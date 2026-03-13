from __future__ import annotations

import argparse
import copy
import csv
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

try:
    import boto3
    from botocore.config import Config
except Exception:  # noqa: BLE001
    boto3 = None
    Config = None

AZURE_BASE_URL = "https://prices.azure.com/api/retail/prices"
AWS_BASE_URL = "https://pricing.us-east-1.amazonaws.com"
HOURS_PER_MONTH = 730
HOURS_PER_YEAR = 12 * HOURS_PER_MONTH


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_json(url: str, timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "vm-pricing-retail-api-skill/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def fetch_azure_all_items(url: str, timeout: int, max_pages: int = 20) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_url: str | None = url
    page_count = 0

    while next_url and page_count < max_pages:
        payload = get_json(next_url, timeout=timeout)
        page_items = payload.get("Items", [])
        if isinstance(page_items, list):
            items.extend([item for item in page_items if isinstance(item, dict)])
        next_url = payload.get("NextPageLink")
        page_count += 1

    return items


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def is_azure_base_vm_line(item: dict[str, Any]) -> bool:
    meter = str(item.get("meterName") or "").lower()
    sku_name = str(item.get("skuName") or "").lower()
    product_name = str(item.get("productName") or "").lower()

    bad_tokens = [
        "spot",
        "low priority",
        "windows hybrid benefit",
        "dedicated host",
        "dev test",
        "cloud services",
        "promotion",
    ]
    text = f"{meter} {sku_name} {product_name}"
    return not any(token in text for token in bad_tokens)


def azure_os_match(item: dict[str, Any], os_name: str) -> bool:
    text = " ".join(
        [
            str(item.get("productName") or ""),
            str(item.get("meterName") or ""),
            str(item.get("skuName") or ""),
        ]
    ).lower()
    if os_name == "windows":
        return "windows" in text
    return "windows" not in text


def azure_family_prefix(sku: str) -> str:
    token = str(sku or "").strip()
    if not token:
        return token

    # Standard_E4as_v5 -> Standard_E4as_
    version_suffix = re.search(r"(?i)^(.*)_v\d+$", token)
    if version_suffix:
        return f"{version_suffix.group(1)}_"

    # If caller already provided a family-like value, keep it as-is.
    return token


def azure_sku_generation(sku: str) -> int | None:
    match = re.search(r"(?i)_v(\d+)$", str(sku or "").strip())
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _pick_azure_sku_for_pricing(items: list[dict[str, Any]]) -> tuple[str | None, int | None, bool, str]:
    sku_generations: dict[str, int | None] = {}
    for item in items:
        sku = str(item.get("armSkuName") or "").strip()
        if not sku:
            continue
        sku_generations[sku] = azure_sku_generation(sku)

    if not sku_generations:
        return None, None, False, "not_found"

    sku_price_anchor: dict[str, float] = {}
    for item in items:
        sku = str(item.get("armSkuName") or "").strip()
        if not sku:
            continue
        price = safe_float(item.get("retailPrice"))
        if price is None:
            continue
        if sku not in sku_price_anchor or price < sku_price_anchor[sku]:
            sku_price_anchor[sku] = price

    v4_plus_skus = [sku for sku, generation in sku_generations.items() if generation is not None and generation >= 4]
    if v4_plus_skus:
        priced = [sku for sku in v4_plus_skus if sku in sku_price_anchor]
        if priced:
            selected = min(priced, key=lambda sku: sku_price_anchor[sku])
        else:
            selected = sorted(v4_plus_skus)[0]
        return selected, sku_generations.get(selected), False, "v4_plus_cheapest"

    numeric_generations = [generation for generation in sku_generations.values() if generation is not None]
    if numeric_generations:
        latest_generation = max(numeric_generations)
        latest_skus = [sku for sku, generation in sku_generations.items() if generation == latest_generation]
        priced = [sku for sku in latest_skus if sku in sku_price_anchor]
        if priced:
            selected = min(priced, key=lambda sku: sku_price_anchor[sku])
        else:
            selected = sorted(latest_skus)[0]
        return selected, latest_generation, True, "latest_below_v4"

    selected = min(sku_generations.keys(), key=lambda sku: sku_price_anchor.get(sku, float("inf")))
    return selected, None, True, "unversioned_family"


def _filter_azure_items_by_sku(items: list[dict[str, Any]], sku: str | None) -> list[dict[str, Any]]:
    if not sku:
        return []
    return [item for item in items if str(item.get("armSkuName") or "").strip() == sku]


def fetch_azure_vm_prices(sku: str, region: str, os_name: str, timeout: int) -> dict[str, Any]:
    cache_key = _azure_request_key(sku, region, os_name)
    cached = _AZURE_PRICE_CACHE.get(cache_key)
    if cached is not None:
        return copy.deepcopy(cached)

    family_prefix = azure_family_prefix(sku)
    filter_expr = (
        f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' "
        f"and startswith(armSkuName, '{family_prefix}')"
    )
    query = urllib.parse.urlencode({"currencyCode": "USD", "$filter": filter_expr})
    url = f"{AZURE_BASE_URL}?{query}"

    try:
        items = fetch_azure_all_items(url, timeout=timeout)
        consumption = [item for item in items if str(item.get("type") or "").lower() == "consumption"]
        reservation = [item for item in items if str(item.get("type") or "").lower() == "reservation"]

        base_consumption = [item for item in consumption if is_azure_base_vm_line(item) and azure_os_match(item, os_name)]
        base_reservation = [item for item in reservation if is_azure_base_vm_line(item) and azure_os_match(item, os_name)]

        selected_sku, selected_generation, review_required, selection_mode = _pick_azure_sku_for_pricing(
            base_consumption + base_reservation
        )
        selected_consumption = _filter_azure_items_by_sku(base_consumption, selected_sku)
        selected_reservation = _filter_azure_items_by_sku(base_reservation, selected_sku)

        paygo = None
        paygo_meta: dict[str, Any] = {"status": "not_found"}
        if selected_consumption:
            priced = [item for item in selected_consumption if safe_float(item.get("retailPrice")) is not None]
            target = min(priced, key=lambda item: float(item.get("retailPrice"))) if priced else selected_consumption[0]
            paygo = safe_float(target.get("retailPrice"))
            paygo_meta = {
                "status": "ok" if paygo is not None else "not_found",
                "meterName": target.get("meterName"),
                "effectiveStartDate": target.get("effectiveStartDate"),
                "armSkuName": target.get("armSkuName"),
            }

        def pick_ri_hourly(years: int) -> tuple[float | None, dict[str, Any]]:
            target_term = "1 year" if years == 1 else "3 years"
            candidates = [
                item
                for item in selected_reservation
                if str(item.get("reservationTerm") or "").strip().lower() == target_term
            ]
            if not candidates:
                return None, {"status": "not_found"}

            best: tuple[float, dict[str, Any]] | None = None
            for item in candidates:
                total = safe_float(item.get("retailPrice"))
                if total is None:
                    continue
                hourly = total / (HOURS_PER_YEAR * years)
                if best is None or hourly < best[0]:
                    best = (hourly, item)

            if best is None:
                return None, {"status": "not_found"}

            hourly, target = best
            return hourly, {
                "status": "ok",
                "reservationTerm": target.get("reservationTerm"),
                "effectiveStartDate": target.get("effectiveStartDate"),
                "meterName": target.get("meterName"),
                "armSkuName": target.get("armSkuName"),
            }

        ri_1y, ri_1y_meta = pick_ri_hourly(1)
        ri_3y, ri_3y_meta = pick_ri_hourly(3)

        status = "ok" if any(v is not None for v in [paygo, ri_1y, ri_3y]) else "not_found"
        result = {
            "status": status,
            "source_url": url,
            "paygo_hourly_usd": paygo,
            "ri_1y_hourly_usd": ri_1y,
            "ri_3y_hourly_usd": ri_3y,
            "review_flag": review_required,
            "meta": {
                "requested_sku": sku,
                "sku_family_prefix": family_prefix,
                "selected_sku": selected_sku,
                "selected_generation": selected_generation,
                "selection_mode": selection_mode,
                "paygo": paygo_meta,
                "ri_1y": ri_1y_meta,
                "ri_3y": ri_3y_meta,
            },
        }
        _AZURE_PRICE_CACHE[cache_key] = result
        return copy.deepcopy(result)
    except Exception as exc:
        result = {
            "status": "error",
            "source_url": url,
            "error": str(exc),
            "paygo_hourly_usd": None,
            "ri_1y_hourly_usd": None,
            "ri_3y_hourly_usd": None,
            "review_flag": False,
        }
        _AZURE_PRICE_CACHE[cache_key] = result
        return copy.deepcopy(result)


def aws_os_name(os_name: str) -> str:
    return "Windows" if os_name == "windows" else "Linux"


_AWS_REGION_INDEX_CACHE: dict[str, Any] | None = None
_AWS_REGION_PAYLOAD_CACHE: dict[str, dict[str, Any]] = {}
_AWS_LOCATION_NAME_CACHE: dict[str, str] | None = None
_AZURE_PRICE_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}


def resolve_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_aws_location_mapping_from_asset() -> dict[str, str]:
    mapping_file = resolve_project_root() / "data" / "get_regions.csv"
    if not mapping_file.exists():
        mapping_file = resolve_project_root() / "data" / "rget_regions.csv"
    if not mapping_file.exists():
        return {}

    try:
        if mapping_file.suffix.lower() == ".csv":
            df = pd.read_csv(mapping_file)
        else:
            df = pd.read_excel(mapping_file)
    except Exception:  # noqa: BLE001
        return {}

    required = {"Cloud", "Region", "Region Long Name"}
    if not required.issubset(set(df.columns)):
        return {}

    mapping: dict[str, str] = {}
    for _, row in df.iterrows():
        cloud = str(row.get("Cloud") or "").strip().lower()
        region = str(row.get("Region") or "").strip().lower()
        region_long_name = str(row.get("Region Long Name") or "").strip()
        if cloud == "aws" and region and region_long_name:
            mapping[region] = region_long_name
    return mapping


def _aws_region_location_name(region: str) -> str:
    global _AWS_LOCATION_NAME_CACHE
    if _AWS_LOCATION_NAME_CACHE is None:
        _AWS_LOCATION_NAME_CACHE = _load_aws_location_mapping_from_asset()

    region_key = str(region or "").strip().lower()
    if region_key in _AWS_LOCATION_NAME_CACHE:
        return _AWS_LOCATION_NAME_CACHE[region_key]

    mapping = {
        "us-east-1": "US East (N. Virginia)",
        "us-east-2": "US East (Ohio)",
        "us-west-1": "US West (N. California)",
        "us-west-2": "US West (Oregon)",
        "ap-southeast-1": "Asia Pacific (Singapore)",
        "ap-southeast-2": "Asia Pacific (Sydney)",
        "ap-southeast-3": "Asia Pacific (Jakarta)",
        "ap-northeast-1": "Asia Pacific (Tokyo)",
        "ap-northeast-2": "Asia Pacific (Seoul)",
        "ap-south-1": "Asia Pacific (Mumbai)",
        "eu-west-1": "EU (Ireland)",
        "eu-west-2": "EU (London)",
        "eu-central-1": "EU (Frankfurt)",
    }
    return mapping.get(region_key, region)


def _aws_load_region_index(timeout: int) -> dict[str, Any]:
    global _AWS_REGION_INDEX_CACHE
    if _AWS_REGION_INDEX_CACHE is not None:
        return _AWS_REGION_INDEX_CACHE

    index_url = f"{AWS_BASE_URL}/offers/v1.0/aws/AmazonEC2/current/region_index.json"
    payload = get_json(index_url, timeout=timeout)
    _AWS_REGION_INDEX_CACHE = payload
    return payload


def _aws_load_region_offer_payload(region: str, timeout: int) -> tuple[dict[str, Any], str]:
    if region in _AWS_REGION_PAYLOAD_CACHE:
        payload = _AWS_REGION_PAYLOAD_CACHE[region]
        return payload, str(payload.get("_source_url") or "")

    index_payload = _aws_load_region_index(timeout=timeout)
    regions = index_payload.get("regions", {})
    entry = regions.get(region)
    if not isinstance(entry, dict):
        raise ValueError(f"aws region not found in pricing index: {region}")

    version_url = entry.get("currentVersionUrl")
    if not version_url:
        raise ValueError(f"aws region currentVersionUrl missing: {region}")

    source_url = f"{AWS_BASE_URL}{version_url}"
    payload = get_json(source_url, timeout=timeout)
    payload["_source_url"] = source_url
    _AWS_REGION_PAYLOAD_CACHE[region] = payload
    return payload, source_url


def _aws_find_sku(payload: dict[str, Any], instance_type: str, os_name: str) -> str | None:
    products = payload.get("products", {})
    target_os = aws_os_name(os_name)

    strict_match: str | None = None
    relaxed_match: str | None = None

    for sku, product in products.items():
        attrs = product.get("attributes", {})
        if attrs.get("instanceType") != instance_type:
            continue
        if attrs.get("operatingSystem") != target_os:
            continue

        if relaxed_match is None:
            relaxed_match = sku

        if (
            attrs.get("preInstalledSw") == "NA"
            and attrs.get("tenancy") == "Shared"
            and attrs.get("capacitystatus") == "Used"
            and attrs.get("operation") == "RunInstances"
        ):
            strict_match = sku
            break

    return strict_match or relaxed_match


def _aws_pick_paygo_from_offer(payload: dict[str, Any], sku: str) -> tuple[float | None, dict[str, Any]]:
    terms = payload.get("terms", {}).get("OnDemand", {}).get(sku, {})
    if not terms:
        return None, {"status": "not_found"}

    best: tuple[float, dict[str, Any], dict[str, Any]] | None = None
    for term in terms.values():
        for dim in term.get("priceDimensions", {}).values():
            unit = str(dim.get("unit") or "").lower()
            if "hrs" not in unit:
                continue
            price = safe_float(dim.get("pricePerUnit", {}).get("USD"))
            if price is None:
                continue
            if best is None or price < best[0]:
                best = (price, term, dim)

    if best is None:
        return None, {"status": "not_found"}

    price, term, dim = best
    return price, {
        "status": "ok",
        "effectiveDate": term.get("effectiveDate"),
        "description": dim.get("description"),
        "unit": dim.get("unit"),
    }


def _aws_pick_ri_from_offer(payload: dict[str, Any], sku: str, years: int) -> tuple[float | None, dict[str, Any]]:
    terms = payload.get("terms", {}).get("Reserved", {}).get(sku, {})
    if not terms:
        return None, {"status": "not_found"}

    target_length = "1yr" if years == 1 else "3yr"
    term_hours = HOURS_PER_YEAR * years
    best: tuple[float, dict[str, Any], dict[str, Any]] | None = None

    for reserved_term in terms.values():
        attrs = reserved_term.get("termAttributes", {})
        if str(attrs.get("LeaseContractLength") or "").lower() != target_length:
            continue
        if str(attrs.get("OfferingClass") or "").lower() != "standard":
            continue

        hourly_part = 0.0
        upfront_part = 0.0
        has_price = False

        for dim in reserved_term.get("priceDimensions", {}).values():
            price = safe_float(dim.get("pricePerUnit", {}).get("USD"))
            if price is None:
                continue
            has_price = True
            unit = str(dim.get("unit") or "").lower()
            if "hrs" in unit:
                hourly_part += price
            else:
                upfront_part += price

        if not has_price:
            continue

        normalized = (upfront_part + hourly_part * term_hours) / term_hours
        if best is None or normalized < best[0]:
            best = (normalized, reserved_term, attrs)

    if best is None:
        return None, {"status": "not_found"}

    normalized, reserved_term, attrs = best
    return normalized, {
        "status": "ok",
        "effectiveDate": reserved_term.get("effectiveDate"),
        "term": target_length,
        "purchaseOption": attrs.get("PurchaseOption"),
        "offeringClass": attrs.get("OfferingClass"),
        "normalized_by": f"(upfront + hourly * ({years} * 12 * 730)) / ({years} * 12 * 730)",
    }


def _fetch_aws_vm_prices_from_offer_file(instance_type: str, region: str, os_name: str, timeout: int) -> dict[str, Any]:
    payload, source_url = _aws_load_region_offer_payload(region=region, timeout=timeout)
    sku = _aws_find_sku(payload=payload, instance_type=instance_type, os_name=os_name)

    if not sku:
        return {
            "status": "not_found",
            "source_url": source_url,
            "sku_match_mode": "offer_file",
            "paygo_hourly_usd": None,
            "ri_1y_hourly_usd": None,
            "ri_3y_hourly_usd": None,
            "meta": {"sku": None},
        }

    paygo, paygo_meta = _aws_pick_paygo_from_offer(payload, sku)
    ri_1y, ri_1y_meta = _aws_pick_ri_from_offer(payload, sku, 1)
    ri_3y, ri_3y_meta = _aws_pick_ri_from_offer(payload, sku, 3)
    status = "ok" if any(v is not None for v in [paygo, ri_1y, ri_3y]) else "not_found"

    return {
        "status": status,
        "source_url": source_url,
        "sku_match_mode": "offer_file",
        "paygo_hourly_usd": paygo,
        "ri_1y_hourly_usd": ri_1y,
        "ri_3y_hourly_usd": ri_3y,
        "meta": {
            "sku": sku,
            "paygo": paygo_meta,
            "ri_1y": ri_1y_meta,
            "ri_3y": ri_3y_meta,
        },
    }


def _aws_pricing_client(timeout: int):
    if boto3 is None or Config is None:
        raise RuntimeError("boto3/botocore not available for AWS Pricing API query mode")

    config = Config(connect_timeout=timeout, read_timeout=timeout, retries={"max_attempts": 3, "mode": "standard"})
    return boto3.client("pricing", region_name="us-east-1", config=config)


def _aws_get_products(filters: list[dict[str, str]], timeout: int) -> list[dict[str, Any]]:
    client = _aws_pricing_client(timeout=timeout)
    products: list[dict[str, Any]] = []
    next_token: str | None = None

    while True:
        kwargs: dict[str, Any] = {
            "ServiceCode": "AmazonEC2",
            "FormatVersion": "aws_v1",
            "Filters": filters,
            "MaxResults": 100,
        }
        if next_token:
            kwargs["NextToken"] = next_token

        response = client.get_products(**kwargs)
        for price_item in response.get("PriceList", []):
            try:
                parsed = json.loads(price_item)
            except Exception:  # noqa: BLE001
                continue
            if isinstance(parsed, dict):
                products.append(parsed)

        next_token = response.get("NextToken")
        if not next_token:
            break

    return products


def _aws_base_filters(instance_type: str, region: str, os_name: str) -> list[dict[str, str]]:
    return [
        {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
        {"Type": "TERM_MATCH", "Field": "regionCode", "Value": region},
        {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": aws_os_name(os_name)},
        {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
        {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
        {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
        {"Type": "TERM_MATCH", "Field": "operation", "Value": "RunInstances"},
    ]


def _extract_aws_paygo(products: list[dict[str, Any]]) -> tuple[float | None, dict[str, Any]]:
    best: tuple[float, dict[str, Any], dict[str, Any], str] | None = None

    for product in products:
        sku = str(product.get("product", {}).get("sku") or "")
        on_demand_terms = product.get("terms", {}).get("OnDemand", {})
        for term in on_demand_terms.values():
            for dim in term.get("priceDimensions", {}).values():
                unit = str(dim.get("unit") or "").lower()
                if "hrs" not in unit:
                    continue
                price = safe_float(dim.get("pricePerUnit", {}).get("USD"))
                if price is None:
                    continue
                if best is None or price < best[0]:
                    best = (price, product, term, sku)

    if best is None:
        return None, {"status": "not_found"}

    price, product, term, sku = best
    attrs = product.get("product", {}).get("attributes", {})
    return price, {
        "status": "ok",
        "effectiveDate": term.get("effectiveDate"),
        "sku": sku,
        "instanceType": attrs.get("instanceType"),
        "regionCode": attrs.get("regionCode"),
        "location": attrs.get("location"),
    }


def _extract_aws_ri(products: list[dict[str, Any]], years: int) -> tuple[float | None, dict[str, Any]]:
    target_length = "1yr" if years == 1 else "3yr"
    term_hours = HOURS_PER_MONTH * 12 * years
    best: tuple[float, dict[str, Any], dict[str, Any], str, dict[str, Any]] | None = None

    for product in products:
        sku = str(product.get("product", {}).get("sku") or "")
        attrs = product.get("product", {}).get("attributes", {})
        reserved_terms = product.get("terms", {}).get("Reserved", {})
        for term in reserved_terms.values():
            term_attrs = term.get("termAttributes", {})
            if str(term_attrs.get("LeaseContractLength") or "").lower() != target_length:
                continue
            if str(term_attrs.get("OfferingClass") or "").lower() != "standard":
                continue

            hourly_part = 0.0
            upfront_part = 0.0
            has_price = False
            for dim in term.get("priceDimensions", {}).values():
                price = safe_float(dim.get("pricePerUnit", {}).get("USD"))
                if price is None:
                    continue
                has_price = True
                unit = str(dim.get("unit") or "").lower()
                if "hrs" in unit:
                    hourly_part += price
                else:
                    upfront_part += price

            if not has_price:
                continue

            normalized = (upfront_part + hourly_part * term_hours) / term_hours
            if best is None or normalized < best[0]:
                best = (normalized, product, term, sku, attrs)

    if best is None:
        return None, {"status": "not_found"}

    normalized, _, term, sku, attrs = best
    return normalized, {
        "status": "ok",
        "effectiveDate": term.get("effectiveDate"),
        "sku": sku,
        "instanceType": attrs.get("instanceType"),
        "regionCode": attrs.get("regionCode"),
        "location": attrs.get("location"),
        "lease": target_length,
        "normalized_by": f"(upfront + hourly * ({years} * 12 * 730)) / ({years} * 12 * 730)",
    }


def fetch_aws_vm_prices(instance_type: str, region: str, os_name: str, timeout: int) -> dict[str, Any]:
    try:
        return _fetch_aws_vm_prices_from_offer_file(
            instance_type=instance_type,
            region=region,
            os_name=os_name,
            timeout=timeout,
        )
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "source_url": "aws-offer-file",
            "paygo_hourly_usd": None,
            "ri_1y_hourly_usd": None,
            "ri_3y_hourly_usd": None,
        }


def first_non_empty(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def normalize_os(os_value: Any) -> str:
    token = str(os_value or "linux").strip().lower()
    return "windows" if token == "windows" else "linux"


def infer_compete_cloud(row: dict[str, Any]) -> str:
    token = str(
        first_non_empty(
            row,
            [
                "compete_cloud",
                "competitor_cloud",
                "provider",
                "cloud",
            ],
            "",
        )
        or ""
    ).strip().lower()
    return token


def _azure_request_key(sku: str, region: str, os_name: str) -> tuple[str, str, str]:
    return (str(sku).strip(), str(region).strip(), normalize_os(os_name))


def _aws_request_key(instance_type: str, region: str, os_name: str) -> tuple[str, str, str]:
    return (str(instance_type).strip(), str(region).strip(), normalize_os(os_name))


def run_query(
    aws_instance_type: str | None,
    aws_region: str | None,
    azure_sku: str | None,
    azure_region: str | None,
    os_name: str,
    timeout: int,
    skip_aws: bool,
    skip_azure: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": "ok",
        "fetched_at": now_iso(),
        "input": {
            "aws_instance_type": aws_instance_type,
            "aws_region": aws_region,
            "azure_sku": azure_sku,
            "azure_region": azure_region,
            "os": os_name,
        },
    }

    if skip_azure:
        result["azure"] = {"status": "skipped"}
    else:
        result["azure"] = fetch_azure_vm_prices(str(azure_sku), str(azure_region), os_name, timeout)

    if skip_aws:
        result["aws"] = {"status": "skipped"}
    else:
        result["aws"] = fetch_aws_vm_prices(str(aws_instance_type), str(aws_region), os_name, timeout)

    if result.get("azure", {}).get("status") == "error" and result.get("aws", {}).get("status") == "error":
        result["status"] = "error"

    return result


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", encoding="utf-8", newline="") as fp:
            fp.write("")
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch VM prices from AWS/Azure retail APIs")

    parser.add_argument("--aws-instance-type", help="AWS instance type, e.g. m6a.4xlarge")
    parser.add_argument("--aws-region", help="AWS region, e.g. ap-southeast-1")
    parser.add_argument("--azure-sku", help="Azure VM SKU, e.g. Standard_D16as_v5")
    parser.add_argument("--azure-region", help="Azure region, e.g. southeastasia")
    parser.add_argument("--os", choices=["linux", "windows"], default="linux")
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--skip-aws", action="store_true")
    parser.add_argument("--skip-azure", action="store_true")
    parser.add_argument("--input-file", help="Batch mode CSV input")
    parser.add_argument("--output", default="output/vm_pricing_results.csv", help="Batch mode CSV output")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.input_file:
        input_file = Path(args.input_file)
        if not input_file.is_absolute():
            input_file = Path.cwd() / input_file
        if not input_file.exists():
            raise FileNotFoundError(f"Input file not found: {input_file.as_posix()}")

        with input_file.open("r", encoding="utf-8-sig", newline="") as fp:
            rows = list(csv.DictReader(fp))

        prepared_rows: list[dict[str, Any]] = []
        azure_keys: set[tuple[str, str, str]] = set()
        aws_keys: set[tuple[str, str, str]] = set()

        for row in rows:
            aws_instance_type = first_non_empty(row, ["aws_instance_type", "instance_type"])
            aws_region = first_non_empty(row, ["aws_region", "mapped_aws_region", "region_aws"])
            azure_sku = first_non_empty(row, ["azure_sku", "primary_sku"])
            sap_sku = first_non_empty(row, ["sap_sku"])
            azure_region = first_non_empty(row, ["azure_region", "mapped_azure_region", "region_azure"])
            os_name = normalize_os(first_non_empty(row, ["os"], "linux"))
            compete_cloud = infer_compete_cloud(row)

            # If source data explicitly says the competitor cloud is AWS, do not skip AWS pricing.
            # This guards against accidental --skip-aws usage in quote comparison workflows.
            force_compare_aws = compete_cloud == "aws"
            skip_aws = (args.skip_aws and not force_compare_aws) or not (aws_instance_type and aws_region)
            skip_azure = args.skip_azure or not (azure_sku and azure_region)

            prepared_rows.append(
                {
                    "row": row,
                    "aws_instance_type": str(aws_instance_type) if aws_instance_type else None,
                    "aws_region": str(aws_region) if aws_region else None,
                    "azure_sku": str(azure_sku) if azure_sku else None,
                    "sap_sku": str(sap_sku) if sap_sku else None,
                    "azure_region": str(azure_region) if azure_region else None,
                    "os_name": os_name,
                    "skip_aws": skip_aws,
                    "skip_azure": skip_azure,
                }
            )

            if not skip_azure and azure_sku and azure_region:
                azure_keys.add(_azure_request_key(str(azure_sku), str(azure_region), os_name))
            if sap_sku and azure_region:
                azure_keys.add(_azure_request_key(str(sap_sku), str(azure_region), os_name))
            if not skip_aws and aws_instance_type and aws_region:
                aws_keys.add(_aws_request_key(str(aws_instance_type), str(aws_region), os_name))

        azure_results: dict[tuple[str, str, str], dict[str, Any]] = {}
        for azure_sku, azure_region, os_name in azure_keys:
            azure_results[(azure_sku, azure_region, os_name)] = fetch_azure_vm_prices(
                sku=azure_sku,
                region=azure_region,
                os_name=os_name,
                timeout=args.timeout,
            )

        aws_results: dict[tuple[str, str, str], dict[str, Any]] = {}
        for aws_instance_type, aws_region, os_name in aws_keys:
            aws_results[(aws_instance_type, aws_region, os_name)] = fetch_aws_vm_prices(
                instance_type=aws_instance_type,
                region=aws_region,
                os_name=os_name,
                timeout=args.timeout,
            )

        output_rows: list[dict[str, Any]] = []
        for prepared in prepared_rows:
            row = prepared["row"]
            aws_instance_type = prepared["aws_instance_type"]
            aws_region = prepared["aws_region"]
            azure_sku = prepared["azure_sku"]
            sap_sku = prepared["sap_sku"]
            azure_region = prepared["azure_region"]
            os_name = prepared["os_name"]
            skip_aws = bool(prepared["skip_aws"])
            skip_azure = bool(prepared["skip_azure"])

            if skip_aws and skip_azure:
                result: dict[str, Any] = {
                    "status": "invalid_input",
                    "error": "Both clouds skipped or missing required columns for both clouds",
                    "input": {
                        "aws_instance_type": aws_instance_type,
                        "aws_region": aws_region,
                        "azure_sku": azure_sku,
                        "azure_region": azure_region,
                        "os": os_name,
                    },
                    "aws": {"status": "skipped"},
                    "azure": {"status": "skipped"},
                }
            else:
                result = {
                    "status": "ok",
                    "fetched_at": now_iso(),
                    "input": {
                        "aws_instance_type": aws_instance_type,
                        "aws_region": aws_region,
                        "azure_sku": azure_sku,
                        "azure_region": azure_region,
                        "os": os_name,
                    },
                }

                if skip_azure:
                    result["azure"] = {"status": "skipped"}
                else:
                    azure_key = _azure_request_key(str(azure_sku), str(azure_region), os_name)
                    result["azure"] = copy.deepcopy(azure_results[azure_key])

                if skip_aws:
                    result["aws"] = {"status": "skipped"}
                else:
                    aws_key = _aws_request_key(str(aws_instance_type), str(aws_region), os_name)
                    result["aws"] = copy.deepcopy(aws_results[aws_key])

                if result.get("azure", {}).get("status") == "error" and result.get("aws", {}).get("status") == "error":
                    result["status"] = "error"

            sap_azure: dict[str, Any] = {"status": "skipped"}
            if sap_sku and azure_region:
                sap_key = _azure_request_key(str(sap_sku), str(azure_region), os_name)
                sap_azure = copy.deepcopy(azure_results[sap_key])

            merged = dict(row)
            merged.update(
                {
                    "pricing_status": result.get("status"),
                    "azure_status": result.get("azure", {}).get("status"),
                    "Azure_paygo": result.get("azure", {}).get("paygo_hourly_usd"),
                    "Azure_1YRI": result.get("azure", {}).get("ri_1y_hourly_usd"),
                    "Azure_3YRI": result.get("azure", {}).get("ri_3y_hourly_usd"),
                    "Azure_review_flag": result.get("azure", {}).get("review_flag"),
                    "sap_azure_status": sap_azure.get("status"),
                    "Azure_SAP_paygo": sap_azure.get("paygo_hourly_usd"),
                    "Azure_SAP_1YRI": sap_azure.get("ri_1y_hourly_usd"),
                    "Azure_SAP_3YRI": sap_azure.get("ri_3y_hourly_usd"),
                    "Azure_SAP_review_flag": sap_azure.get("review_flag"),
                    "aws_status": result.get("aws", {}).get("status"),
                    "AWS_paygo": result.get("aws", {}).get("paygo_hourly_usd"),
                    "AWS_1YRI": result.get("aws", {}).get("ri_1y_hourly_usd"),
                    "AWS_3YRI": result.get("aws", {}).get("ri_3y_hourly_usd"),
                    "pricing_error": result.get("error")
                    or result.get("aws", {}).get("error")
                    or result.get("azure", {}).get("error")
                    or sap_azure.get("error"),
                    "pricing_result_json": json.dumps(result, ensure_ascii=False),
                }
            )
            output_rows.append(merged)

        output_file = Path(args.output)
        if not output_file.is_absolute():
            output_file = Path.cwd() / output_file
        write_csv(output_file, output_rows)

        print(
            json.dumps(
                {
                    "status": "ok",
                    "rows": len(output_rows),
                    "input_file": input_file.as_posix(),
                    "output_file": output_file.as_posix(),
                },
                ensure_ascii=False,
            )
        )
        return

    if args.skip_aws and args.skip_azure:
        raise ValueError("Cannot set both --skip-aws and --skip-azure")

    if not args.skip_azure and (not args.azure_sku or not args.azure_region):
        raise ValueError("Azure query requires --azure-sku and --azure-region unless --skip-azure is set")

    if not args.skip_aws and (not args.aws_instance_type or not args.aws_region):
        raise ValueError("AWS query requires --aws-instance-type and --aws-region unless --skip-aws is set")

    result = run_query(
        aws_instance_type=args.aws_instance_type,
        aws_region=args.aws_region,
        azure_sku=args.azure_sku,
        azure_region=args.azure_region,
        os_name=args.os,
        timeout=args.timeout,
        skip_aws=args.skip_aws,
        skip_azure=args.skip_azure,
    )

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
