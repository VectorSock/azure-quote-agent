from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

AZURE_BASE_URL = "https://prices.azure.com/api/retail/prices"
AWS_BASE_URL = "https://pricing.us-east-1.amazonaws.com"
HOURS_PER_YEAR = 24 * 365


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def get_json(url: str, timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "vm-pricing-retail-api-skill/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


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


def fetch_azure_vm_prices(sku: str, region: str, os_name: str, timeout: int) -> dict[str, Any]:
    filter_expr = f"serviceName eq 'Virtual Machines' and armRegionName eq '{region}' and armSkuName eq '{sku}'"
    query = urllib.parse.urlencode({"$filter": filter_expr})
    url = f"{AZURE_BASE_URL}?{query}"

    try:
        payload = get_json(url, timeout=timeout)
        items = payload.get("Items", [])
        consumption = [item for item in items if str(item.get("type") or "").lower() == "consumption"]
        reservation = [item for item in items if str(item.get("type") or "").lower() == "reservation"]

        base_consumption = [item for item in consumption if is_azure_base_vm_line(item) and azure_os_match(item, os_name)]
        base_reservation = [item for item in reservation if is_azure_base_vm_line(item) and azure_os_match(item, os_name)]

        paygo = None
        paygo_meta: dict[str, Any] = {"status": "not_found"}
        if base_consumption:
            target = base_consumption[0]
            paygo = safe_float(target.get("retailPrice"))
            paygo_meta = {
                "status": "ok" if paygo is not None else "not_found",
                "meterName": target.get("meterName"),
                "effectiveStartDate": target.get("effectiveStartDate"),
            }

        def pick_ri_hourly(years: int) -> tuple[float | None, dict[str, Any]]:
            target_term = "1 year" if years == 1 else "3 years"
            candidates = [
                item
                for item in base_reservation
                if str(item.get("reservationTerm") or "").strip().lower() == target_term
            ]
            if not candidates:
                return None, {"status": "not_found"}
            target = candidates[0]
            total = safe_float(target.get("retailPrice"))
            if total is None:
                return None, {"status": "not_found"}
            hourly = total / (HOURS_PER_YEAR * years)
            return hourly, {
                "status": "ok",
                "reservationTerm": target.get("reservationTerm"),
                "effectiveStartDate": target.get("effectiveStartDate"),
                "meterName": target.get("meterName"),
            }

        ri_1y, ri_1y_meta = pick_ri_hourly(1)
        ri_3y, ri_3y_meta = pick_ri_hourly(3)

        status = "ok" if any(v is not None for v in [paygo, ri_1y, ri_3y]) else "not_found"
        return {
            "status": status,
            "source_url": url,
            "paygo_hourly_usd": paygo,
            "ri_1y_hourly_usd": ri_1y,
            "ri_3y_hourly_usd": ri_3y,
            "meta": {
                "paygo": paygo_meta,
                "ri_1y": ri_1y_meta,
                "ri_3y": ri_3y_meta,
            },
        }
    except BaseException as exc:  # noqa: BLE001
        return {
            "status": "error",
            "source_url": url,
            "error": str(exc),
            "paygo_hourly_usd": None,
            "ri_1y_hourly_usd": None,
            "ri_3y_hourly_usd": None,
        }


def aws_os_name(os_name: str) -> str:
    return "Windows" if os_name == "windows" else "Linux"


def load_aws_region_offer(region: str, timeout: int) -> tuple[dict[str, Any], str]:
    region_index_url = f"{AWS_BASE_URL}/offers/v1.0/aws/AmazonEC2/current/region_index.json"
    region_index = get_json(region_index_url, timeout=timeout)
    regions = region_index.get("regions", {})
    if region not in regions:
        raise ValueError(f"aws region not found in pricing index: {region}")

    version_url = regions[region].get("currentVersionUrl")
    if not version_url:
        raise ValueError(f"aws region has no version url: {region}")

    offer_url = f"{AWS_BASE_URL}{version_url}"
    payload = get_json(offer_url, timeout=timeout)
    return payload, offer_url


def find_aws_sku(payload: dict[str, Any], instance_type: str, os_name: str) -> tuple[str | None, str]:
    target_os = aws_os_name(os_name)
    products = payload.get("products", {})

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

    if strict_match:
        return strict_match, "strict"
    if relaxed_match:
        return relaxed_match, "relaxed"
    return None, "none"


def pick_aws_paygo_hourly(payload: dict[str, Any], sku: str) -> tuple[float | None, dict[str, Any]]:
    on_demand = payload.get("terms", {}).get("OnDemand", {}).get(sku, {})
    if not on_demand:
        return None, {"status": "not_found"}

    term = next(iter(on_demand.values()))
    dimensions = term.get("priceDimensions", {})
    if not dimensions:
        return None, {"status": "not_found"}

    dim = next(iter(dimensions.values()))
    price = safe_float(dim.get("pricePerUnit", {}).get("USD"))
    return price, {
        "status": "ok" if price is not None else "not_found",
        "effectiveDate": term.get("effectiveDate"),
        "description": dim.get("description"),
        "unit": dim.get("unit"),
    }


def pick_aws_ri_hourly(payload: dict[str, Any], sku: str, years: int) -> tuple[float | None, dict[str, Any]]:
    reserved = payload.get("terms", {}).get("Reserved", {}).get(sku, {})
    if not reserved:
        return None, {"status": "not_found"}

    target_length = "1yr" if years == 1 else "3yr"
    term_hours = HOURS_PER_YEAR * years

    for term in reserved.values():
        attrs = term.get("termAttributes", {})
        if attrs.get("LeaseContractLength") != target_length:
            continue
        if attrs.get("PurchaseOption") != "No Upfront":
            continue
        if attrs.get("OfferingClass") != "standard":
            continue

        hourly_part = 0.0
        upfront_part = 0.0
        for dimension in term.get("priceDimensions", {}).values():
            unit = str(dimension.get("unit") or "").lower()
            price = safe_float(dimension.get("pricePerUnit", {}).get("USD")) or 0.0
            if "hrs" in unit:
                hourly_part += price
            else:
                upfront_part += price

        total = upfront_part + hourly_part * term_hours
        normalized = total / term_hours
        return normalized, {
            "status": "ok",
            "effectiveDate": term.get("effectiveDate"),
            "lease": target_length,
            "purchaseOption": "No Upfront",
            "offeringClass": "standard",
        }

    return None, {"status": "not_found"}


def fetch_aws_vm_prices(instance_type: str, region: str, os_name: str, timeout: int) -> dict[str, Any]:
    try:
        payload, offer_url = load_aws_region_offer(region, timeout=timeout)
        sku, match_mode = find_aws_sku(payload, instance_type, os_name)
        if not sku:
            return {
                "status": "not_found",
                "source_url": offer_url,
                "sku_match_mode": "none",
                "paygo_hourly_usd": None,
                "ri_1y_hourly_usd": None,
                "ri_3y_hourly_usd": None,
            }

        paygo, paygo_meta = pick_aws_paygo_hourly(payload, sku)
        ri_1y, ri_1y_meta = pick_aws_ri_hourly(payload, sku, 1)
        ri_3y, ri_3y_meta = pick_aws_ri_hourly(payload, sku, 3)

        status = "ok" if any(v is not None for v in [paygo, ri_1y, ri_3y]) else "not_found"
        return {
            "status": status,
            "source_url": offer_url,
            "sku": sku,
            "sku_match_mode": match_mode,
            "paygo_hourly_usd": paygo,
            "ri_1y_hourly_usd": ri_1y,
            "ri_3y_hourly_usd": ri_3y,
            "meta": {
                "paygo": paygo_meta,
                "ri_1y": ri_1y_meta,
                "ri_3y": ri_3y_meta,
            },
        }
    except BaseException as exc:  # noqa: BLE001
        return {
            "status": "error",
            "error": str(exc),
            "paygo_hourly_usd": None,
            "ri_1y_hourly_usd": None,
            "ri_3y_hourly_usd": None,
        }


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

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.skip_aws and args.skip_azure:
        raise ValueError("Cannot set both --skip-aws and --skip-azure")

    if not args.skip_azure and (not args.azure_sku or not args.azure_region):
        raise ValueError("Azure query requires --azure-sku and --azure-region unless --skip-azure is set")

    if not args.skip_aws and (not args.aws_instance_type or not args.aws_region):
        raise ValueError("AWS query requires --aws-instance-type and --aws-region unless --skip-aws is set")

    result: dict[str, Any] = {
        "status": "ok",
        "fetched_at": now_iso(),
        "input": {
            "aws_instance_type": args.aws_instance_type,
            "aws_region": args.aws_region,
            "azure_sku": args.azure_sku,
            "azure_region": args.azure_region,
            "os": args.os,
        },
    }

    if args.skip_azure:
        result["azure"] = {"status": "skipped"}
    else:
        result["azure"] = fetch_azure_vm_prices(args.azure_sku, args.azure_region, args.os, args.timeout)

    if args.skip_aws:
        result["aws"] = {"status": "skipped"}
    else:
        result["aws"] = fetch_aws_vm_prices(args.aws_instance_type, args.aws_region, args.os, args.timeout)

    if result.get("azure", {}).get("status") == "error" and result.get("aws", {}).get("status") == "error":
        result["status"] = "error"

    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
