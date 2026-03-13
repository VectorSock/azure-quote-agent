from __future__ import annotations

import argparse
import csv
import json
import math
import re
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any
import sys


SAP_MEMORY_PER_VCPU_GB = 8.0
SUPPORTED_VCPU_STEPS = [2, 4, 8, 16, 20, 24, 32, 48, 64, 72, 80, 96, 104, 112, 120, 128, 144, 176, 192]
APP_LS_DISK_GB_THRESHOLD = 500.0

APP_DB_POLICIES = {"strict", "balanced", "cost-first"}
RANKING_WEIGHTS = {
    "strict": {"fit": 0.3, "perf": 0.5, "cost": 0.2},
    "balanced": {"fit": 0.35, "perf": 0.3, "cost": 0.35},
    "cost-first": {"fit": 0.25, "perf": 0.15, "cost": 0.6},
}

SKU_PARSE_PATTERN = re.compile(r"^Standard_([A-Za-z]+)(\d+)([a-z]*)")
_CATALOG_CACHE: dict[str, dict[str, Any]] = {}

AZURE_RETAIL_API_URL = "https://prices.azure.com/api/retail/prices"
_RETAIL_PRICE_CACHE: dict[str, dict[str, Any]] = {}

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sap_inference import detect_role, infer_sap_workload, normalize_env, normalize_text


def resolve_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def resolve_catalog_path(path_arg: str | None) -> Path:
    if path_arg:
        path = Path(path_arg)
        return path if path.is_absolute() else resolve_project_root() / path
    return resolve_project_root() / ".github" / "skills" / "vm-config-to-azure-instance" / "assets" / "sap_sku_catalog.json"


def load_sku_catalog(path: Path) -> dict[str, dict[str, Any]]:
    cache_key = path.as_posix()
    if cache_key in _CATALOG_CACHE:
        return _CATALOG_CACHE[cache_key]

    if not path.exists():
        _CATALOG_CACHE[cache_key] = {}
        return _CATALOG_CACHE[cache_key]

    with path.open("r", encoding="utf-8") as fp:
        payload = json.load(fp)

    entries = payload.get("skus", []) if isinstance(payload, dict) else payload
    catalog: dict[str, dict[str, Any]] = {}
    if isinstance(entries, list):
        for item in entries:
            if not isinstance(item, dict):
                continue
            sku = str(item.get("sku") or "").strip()
            if not sku:
                continue
            normalized = dict(item)
            normalized["sku"] = sku
            normalized["supported_regions"] = [str(v).strip().lower() for v in (item.get("supported_regions") or []) if str(v).strip()]
            normalized["supported_os"] = [str(v).strip().lower() for v in (item.get("supported_os") or []) if str(v).strip()]
            catalog[sku] = normalized

    _CATALOG_CACHE[cache_key] = catalog
    return catalog


def parse_sku_shape(sku: str) -> dict[str, Any]:
    token = str(sku or "").strip()
    match = SKU_PARSE_PATTERN.match(token)
    if not match:
        return {"family": "", "vcpu": 0, "suffix": ""}

    family_raw = match.group(1)
    family = family_raw[0].upper() if family_raw else ""
    vcpu = int(match.group(2) or 0)
    suffix = str(match.group(3) or "").lower()
    return {"family": family, "vcpu": vcpu, "suffix": suffix}


def parse_optional_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def is_amd_sku(sku: str) -> bool:
    shape = parse_sku_shape(sku)
    suffix = str(shape.get("suffix") or "").lower()
    return "a" in suffix


def estimate_memory_by_family(family: str, vcpu: int) -> float:
    ratio = {
        "D": 4.0,
        "E": 8.0,
        "F": 2.0,
        "B": 4.0,
        "M": 16.0,
    }.get(family.upper(), 4.0)
    return float(vcpu) * ratio


def support_gate_for_candidate(
    *,
    sku: str,
    catalog_entry: dict[str, Any] | None,
    azure_region: str | None,
    os_name: str | None,
    sap_cert_required: bool,
    pam_supported: bool | None,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []

    if pam_supported is False:
        reasons.append("pam_check_failed")
        return False, reasons
    if pam_supported is None:
        reasons.append("pam_check_skipped_no_input")
    else:
        reasons.append("pam_check_passed")

    if catalog_entry is None:
        if sap_cert_required:
            reasons.append("sap_note_gate_failed_unknown_certification")
            return False, reasons
        reasons.append("sap_note_gate_skipped_no_catalog_entry")
        return True, reasons

    if sap_cert_required and not bool(catalog_entry.get("sap_certified", False)):
        reasons.append("sap_note_gate_failed_non_certified_sku")
        return False, reasons
    reasons.append("sap_note_gate_passed")

    supported_regions = catalog_entry.get("supported_regions") or []
    region = str(azure_region or "").strip().lower()
    if supported_regions and region and region not in supported_regions:
        reasons.append("region_gate_failed")
        return False, reasons
    reasons.append("region_gate_passed" if supported_regions else "region_gate_skipped_no_catalog_regions")

    supported_os = catalog_entry.get("supported_os") or []
    normalized_os = str(os_name or "").strip().lower()
    if supported_os and normalized_os and normalized_os not in supported_os:
        reasons.append("os_gate_failed")
        return False, reasons
    reasons.append("os_gate_passed" if supported_os else "os_gate_skipped_no_catalog_os")

    return True, reasons


def normalized_gap_score(actual: float, required: float) -> float:
    if required <= 0:
        return 0.5
    if actual <= 0:
        return 0.0
    if actual >= required:
        return min(1.0, required / actual + 0.2)
    return max(0.0, actual / required)


def estimate_cost_score(family: str, suffix: str) -> float:
    family_factor = {
        "B": 0.6,
        "D": 1.0,
        "E": 1.15,
        "F": 0.95,
        "M": 2.6,
        "N": 3.0,
    }.get(family.upper(), 1.2)
    suffix_factor = {
        "ls": 0.9,
        "as": 0.95,
        "a": 0.97,
        "s": 1.0,
        "ds": 1.05,
        "d": 1.03,
        "": 1.02,
    }.get(suffix.lower(), 1.04)
    rough_cost = family_factor * suffix_factor
    return 1.0 / (1.0 + rough_cost)


# ---------------------------------------------------------------------------
# Azure Retail Prices API helpers for version resolution & real pricing
# ---------------------------------------------------------------------------

def _retail_api_get_json(url: str, timeout: int = 15) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "vm-config-to-azure-instance/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _retail_api_fetch_all(url: str, timeout: int = 15, max_pages: int = 10) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    next_url: str | None = url
    page = 0
    while next_url and page < max_pages:
        payload = _retail_api_get_json(next_url, timeout=timeout)
        page_items = payload.get("Items", [])
        if isinstance(page_items, list):
            items.extend(item for item in page_items if isinstance(item, dict))
        next_url = payload.get("NextPageLink")
        page += 1
    return items


def _is_base_vm_line(item: dict[str, Any]) -> bool:
    text = " ".join([
        str(item.get("meterName") or ""),
        str(item.get("skuName") or ""),
        str(item.get("productName") or ""),
    ]).lower()
    bad = ["spot", "low priority", "dedicated host", "dev test", "cloud services", "promotion"]
    return not any(t in text for t in bad)


def _os_matches_item(item: dict[str, Any], os_name: str | None) -> bool:
    if not os_name:
        return True
    text = " ".join([
        str(item.get("productName") or ""),
        str(item.get("meterName") or ""),
        str(item.get("skuName") or ""),
    ]).lower()
    if os_name == "windows":
        return "windows" in text
    return "windows" not in text


def _sku_generation_num(sku: str) -> int | None:
    m = re.search(r"_v(\d+)$", str(sku or "").strip(), re.IGNORECASE)
    return int(m.group(1)) if m else None


def _strip_sku_version(sku: str) -> str:
    """Standard_E4as_v5 -> Standard_E4as_"""
    m = re.search(r"^(.*)_v\d+$", str(sku or "").strip(), re.IGNORECASE)
    return f"{m.group(1)}_" if m else str(sku or "").strip()


def _select_best_sku_from_api(sku_prices: dict[str, float]) -> dict[str, Any]:
    """Pick best SKU: cheapest v5+, else cheapest v4+, else latest generation."""
    if not sku_prices:
        return {"resolved_sku": None, "paygo_hourly_usd": None, "generation": None, "selection_mode": "not_found"}

    sku_gens = {s: _sku_generation_num(s) for s in sku_prices}

    # Prefer cheapest among v5+
    v5_plus = {s: p for s, p in sku_prices.items() if (sku_gens.get(s) or 0) >= 5}
    if v5_plus:
        best = min(v5_plus, key=lambda s: v5_plus[s])
        return {"resolved_sku": best, "paygo_hourly_usd": v5_plus[best], "generation": sku_gens[best], "selection_mode": "v5_plus_cheapest"}

    # Else cheapest among v4+
    v4_plus = {s: p for s, p in sku_prices.items() if (sku_gens.get(s) or 0) >= 4}
    if v4_plus:
        best = min(v4_plus, key=lambda s: v4_plus[s])
        return {"resolved_sku": best, "paygo_hourly_usd": v4_plus[best], "generation": sku_gens[best], "selection_mode": "v4_plus_cheapest"}

    # Else latest generation
    numeric_gens = [g for g in sku_gens.values() if g is not None]
    if numeric_gens:
        max_gen = max(numeric_gens)
        latest = {s: p for s, p in sku_prices.items() if sku_gens.get(s) == max_gen}
        best = min(latest, key=lambda s: latest[s])
        return {"resolved_sku": best, "paygo_hourly_usd": latest[best], "generation": max_gen, "selection_mode": "latest_gen"}

    # No generation info
    best = min(sku_prices, key=lambda s: sku_prices[s])
    return {"resolved_sku": best, "paygo_hourly_usd": sku_prices[best], "generation": None, "selection_mode": "unversioned_cheapest"}


def resolve_and_price_candidates(
    candidates: list[str],
    azure_region: str,
    os_name: str | None,
    timeout: int = 15,
) -> tuple[list[str], dict[str, float]]:
    """
    Resolve candidate SKUs to actual versions via Azure Retail Prices API.

    For each unique SKU prefix (family+size+suffix), queries the API to find
    all available generations, then selects the best one:
      - cheapest among v5+ if any exist
      - else cheapest among v4+
      - else latest generation

    Returns:
        resolved_candidates: list of resolved SKU names (order preserved, deduped)
        real_prices: dict mapping resolved_sku -> paygo_hourly_usd
    """
    prefix_to_candidates: dict[str, list[str]] = {}
    for sku in candidates:
        prefix = _strip_sku_version(sku)
        if prefix not in prefix_to_candidates:
            prefix_to_candidates[prefix] = []
        prefix_to_candidates[prefix].append(sku)

    resolved_map: dict[str, str] = {}  # original_sku -> resolved_sku
    real_prices: dict[str, float] = {}  # resolved_sku -> price

    for prefix, original_skus in prefix_to_candidates.items():
        cache_key = f"{prefix}|{azure_region}|{os_name or 'linux'}"

        if cache_key in _RETAIL_PRICE_CACHE:
            info = _RETAIL_PRICE_CACHE[cache_key]
        else:
            try:
                filter_expr = (
                    f"serviceName eq 'Virtual Machines' "
                    f"and armRegionName eq '{azure_region}' "
                    f"and startswith(armSkuName, '{prefix}')"
                )
                query_str = urllib.parse.urlencode({"currencyCode": "USD", "$filter": filter_expr})
                url = f"{AZURE_RETAIL_API_URL}?{query_str}"
                items = _retail_api_fetch_all(url, timeout=timeout)

                consumption = [
                    item for item in items
                    if str(item.get("type") or "").lower() == "consumption"
                    and _is_base_vm_line(item)
                    and _os_matches_item(item, os_name)
                ]

                sku_prices: dict[str, float] = {}
                for item in consumption:
                    arm_sku = str(item.get("armSkuName") or "").strip()
                    price = parse_optional_float(item.get("retailPrice"))
                    if arm_sku and price is not None:
                        if arm_sku not in sku_prices or price < sku_prices[arm_sku]:
                            sku_prices[arm_sku] = price

                info = _select_best_sku_from_api(sku_prices)
            except Exception:  # noqa: BLE001
                info = {"resolved_sku": None, "paygo_hourly_usd": None, "generation": None, "selection_mode": "api_error"}

            _RETAIL_PRICE_CACHE[cache_key] = info

        resolved_sku = info.get("resolved_sku")
        price = info.get("paygo_hourly_usd")

        for orig_sku in original_skus:
            if resolved_sku:
                resolved_map[orig_sku] = resolved_sku
                if price is not None:
                    real_prices[resolved_sku] = price
            else:
                resolved_map[orig_sku] = orig_sku

    # Build resolved candidates list, preserving order and deduping
    seen: set[str] = set()
    resolved_candidates: list[str] = []
    for sku in candidates:
        resolved = resolved_map.get(sku, sku)
        if resolved not in seen:
            seen.add(resolved)
            resolved_candidates.append(resolved)

    return resolved_candidates, real_prices


def rank_candidates(
    *,
    candidates: list[str],
    catalog: dict[str, dict[str, Any]],
    policy: str,
    required_vcpu: int,
    required_memory_gb: float,
    required_iops: float | None,
    required_network_mbps: float | None,
    required_disk_throughput_mbps: float | None,
    prefer_ls_for_app: bool = False,
    real_prices: dict[str, float] | None = None,
) -> list[dict[str, Any]]:
    weights = RANKING_WEIGHTS.get(policy, RANKING_WEIGHTS["strict"])
    ranked: list[dict[str, Any]] = []

    for sku in candidates:
        catalog_entry = catalog.get(sku)
        shape = parse_sku_shape(sku)

        vcpu_actual = int(catalog_entry.get("vcpu") or shape["vcpu"] or 0) if catalog_entry else int(shape["vcpu"] or 0)
        memory_from_catalog = parse_optional_float(catalog_entry.get("memory_gb")) if catalog_entry else None
        memory_actual = memory_from_catalog if memory_from_catalog is not None else estimate_memory_by_family(shape["family"], vcpu_actual)

        fit_vcpu = normalized_gap_score(vcpu_actual, float(required_vcpu))
        fit_mem = normalized_gap_score(memory_actual, required_memory_gb)
        fit_score = (fit_vcpu + fit_mem) / 2.0

        iops_actual = parse_optional_float(catalog_entry.get("max_iops")) if catalog_entry else None
        net_actual = parse_optional_float(catalog_entry.get("network_mbps")) if catalog_entry else None
        disk_tp_actual = parse_optional_float(catalog_entry.get("disk_throughput_mbps")) if catalog_entry else None

        perf_components: list[float] = []
        for required_value, actual_value in [
            (required_iops, iops_actual),
            (required_network_mbps, net_actual),
            (required_disk_throughput_mbps, disk_tp_actual),
        ]:
            if required_value is None:
                continue
            perf_components.append(normalized_gap_score(float(actual_value or 0.0), required_value))
        perf_score = sum(perf_components) / len(perf_components) if perf_components else 0.5

        if real_prices and sku in real_prices:
            # Real price: lower price -> higher score via 1/(1+price)
            cost_score = 1.0 / (1.0 + real_prices[sku])
        else:
            cost_score = estimate_cost_score(shape["family"], shape["suffix"])
        total = fit_score * weights["fit"] + perf_score * weights["perf"] + cost_score * weights["cost"]

        # In APP + large-disk scenarios, prefer D-ls candidates to surface them earlier.
        if prefer_ls_for_app:
            if shape["family"].upper() == "D" and shape["suffix"].lower() == "ls":
                total += 0.08
            elif shape["family"].upper() == "D" and shape["suffix"].lower() in {"as", "a", "s", "ds", "d", ""}:
                total += 0.02
            elif shape["family"].upper() == "F":
                total -= 0.03

        ranked.append(
            {
                "sku": sku,
                "score": round(total, 5),
                "fit_score": round(fit_score, 5),
                "perf_score": round(perf_score, 5),
                "cost_score": round(cost_score, 5),
            }
        )

    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked


def normalize_workload(workload: str | None) -> str:
    return str(workload or "").strip().lower()


def normalize_os_name(value: Any) -> str | None:
    token = str(value or "").strip().lower()
    if token == "":
        return None
    if "windows" in token:
        return "windows"
    if any(keyword in token for keyword in ["linux", "suse", "rhel", "ubuntu", "centos", "oracle linux"]):
        return "linux"
    return token


def parse_optional_bool(value: Any) -> bool | None:
    token = str(value or "").strip().lower()
    if token in {"", "none", "null", "nan", "n/a", "na", "tbd", "pending"}:
        return None
    if token in {"1", "true", "yes", "y", "on"}:
        return True
    if token in {"0", "false", "no", "n", "off"}:
        return False
    return None


def infer_workload_profile(
    *,
    workload: str | None,
    system: str | None,
    env: str | None,
    workload_type: str | None,
    sap_workload: bool | None,
    memory_gb: float,
    app_db_policy: str,
) -> dict[str, Any]:
    parts = [normalize_text(system), normalize_text(env), normalize_text(workload_type), normalize_text(workload)]
    merged = " | ".join([part for part in parts if part])

    env_norm = normalize_env(normalize_text(env))
    role = detect_role(merged)
    sap_inference = infer_sap_workload(system=system, env=env, workload_type=workload_type, workload=workload)

    sap_detected = bool(sap_workload) if sap_workload is not None else bool(sap_inference.get("is_sap_workload"))
    category = str(sap_inference.get("category") or "general")
    is_non_sap_infra = category == "non_sap_infra"
    is_core_suite = category == "sap_core_suite"

    if is_non_sap_infra:
        mapping_path = "infra_general"
        sap_cert_required = False
        prefer_m_family = False
        preferred_family = "D"
    elif role == "app+db":
        if env_norm == "prd":
            mapping_path = "app_db_prd_hana"
            if app_db_policy == "strict":
                sap_cert_required = bool(sap_detected or memory_gb >= 256)
                prefer_m_family = memory_gb >= 256
                preferred_family = "M" if prefer_m_family else "E"
            elif app_db_policy == "cost-first":
                sap_cert_required = False
                prefer_m_family = False
                preferred_family = "E"
            else:
                sap_cert_required = bool(is_core_suite and sap_detected and memory_gb >= 256)
                prefer_m_family = memory_gb >= 512
                preferred_family = "M" if prefer_m_family else "E"
        else:
            mapping_path = "app_db_nonprd_app"
            sap_cert_required = False
            prefer_m_family = False
            preferred_family = "E" if memory_gb >= 128 else "D"
    elif role == "db":
        mapping_path = "db_hana"
        if app_db_policy == "strict":
            sap_cert_required = bool((is_core_suite and sap_detected) or sap_detected or memory_gb >= 256)
            prefer_m_family = memory_gb >= 256
            preferred_family = "M" if prefer_m_family else "E"
        elif app_db_policy == "cost-first":
            sap_cert_required = False
            prefer_m_family = False
            preferred_family = "E"
        else:
            sap_cert_required = bool(is_core_suite and sap_detected and env_norm == "prd" and memory_gb >= 384)
            prefer_m_family = memory_gb >= 512
            preferred_family = "M" if prefer_m_family else "E"
    elif role == "app" and sap_detected:
        mapping_path = "sap_app"
        sap_cert_required = False
        prefer_m_family = False
        preferred_family = "E" if memory_gb >= 128 else "D"
    else:
        mapping_path = "generic"
        sap_cert_required = False
        prefer_m_family = False
        preferred_family = "E" if memory_gb >= 256 else "D"

    return {
        "env": env_norm,
        "role": role,
        "category": category,
        "sap_detected": bool(sap_detected),
        "sap_cert_required": sap_cert_required,
        "prefer_m_family": prefer_m_family,
        "preferred_family": preferred_family,
        "mapping_path": mapping_path,
        "app_db_policy": app_db_policy,
    }


def round_vcpu_for_sku(vcpu: int) -> int:
    for candidate in SUPPORTED_VCPU_STEPS:
        if candidate >= vcpu:
            return candidate
    return vcpu


def pick_sap_certified_sku(
    *,
    required_vcpu: int,
    required_memory_gb: float,
    prefer_m_family: bool,
    catalog: dict[str, dict[str, Any]],
    azure_region: str | None,
    os_name: str | None,
    intel_only: bool = False,
) -> str | None:
    candidates = []
    for sku, item in catalog.items():
        if not bool(item.get("sap_certified", False)):
            continue
        if intel_only and is_amd_sku(sku):
            continue
        item_vcpu = int(float(item.get("vcpu") or 0))
        item_memory = float(item.get("memory_gb") or 0)
        if item_memory < required_memory_gb or item_vcpu < required_vcpu:
            continue

        # Reuse support_gate_for_candidate for region/OS filtering
        passed, _ = support_gate_for_candidate(
            sku=sku,
            catalog_entry=item,
            azure_region=azure_region,
            os_name=os_name,
            sap_cert_required=True,
            pam_supported=None,
        )
        if passed:
            candidates.append(item)

    if not candidates:
        return None

    def family_rank(sku: str) -> int:
        if sku.startswith("Standard_M"):
            return 0 if prefer_m_family else 1
        if sku.startswith("Standard_E"):
            return 1 if prefer_m_family else 0
        return 2

    ordered = sorted(
        candidates,
        key=lambda item: (family_rank(str(item["sku"])), item["memory_gb"], item["vcpu"]),
    )
    return str(ordered[0]["sku"]) if ordered else None


def family_from_shape(vcpu: int, memory_gb: float, burstable: bool, gpu: bool) -> str:
    if gpu:
        return "N"
    if burstable:
        return "B"
    ratio = memory_gb / max(vcpu, 1)
    if ratio >= 6.0:
        return "E"
    if ratio <= 2.5:
        return "F"
    return "D"


def choose_version(family: str) -> str:
    token = family.upper()
    if token == "B":
        return ""
    if token in {"D", "E"}:
        return "_v5"
    if token == "F":
        return "_v2"
    if token == "M":
        return "_v2"
    if token.startswith("N"):
        return "_v3"
    return "_v5"


def features_from_config(
    family: str,
    cpu_vendor: str,
    cpu_arch: str,
    burstable: bool,
    gpu: bool,
    local_temp_disk: bool,
    network_optimized: bool,
    prefer_amd: bool,
) -> str:
    features: list[str] = []
    family_token = family.upper()

    if (cpu_vendor == "amd" or (prefer_amd and cpu_vendor == "unknown")) and cpu_arch != "arm64" and not burstable and not gpu:
        features.append("a")
    if cpu_arch == "arm64":
        features.append("p")
    if local_temp_disk:
        features.append("d")
    if network_optimized:
        features.append("n")
    if family_token != "B":
        features.append("s")

    ordered = ["a", "p", "d", "n", "s"]
    features = [item for item in ordered if item in features]
    return "".join(features)


def candidate_families(primary: str, prefer_ls_for_app: bool = False) -> list[str]:
    token = primary.upper()
    if token == "D":
        return ["D", "E", "F"]
    if token == "E":
        return ["E", "M", "D"]
    if token == "F":
        if prefer_ls_for_app:
            return ["D", "F", "E"]
        return ["F", "D", "E"]
    if token == "N":
        return ["N", "E", "D"]
    if token == "B":
        return ["B", "D", "F"]
    return [token, "D", "E", "F"]


def fallback_features(primary_features: str, family: str, prefer_ls: bool = False) -> list[str]:
    family_token = family.upper()
    values = [primary_features]

    if family_token == "B":
        candidates = ["", "a"]
    else:
        candidates = ["as", "s", "a", "ds", "d", ""]
        if family_token == "D" and prefer_ls:
            candidates = ["ls", *candidates]

    for candidate in candidates:
        if candidate not in values:
            values.append(candidate)
    return values


def build_candidates(
    primary_family: str,
    vcpu: int,
    features: str,
    fallback_count: int,
    required_memory_gb: float,
    prefer_ls_for_app: bool,
) -> tuple[str, list[str]]:
    primary = f"Standard_{primary_family}{vcpu}{features}{choose_version(primary_family)}"
    candidates: list[str] = [primary]

    for family in candidate_families(primary_family, prefer_ls_for_app=prefer_ls_for_app):
        sizes_to_try = [vcpu]
        family_min_vcpu = min_vcpu_for_family_by_memory(family, required_memory_gb)
        if family_min_vcpu > 0:
            sizes_to_try.append(round_vcpu_for_sku(family_min_vcpu))
        if family in {"D", "E", "F", "M"}:
            sizes_to_try.append(vcpu * 2)

        unique_sizes = sorted({item for item in sizes_to_try if item > 0})

        for candidate_vcpu in unique_sizes:
            for suffix in fallback_features(features, family, prefer_ls=prefer_ls_for_app):
                sku = f"Standard_{family}{candidate_vcpu}{suffix}{choose_version(family)}"
                if sku not in candidates:
                    candidates.append(sku)
                if len(candidates) >= fallback_count + 1:
                    return primary, candidates[1 : fallback_count + 1]

    return primary, candidates[1 : fallback_count + 1]


def confidence_score(primary_family: str, vcpu: int, memory_gb: float, burstable: bool, gpu: bool) -> float:
    ratio = memory_gb / max(vcpu, 1)
    if gpu and primary_family == "N":
        return 0.9
    if burstable and primary_family == "B":
        return 0.86
    if primary_family == "E" and ratio >= 6.0:
        return 0.84
    if primary_family == "F" and ratio <= 2.5:
        return 0.84
    if primary_family == "D" and 2.5 < ratio < 6.0:
        return 0.82
    return 0.72


def min_vcpu_for_family_by_memory(family: str, memory_gb: float) -> int:
    token = family.upper()
    ratio_map = {
        "D": 4.0,
        "E": 8.0,
        "F": 2.0,
        "B": 4.0,
    }
    ratio = ratio_map.get(token)
    if ratio is None:
        return 0
    return int(math.ceil(memory_gb / ratio))


def map_single(
    vcpu: int,
    memory_gb: float,
    workload: str | None,
    system: str | None,
    env: str | None,
    workload_type: str | None,
    disk_gb: float | None,
    sap_workload: bool | None,
    cpu_vendor: str,
    cpu_arch: str,
    burstable: bool,
    gpu: bool,
    local_temp_disk: bool,
    network_optimized: bool,
    prefer_amd: bool,
    fallback_count: int,
    app_db_policy: str,
    azure_region: str | None,
    os_name: str | None,
    required_iops: float | None,
    required_network_mbps: float | None,
    required_disk_throughput_mbps: float | None,
    pam_supported: bool | None,
    sku_catalog: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if vcpu <= 0 or memory_gb <= 0:
        return {
            "status": "invalid_input",
            "error": "vcpu and memory_gb must be positive",
        }

    profile = infer_workload_profile(
        workload=workload,
        system=system,
        env=env,
        workload_type=workload_type,
        sap_workload=sap_workload,
        memory_gb=memory_gb,
        app_db_policy=app_db_policy,
    )
    sap_mode = bool(profile["sap_detected"])
    sap_db_related = bool(sap_mode and profile["role"] in {"db", "app+db"})
    sap_cert_required = bool(profile["sap_cert_required"])
    effective_vcpu = int(vcpu)
    effective_family_burstable = burstable
    effective_family_gpu = gpu
    effective_cpu_vendor = cpu_vendor
    effective_prefer_amd = prefer_amd
    mapping_notes: list[str] = []

    if sap_db_related:
        # SAP DB workloads must remain on Intel; do not emit AMD suffix even when prefer_amd is enabled.
        effective_cpu_vendor = "intel"
        effective_prefer_amd = False
        mapping_notes.append("sap_db_force_intel_cpu")

    if sap_cert_required:
        effective_family_burstable = False
        effective_family_gpu = False
        minimum_vcpu_by_memory = int(math.ceil(memory_gb / SAP_MEMORY_PER_VCPU_GB))
        effective_vcpu = round_vcpu_for_sku(max(vcpu, minimum_vcpu_by_memory))
        if effective_vcpu != vcpu:
            mapping_notes.append("sap_memory_priority_vcpu_upsize")

    preferred_family = str(profile["preferred_family"])
    if sap_cert_required:
        family = "M" if profile["prefer_m_family"] else "E"
    elif profile["mapping_path"] == "sap_app":
        memory_ratio = memory_gb / max(vcpu, 1)
        family = "E" if (memory_ratio >= 6.0 or memory_gb >= 128) else "D"
    elif preferred_family in {"D", "E", "M"} and (sap_mode or profile["mapping_path"].startswith("app_db")):
        family = preferred_family
    else:
        family = family_from_shape(vcpu, memory_gb, effective_family_burstable, effective_family_gpu)

    prefer_ls_for_app = bool(profile["role"] == "app" and (disk_gb or 0.0) >= APP_LS_DISK_GB_THRESHOLD)
    if prefer_ls_for_app:
        mapping_notes.append("app_large_disk_prefer_ls_suffix")

    min_vcpu_by_family_memory = min_vcpu_for_family_by_memory(family, memory_gb)
    if min_vcpu_by_family_memory > 0 and effective_vcpu < min_vcpu_by_family_memory:
        effective_vcpu = round_vcpu_for_sku(min_vcpu_by_family_memory)
        mapping_notes.append("family_memory_capacity_vcpu_upsize")

    features = features_from_config(
        family=family,
        cpu_vendor=effective_cpu_vendor,
        cpu_arch=cpu_arch,
        burstable=effective_family_burstable,
        gpu=effective_family_gpu,
        local_temp_disk=local_temp_disk,
        network_optimized=network_optimized,
        prefer_amd=effective_prefer_amd,
    )
    candidate_pool_size = max(fallback_count, 2)
    primary_sku, fallback_skus = build_candidates(
        family,
        effective_vcpu,
        features,
        candidate_pool_size,
        required_memory_gb=memory_gb,
        prefer_ls_for_app=prefer_ls_for_app,
    )
    confidence = confidence_score(family, effective_vcpu, memory_gb, effective_family_burstable, effective_family_gpu)

    all_candidates = [primary_sku, *fallback_skus]

    # Resolve SKU versions and fetch real prices via Azure Retail Prices API
    real_prices: dict[str, float] = {}
    if azure_region:
        resolved_candidates, real_prices = resolve_and_price_candidates(
            all_candidates, azure_region, os_name,
        )
        if resolved_candidates:
            primary_sku = resolved_candidates[0]
            all_candidates = resolved_candidates

    if sap_db_related:
        intel_candidates = [sku for sku in all_candidates if not is_amd_sku(sku)]
        if intel_candidates:
            all_candidates = intel_candidates
            if primary_sku not in all_candidates:
                primary_sku = all_candidates[0]
            mapping_notes.append("sap_db_amd_candidates_removed")
        else:
            mapping_notes.append("sap_db_intel_candidate_missing_keep_original")

    gate_kept: list[str] = []
    gate_rejected: list[dict[str, Any]] = []
    for sku in all_candidates:
        passed, reasons = support_gate_for_candidate(
            sku=sku,
            catalog_entry=sku_catalog.get(sku),
            azure_region=azure_region,
            os_name=os_name,
            sap_cert_required=sap_cert_required,
            pam_supported=pam_supported,
        )
        if passed:
            gate_kept.append(sku)
        else:
            gate_rejected.append({"sku": sku, "reasons": reasons})

    review_flag = False
    if not gate_kept:
        gate_kept = all_candidates
        mapping_notes.append("support_gate_all_rejected_fallback_to_original_candidates")
        review_flag = True

    ranked = rank_candidates(
        candidates=gate_kept,
        catalog=sku_catalog,
        policy=app_db_policy,
        required_vcpu=effective_vcpu,
        required_memory_gb=memory_gb,
        required_iops=required_iops,
        required_network_mbps=required_network_mbps,
        required_disk_throughput_mbps=required_disk_throughput_mbps,
        prefer_ls_for_app=prefer_ls_for_app,
        real_prices=real_prices if real_prices else None,
    )
    ranked_skus = [item["sku"] for item in ranked]

    sap_sku = (
        pick_sap_certified_sku(
            required_vcpu=effective_vcpu,
            required_memory_gb=memory_gb,
            prefer_m_family=bool(profile["prefer_m_family"]),
            catalog=sku_catalog,
            azure_region=azure_region,
            os_name=os_name,
            intel_only=sap_db_related,
        )
        if sap_cert_required
        else None
    )
    if sap_cert_required and sap_sku and app_db_policy == "strict":
        primary_sku = sap_sku
    elif ranked_skus:
        primary_sku = ranked_skus[0]

    fallback_skus = [sku for sku in ranked_skus if sku != primary_sku][:1]
    fallback_sku = fallback_skus[0] if fallback_skus else ""

    assumptions = [
        "version_policy_applied",
        "premium_storage_suffix_default_except_b_family",
        "fallback_suffix_priority_applied",
        "fallback_size_escalation_applied",
    ]
    if (
        effective_cpu_vendor == "unknown"
        and effective_prefer_amd
        and cpu_arch != "arm64"
        and not burstable
        and not gpu
    ):
        assumptions.append("cpu_vendor_unknown_prefer_amd_applied")
    if sap_mode:
        assumptions.append("sap_workload_memory_priority_applied")
    if sap_cert_required:
        assumptions.append("sap_certified_vm_required")
    assumptions.append(f"app_db_policy:{app_db_policy}")
    if required_iops is None and required_network_mbps is None and required_disk_throughput_mbps is None:
        assumptions.append("perf_signals_not_provided_ranking_on_shape_and_cost")
    else:
        assumptions.append("perf_signals_applied_in_ranking")
    assumptions.append(f"workload_mapping_path:{profile['mapping_path']}")
    if real_prices:
        assumptions.append("real_retail_prices_applied_in_ranking")
    else:
        assumptions.append("estimated_cost_used_no_retail_api")
    assumptions.extend(mapping_notes)

    return {
        "status": "ok",
        "input": {
            "vcpu": vcpu,
            "memory_gb": memory_gb,
            "workload": workload,
            "system": system,
            "env": env,
            "workload_type": workload_type,
            "disk_gb": disk_gb,
            "sap_workload": sap_workload,
            "cpu_vendor": cpu_vendor,
            "cpu_arch": cpu_arch,
            "burstable": burstable,
            "gpu": gpu,
            "local_temp_disk": local_temp_disk,
            "network_optimized": network_optimized,
            "azure_region": azure_region,
            "os_name": os_name,
            "required_iops": required_iops,
            "required_network_mbps": required_network_mbps,
            "required_disk_throughput_mbps": required_disk_throughput_mbps,
            "pam_supported": pam_supported,
            "app_db_policy": app_db_policy,
        },
        "effective_vcpu": effective_vcpu,
        "sap_mode": sap_mode,
        "sap_cert_required": sap_cert_required,
        "workload_role": profile["role"],
        "workload_category": profile["category"],
        "workload_env": profile["env"],
        "mapping_path": profile["mapping_path"],
        "primary_sku": primary_sku,
        "fallback_sku": fallback_sku,
        "fallback_skus": fallback_skus,
        "sap_sku": sap_sku,
        "support_gate_kept": gate_kept,
        "support_gate_rejected": gate_rejected,
        "ranking": ranked,
        "mapping_confidence": round(confidence, 2),
        "matched_by": "shape_and_feature_policy",
        "review_flag": review_flag,
        "assumptions": assumptions,
    }


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    token = str(value).strip().lower()
    return token in {"1", "true", "yes", "y", "on"}


def normalize_policy(value: str | None, default_policy: str) -> str:
    token = str(value or "").strip().lower()
    if token in APP_DB_POLICIES:
        return token
    return default_policy


def first_non_empty(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


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
    parser = argparse.ArgumentParser(description="Map VM config to Azure VM instance")

    parser.add_argument("--vcpu", type=int, help="vCPU count for single mode")
    parser.add_argument("--memory-gb", type=float, help="memory in GB for single mode")
    parser.add_argument("--cpu-vendor", choices=["amd", "intel", "arm", "unknown"], default="unknown")
    parser.add_argument("--cpu-arch", choices=["x86_64", "arm64"], default="x86_64")
    parser.add_argument("--burstable", action="store_true")
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--workload", help="workload tag, e.g. SAP")
    parser.add_argument("--system", help="system name, e.g. S4/Fiori/Zabbix")
    parser.add_argument("--env", help="environment, e.g. DEV/QAS/PRD")
    parser.add_argument("--workload-type", help="workload role, e.g. APP/DB/APP+DB")
    parser.add_argument("--disk-gb", type=float, help="disk size in GB for APP large disk heuristics")
    parser.add_argument("--sap-workload", help="optional explicit SAP workload boolean")
    parser.add_argument("--local-temp-disk", action="store_true")
    parser.add_argument("--network-optimized", action="store_true")
    parser.add_argument("--prefer-amd", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fallback-count", type=int, default=1)
    parser.add_argument("--app-db-policy", choices=["strict", "balanced", "cost-first"], default="balanced")
    parser.add_argument("--catalog-file", help="external SKU catalog json")
    parser.add_argument("--azure-region", help="azure region for single mode support gate")
    parser.add_argument("--os-name", help="os name for single mode support gate")
    parser.add_argument("--required-iops", type=float, help="optional required IOPS for ranking")
    parser.add_argument("--required-network-mbps", type=float, help="optional required network throughput for ranking")
    parser.add_argument("--required-disk-throughput-mbps", type=float, help="optional required disk throughput for ranking")
    parser.add_argument("--pam-supported", help="optional explicit PAM support boolean for single mode")

    parser.add_argument("--input-file", help="batch mode CSV input")
    parser.add_argument("--output", default="output/azure_instance_mapping.csv", help="batch output CSV")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    catalog_file = resolve_catalog_path(args.catalog_file)
    sku_catalog = load_sku_catalog(catalog_file)
    env_policy = normalize_policy(os.getenv("VM_APP_DB_POLICY"), args.app_db_policy)

    if args.input_file:
        input_file = Path(args.input_file)
        if not input_file.is_absolute():
            input_file = Path.cwd() / input_file
        if not input_file.exists():
            raise FileNotFoundError(f"Input file not found: {input_file.as_posix()}")

        rows = load_csv(input_file)
        if not rows:
            print(json.dumps({"status": "ok", "rows": 0, "message": "empty input"}, ensure_ascii=False))
            return

        required_any = {
            "vcpu": ["vcpu", "parsed_vcpu"],
            "memory_gb": ["memory_gb", "parsed_memory_gb"],
        }
        missing = [name for name, candidates in required_any.items() if all(col not in rows[0] for col in candidates)]
        if missing:
            raise ValueError(
                "Batch input missing required columns. "
                f"Need at least one of each group: {required_any}; missing groups={missing}"
            )

        output_rows: list[dict[str, Any]] = []
        for row in rows:
            vcpu_value = first_non_empty(row, ["vcpu", "parsed_vcpu"], 0)
            memory_value = first_non_empty(row, ["memory_gb", "parsed_memory_gb"], 0)
            disk_value = first_non_empty(row, ["disk_gb", "disk", "storage"], None)
            app_db_policy = normalize_policy(first_non_empty(row, ["app_db_policy"], None), env_policy)
            azure_region = str(
                first_non_empty(row, ["mapped_azure_region", "azure_region", "region_azure"], "")
            ).strip().lower() or None
            os_name = normalize_os_name(first_non_empty(row, ["os", "os_name"], ""))
            required_iops = parse_optional_float(first_non_empty(row, ["required_iops", "iops"], None))
            required_network_mbps = parse_optional_float(
                first_non_empty(row, ["required_network_mbps", "network_mbps", "network_throughput_mbps"], None)
            )
            required_disk_throughput_mbps = parse_optional_float(
                first_non_empty(row, ["required_disk_throughput_mbps", "disk_throughput_mbps"], None)
            )
            pam_supported = parse_optional_bool(first_non_empty(row, ["pam_supported"], None))

            cpu_vendor = str(first_non_empty(row, ["cpu_vendor", "parsed_cpu_vendor"], "unknown")).strip().lower()
            if cpu_vendor in {"", "none", "null", "nan", "unspecified_x86_vendor"}:
                cpu_vendor = "unknown"

            result = map_single(
                vcpu=int(float(vcpu_value or 0)),
                memory_gb=float(memory_value or 0),
                workload=str(first_non_empty(row, ["workload", "scenario", "usage"], "")).strip() or None,
                system=str(first_non_empty(row, ["system", "application", "landscape_system"], "")).strip() or None,
                env=str(first_non_empty(row, ["env", "environment"], "")).strip() or None,
                workload_type=str(first_non_empty(row, ["workload_type", "role", "tier"], "")).strip() or None,
                disk_gb=parse_optional_float(disk_value),
                sap_workload=parse_optional_bool(first_non_empty(row, ["SAP_workload", "sap_workload"], None)),
                cpu_vendor=cpu_vendor,
                cpu_arch=str(first_non_empty(row, ["cpu_arch", "parsed_cpu_arch"], "x86_64")).strip().lower(),
                burstable=parse_bool(str(first_non_empty(row, ["burstable", "is_burstable"], ""))),
                gpu=parse_bool(str(first_non_empty(row, ["gpu", "is_gpu_accelerated"], ""))),
                local_temp_disk=parse_bool(str(first_non_empty(row, ["local_temp_disk", "has_local_temp_disk"], ""))),
                network_optimized=parse_bool(
                    str(first_non_empty(row, ["network_optimized", "is_network_optimized"], ""))
                ),
                prefer_amd=parse_bool(str(row.get("prefer_amd") or "true"), default=True),
                fallback_count=int(float(row.get("fallback_count") or args.fallback_count)),
                app_db_policy=app_db_policy,
                azure_region=azure_region,
                os_name=os_name,
                required_iops=required_iops,
                required_network_mbps=required_network_mbps,
                required_disk_throughput_mbps=required_disk_throughput_mbps,
                pam_supported=pam_supported,
                sku_catalog=sku_catalog,
            )
            merged = dict(row)
            merged.update(
                {
                    "status": result.get("status"),
                    "effective_vcpu": result.get("effective_vcpu"),
                    "sap_mode": result.get("sap_mode"),
                    "sap_cert_required": result.get("sap_cert_required"),
                    "workload_role": result.get("workload_role"),
                    "workload_category": result.get("workload_category"),
                    "workload_env": result.get("workload_env"),
                    "mapping_path": result.get("mapping_path"),
                    "primary_sku": result.get("primary_sku"),
                    "azure_sku": result.get("primary_sku"),
                    "fallback_sku": result.get("fallback_sku"),
                    "fallback_skus": "|".join(result.get("fallback_skus", [])),
                    "sap_sku": result.get("sap_sku"),
                    "app_db_policy": app_db_policy,
                    "mapping_confidence": result.get("mapping_confidence"),
                    "matched_by": result.get("matched_by"),
                    "review_flag": result.get("review_flag"),
                    "assumptions": "|".join(result.get("assumptions", [])),
                    "support_gate_kept": "|".join(result.get("support_gate_kept", [])),
                    "support_gate_rejected": json.dumps(result.get("support_gate_rejected", []), ensure_ascii=False),
                    "ranking": json.dumps(result.get("ranking", []), ensure_ascii=False),
                    "error": result.get("error"),
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
                    "catalog_file": catalog_file.as_posix(),
                    "default_app_db_policy": env_policy,
                },
                ensure_ascii=False,
            )
        )
        return

    if args.vcpu is None or args.memory_gb is None:
        raise ValueError("Single mode requires --vcpu and --memory-gb")

    result = map_single(
        vcpu=args.vcpu,
        memory_gb=args.memory_gb,
        workload=args.workload,
        system=args.system,
        env=args.env,
        workload_type=args.workload_type,
        disk_gb=args.disk_gb,
        sap_workload=parse_optional_bool(args.sap_workload),
        cpu_vendor=args.cpu_vendor,
        cpu_arch=args.cpu_arch,
        burstable=args.burstable,
        gpu=args.gpu,
        local_temp_disk=args.local_temp_disk,
        network_optimized=args.network_optimized,
        prefer_amd=args.prefer_amd,
        fallback_count=args.fallback_count,
        app_db_policy=env_policy,
        azure_region=(str(args.azure_region).strip().lower() if args.azure_region else None),
        os_name=normalize_os_name(args.os_name),
        required_iops=args.required_iops,
        required_network_mbps=args.required_network_mbps,
        required_disk_throughput_mbps=args.required_disk_throughput_mbps,
        pam_supported=parse_optional_bool(args.pam_supported),
        sku_catalog=sku_catalog,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
