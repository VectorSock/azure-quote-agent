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
    "system": ["system", "sap_system", "系统", "系统名称"],
    "env": ["env", "environment", "环境"],
    "SAP_workload": ["sap_workload", "sap workload", "sap_workload_flag", "是否sap", "sap负载"],
    "workload_type": ["workload_type", "role", "角色", "工作负载类型"],
    "disk": ["disk", "disk_gb", "storage", "磁盘", "磁盘容量"],
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
    if "windows" in lowered:
        return "windows"

    linux_keywords = (
        "linux",
        "unix",
        "ubuntu",
        "debian",
        "centos",
        "suse",
        "sles",
        "opensuse",
        "rhel",
        "red hat",
        "rocky",
        "alma",
        "almalinux",
        "amazon linux",
        "amzn",
        "oracle linux",
        "ol",
        "fedora",
    )
    if any(keyword in lowered for keyword in linux_keywords):
        return "linux"

    return raw


def normalize_sap_workload(value: Any) -> bool | None:
    if value is None:
        return None

    raw = str(value).strip().lower()
    if raw in {"", "nan", "none", "null"}:
        return None
    if raw in {"1", "1.0", "true", "yes", "y", "是"}:
        return True
    if raw in {"0", "0.0", "false", "no", "n", "否"}:
        return False
    return None


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
    "elastic compute cloud": "vm",
    "ecs": "vm",
    "elastic compute service": "vm",
    "aliyun ecs": "vm",
    "alibaba cloud ecs": "vm",
    "云服务器 ecs": "vm",
    "cvm": "vm",
    "tencent cvm": "vm",
    "tencent cloud cvm": "vm",
    "qcloud cvm": "vm",
    "huawei ecs": "vm",
    "huawei cloud ecs": "vm",
    "华为云 ecs": "vm",
    "gce": "vm",
    "google compute engine": "vm",
    "google compute instance": "vm",
    "compute instance": "vm",
    "oci compute": "vm",
    "oci compute instance": "vm",
    "oracle cloud compute": "vm",
    "oracle compute": "vm",
    "compute engine": "vm",
    "virtual server": "vm",
    "vm instance": "vm",
    "virtual machine instance": "vm",
    "virtual machine": "vm",
    "virtual_machine": "vm",
    "compute": "vm",
    "云主机": "vm",
    "云服务器": "vm",
    "弹性云服务器": "vm",
    "虚拟机": "vm",
}


def normalize_resource_type(raw: str) -> str:
    """Map common resource-type synonyms to a canonical value."""
    key = raw.strip().lower()
    if key in RESOURCE_TYPE_ALIASES:
        return RESOURCE_TYPE_ALIASES[key]

    vm_tokens = [
        "ec2",
        "ecs",
        "elastic compute",
        "compute engine",
        "compute instance",
        "gce",
        "cvm",
        "oci compute",
        "oracle compute",
        "virtual machine",
        "vm instance",
        "virtual server",
        "云服务器",
        "云主机",
        "弹性云服务器",
        "虚拟机",
    ]
    if any(token in key for token in vm_tokens):
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
        vcpu_value = to_float_or_none(row.get(detected["vcpu"])) if detected["vcpu"] else None
        memory_value = to_float_or_none(row.get(detected["memory_gb"])) if detected["memory_gb"] else None
        raw_provider = str(row.get(detected["provider"], "") if detected["provider"] else "").strip()
        provider = normalize_text(raw_provider)
        provider_from_input = bool(raw_provider)
        provider = infer_provider(provider, instance_name)

        resource_type = normalize_text(row.get(detected["resource_type"], "") if detected["resource_type"] else "")
        resource_type = infer_resource_type(resource_type, instance_name)

        status = normalize_text(row.get(detected["status"], "") if detected["status"] else "")
        status_reason = str(row.get(detected["status_reason"], "") if detected["status_reason"] else "").strip()
        has_vm_shape = (vcpu_value or 0) > 0 and (memory_value or 0) > 0
        if not status:
            status = "ok" if (instance_name or has_vm_shape) else "review"
            if not status_reason and status == "review":
                status_reason = "missing_instance_name"

        records.append(
            {
                "nrm_id": f"row-{index + 1}",
                "provider": provider,
                "provider_from_input": provider_from_input,
                "resource_type": resource_type,
                "instance_name": instance_name,
                "quantity": to_float_or_none(row.get(detected["quantity"])) if detected["quantity"] else None,
                "vcpu": vcpu_value,
                "memory_gb": memory_value,
                "os": normalize_os_name(row.get(detected["os"], "") if detected["os"] else ""),
                "region_input": str(row.get(detected["region_input"], "") if detected["region_input"] else "").strip() or None,
                "region_aws": None,
                "region_azure": None,
                "workload": str(row.get(detected["workload"], "") if detected["workload"] else "").strip() or None,
                "system": str(row.get(detected["system"], "") if detected["system"] else "").strip() or None,
                "env": str(row.get(detected["env"], "") if detected["env"] else "").strip() or None,
                "SAP_workload": normalize_sap_workload(row.get(detected["SAP_workload"])) if detected["SAP_workload"] else None,
                "workload_type": str(row.get(detected["workload_type"], "") if detected["workload_type"] else "").strip() or None,
                "disk": str(row.get(detected["disk"], "") if detected["disk"] else "").strip() or None,
                "status": status,
                "status_reason": None if (status_reason == "missing_instance_name" and has_vm_shape) else (status_reason or None),
            }
        )
    return records


def as_base_row(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "nrm_id": record.get("nrm_id"),
        "provider": record.get("provider"),
        "provider_from_input": record.get("provider_from_input"),
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
        "system": record.get("system"),
        "env": record.get("env"),
        "SAP_workload": record.get("SAP_workload"),
        "workload_type": record.get("workload_type"),
        "disk": record.get("disk"),
        "status": record.get("status"),
        "status_reason": record.get("status_reason"),
    }


def extract_aws_vm(record: dict[str, Any]) -> dict[str, Any] | None:
    base = as_base_row(record)
    provider = normalize_text(base.get("provider"))
    resource_type = normalize_text(base.get("resource_type"))
    instance_name = str(base.get("instance_name") or "").strip()

    if resource_type != "vm":
        return None
    if provider not in {"", "aws"}:
        return None
    has_shape = (to_float_or_none(base.get("vcpu")) or 0) > 0 and (to_float_or_none(base.get("memory_gb")) or 0) > 0
    if not instance_name and not has_shape:
        return None

    row = base
    row["instance_type"] = normalize_instance_type(instance_name) if instance_name else ""
    return row


def extract_all_resources(record: dict[str, Any]) -> dict[str, Any] | None:
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
            "system",
            "env",
            "SAP_workload",
            "workload_type",
            "disk",
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

    records = build_records_by_fallback(input_excel)
    extraction_engine = "standalone_engine"

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
