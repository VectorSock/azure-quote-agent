from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]

import pandas as pd

AWS_INSTANCE_RE = re.compile(r"^[a-z][a-z0-9]*\d+[a-z0-9]*\.[a-z0-9]+$", re.IGNORECASE)

COLUMN_ALIASES: dict[str, list[str]] = {
    "provider": ["provider", "cloud", "cloud_provider", "vendor", "平台"],
    "resource_type": ["resource_type", "resource", "service_type", "product_family", "type", "资源类型"],
    "instance_name": ["instance_name", "instance_type", "vm_size", "sku", "规格", "实例类型", "机型"],
    "quantity": ["quantity", "qty", "count", "数量", "instances"],
    "vcpu": ["vcpu", "cpu", "cores", "vcpus"],
    "memory_gb": ["memory_gb", "memory", "ram_gb", "mem_gb", "内存"],
    "os": ["os", "operating_system", "platform"],
    "region_input": ["region", "location", "region_input", "地域", "区域"],
    "workload": ["workload", "scenario", "usage", "业务"],
    "status": ["status", "record_status"],
    "status_reason": ["status_reason", "reason", "message"],
}


def resolve_path(path_str: str) -> Path:
    path = Path(path_str)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with path.open("w", encoding="utf-8", newline="") as fp:
            fp.write("")
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def normalize_col_name(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = text.replace(" ", "_").replace("-", "_")
    return text


def to_float_or_none(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def normalize_os_name(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    lowered = raw.lower()
    if "windows with sql" in lowered:
        return "windows"
    if lowered == "windows with sql server standard":
        return "windows"
    if "windows" in lowered:
        return "windows"
    if "suse" in lowered:
        return "linux"
    if "centos" in lowered:
        return "linux"
    if lowered in {"linux/unix", "linux", "unix"}:
        return "linux"
    return raw


def detect_column(columns: list[str], aliases: list[str]) -> str | None:
    alias_set = {normalize_col_name(item) for item in aliases}
    for col in columns:
        if normalize_col_name(col) in alias_set:
            return col
    return None


def infer_provider(provider: str, instance_name: str) -> str:
    if provider:
        return provider
    if instance_name and AWS_INSTANCE_RE.match(instance_name):
        return "aws"
    return ""


RESOURCE_TYPE_ALIASES: dict[str, str] = {
    "ec2": "vm",
    "amazon ec2": "vm",
    "amazon elastic compute cloud": "vm",
    "ecs": "vm",
    "compute engine": "vm",
    "virtual machine": "vm",
    "virtual_machine": "vm",
    "compute": "vm",
    "虚拟机": "vm",
}


def normalize_resource_type(raw: str) -> str:
    """Map common resource-type synonyms to a canonical value."""
    key = raw.strip().lower()
    if key in RESOURCE_TYPE_ALIASES:
        return RESOURCE_TYPE_ALIASES[key]

    if any(token in key for token in ["ec2", "elastic compute", "compute engine"]):
        return "vm"

    return key


def normalize_instance_type(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    if AWS_INSTANCE_RE.match(text):
        return text

    candidate = text.split()[0].strip().rstrip(",;)")
    if AWS_INSTANCE_RE.match(candidate):
        return candidate

    match = re.search(r"([a-z][a-z0-9]*\d+[a-z0-9]*\.[a-z0-9]+)", text, re.IGNORECASE)
    if match:
        return match.group(1)

    return text


def infer_resource_type(resource_type: str, instance_name: str) -> str:
    if resource_type:
        return normalize_resource_type(resource_type)
    if instance_name:
        return "vm"
    return ""


def build_records_by_fallback(input_excel: Path) -> list[dict[str, Any]]:
    df = pd.read_excel(input_excel)
    if df is None:
        return []

    columns = list(df.columns)
    detected = {key: detect_column(columns, aliases) for key, aliases in COLUMN_ALIASES.items()}

    records: list[dict[str, Any]] = []
    for index, row in df.iterrows():
        instance_name = str(row.get(detected["instance_name"], "") if detected["instance_name"] else "").strip()
        provider = normalize_text(row.get(detected["provider"], "") if detected["provider"] else "")
        provider = infer_provider(provider, instance_name)

        resource_type = normalize_text(row.get(detected["resource_type"], "") if detected["resource_type"] else "")
        resource_type = infer_resource_type(resource_type, instance_name)

        status = normalize_text(row.get(detected["status"], "") if detected["status"] else "")
        status_reason = str(row.get(detected["status_reason"], "") if detected["status_reason"] else "").strip()
        if not status:
            status = "ok" if instance_name else "review"
            if not status_reason and status == "review":
                status_reason = "missing_instance_name"

        records.append(
            {
                "nrm_id": f"row-{index + 1}",
                "provider": provider,
                "resource_type": resource_type,
                "instance_name": instance_name,
                "quantity": to_float_or_none(row.get(detected["quantity"])) if detected["quantity"] else None,
                "vcpu": to_float_or_none(row.get(detected["vcpu"])) if detected["vcpu"] else None,
                "memory_gb": to_float_or_none(row.get(detected["memory_gb"])) if detected["memory_gb"] else None,
                "os": normalize_os_name(row.get(detected["os"], "") if detected["os"] else ""),
                "region_input": str(row.get(detected["region_input"], "") if detected["region_input"] else "").strip() or None,
                "region_aws": None,
                "region_azure": None,
                "workload": str(row.get(detected["workload"], "") if detected["workload"] else "").strip() or None,
                "status": status,
                "status_reason": status_reason or None,
            }
        )
    return records


def build_records(input_excel: Path) -> tuple[list[dict[str, Any]], str]:
    return build_records_by_fallback(input_excel), "standalone_engine"


def as_base_row(record: Any) -> dict[str, Any]:
    if isinstance(record, dict):
        return {
            "nrm_id": record.get("nrm_id"),
            "provider": record.get("provider"),
            "resource_type": record.get("resource_type"),
            "instance_name": record.get("instance_name"),
            "quantity": record.get("quantity"),
            "vcpu": record.get("vcpu"),
            "memory_gb": record.get("memory_gb"),
            "os": record.get("os"),
            "region_input": record.get("region_input"),
            "region_aws": record.get("region_aws"),
            "region_azure": record.get("region_azure"),
            "workload": record.get("workload"),
            "status": record.get("status"),
            "status_reason": record.get("status_reason"),
        }

    return {
        "nrm_id": getattr(record, "nrm_id", None),
        "provider": getattr(record, "provider", None),
        "resource_type": getattr(record, "resource_type", None),
        "instance_name": getattr(record, "instance_name", None),
        "quantity": getattr(record, "quantity", None),
        "vcpu": getattr(record, "vcpu", None),
        "memory_gb": getattr(record, "memory_gb", None),
        "os": getattr(record, "os", None),
        "region_input": getattr(record, "region_input", None),
        "region_aws": getattr(record, "region_aws", None),
        "region_azure": getattr(record, "region_azure", None),
        "workload": getattr(record, "workload", None),
        "status": getattr(record, "status", None),
        "status_reason": getattr(record, "status_reason", None),
    }


def extract_aws_vm(record: Any) -> dict[str, Any] | None:
    base = as_base_row(record)
    provider = normalize_text(base.get("provider"))
    resource_type = normalize_text(base.get("resource_type"))
    instance_name = str(base.get("instance_name") or "").strip()

    if resource_type != "vm":
        return None
    if provider != "aws":
        return None
    if not instance_name:
        return None

    row = base
    row["instance_type"] = normalize_instance_type(instance_name)
    return row


def extract_all_resources(record: Any) -> dict[str, Any] | None:
    return as_base_row(record)


EXTRACTOR_REGISTRY: dict[str, dict[str, Any]] = {
    "aws_vm": {
        "extractor": extract_aws_vm,
        "required_for_next_skill": ["instance_type"],
        "recommended_columns": [
            "provider",
            "resource_type",
            "instance_name",
            "quantity",
            "vcpu",
            "memory_gb",
            "os",
            "region_input",
            "workload",
        ],
    },
    "all_resources": {
        "extractor": extract_all_resources,
        "required_for_next_skill": ["resource_type"],
        "recommended_columns": [
            "provider",
            "resource_type",
            "instance_name",
            "quantity",
            "vcpu",
            "memory_gb",
            "os",
            "region_input",
            "region_aws",
            "region_azure",
            "workload",
        ],
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract normalized inputs from raw Excel")
    parser.add_argument("--input-excel", required=True, help="input Excel (.xlsx/.xls)")
    parser.add_argument("--output", default="output/extracted_inputs.csv", help="output CSV path")
    parser.add_argument("--profile", choices=sorted(EXTRACTOR_REGISTRY.keys()), default="aws_vm")
    parser.add_argument("--include-review", action="store_true", help="include status != ok rows")
    parser.add_argument("--provider", help="optional provider filter, e.g. aws/azure/gcp")
    parser.add_argument("--resource-type", help="optional resource_type filter, e.g. vm/storage/db")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_excel = resolve_path(args.input_excel)
    output_csv = resolve_path(args.output)

    if not input_excel.exists():
        raise FileNotFoundError(f"Input Excel not found: {input_excel.as_posix()}")
    profile_spec = EXTRACTOR_REGISTRY[args.profile]
    extractor = profile_spec["extractor"]

    provider_filter = normalize_text(args.provider)
    resource_type_filter = normalize_text(args.resource_type)

    records, extraction_engine = build_records(input_excel)

    output_rows: list[dict[str, Any]] = []
    eligible_rows = 0
    for record in records:
        base = as_base_row(record)

        if provider_filter and normalize_text(base.get("provider")) != provider_filter:
            continue
        if resource_type_filter and normalize_text(base.get("resource_type")) != resource_type_filter:
            continue
        if not args.include_review and normalize_text(base.get("status")) != "ok":
            continue

        eligible_rows += 1
        extracted = extractor(base)
        if extracted is not None:
            output_rows.append(extracted)

    write_csv(output_csv, output_rows)

    print(
        json.dumps(
            {
                "status": "ok",
                "input_excel": str(Path(args.input_excel).as_posix()),
                "output_csv": str(Path(args.output).as_posix()),
                "profile": args.profile,
                "engine": extraction_engine,
                "filters": {
                    "provider": args.provider,
                    "resource_type": args.resource_type,
                    "include_review": args.include_review,
                },
                "total_rows": len(records),
                "eligible_rows": eligible_rows,
                "extracted_rows": len(output_rows),
                "required_for_next_skill": profile_spec["required_for_next_skill"],
                "recommended_columns": profile_spec["recommended_columns"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
