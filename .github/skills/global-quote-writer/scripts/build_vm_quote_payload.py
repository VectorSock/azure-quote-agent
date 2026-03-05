from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any


def safe_float(value: Any) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def safe_bool(value: Any) -> bool:
    token = str(value or "").strip().lower()
    return token in {"1", "true", "yes", "y", "on"}


def first_non_empty(row: dict[str, Any], keys: list[str], default: Any = None) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default


def load_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fp:
        return list(csv.DictReader(fp))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build quote payload JSON from VM pipeline pricing CSV")
    parser.add_argument("--input-csv", required=True, help="Input CSV (typically pricing batch output)")
    parser.add_argument("--output-json", required=True, help="Output quote payload JSON path")
    parser.add_argument("--monthly-hours", type=float, default=730, help="Monthly hours, default 730")
    parser.add_argument("--customer-project", default="VM Migration Quote", help="Summary customer/project")
    parser.add_argument("--region", default="", help="Summary region text")
    parser.add_argument("--currency", default="USD (excl. tax)", help="Summary currency")
    parser.add_argument("--competitor-cloud", default="AWS", help="Summary competitor cloud")
    parser.add_argument(
        "--pricing-source-note",
        default="Azure Retail Prices API + AWS Pricing API (GetProducts)",
        help="Summary pricing source note",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_csv = Path(args.input_csv)
    if not input_csv.is_absolute():
        input_csv = Path.cwd() / input_csv
    if not input_csv.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_csv.as_posix()}")

    rows = load_csv(input_csv)

    line_items: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []

    aws_available = False
    azure_available = False
    input_provider_present = False

    for idx, row in enumerate(rows, start=1):
        quantity = safe_float(first_non_empty(row, ["quantity"], 1)) or 1.0
        os_name = str(first_non_empty(row, ["os"], "linux")).strip().lower()
        provider_from_input = safe_bool(first_non_empty(row, ["provider_from_input"], False))
        if provider_from_input:
            input_provider_present = True

        aws_paygo = safe_float(first_non_empty(row, ["AWS_paygo", "aws_paygo_hourly_usd", "unit_price_AWS_paygo"]))
        aws_1y = safe_float(first_non_empty(row, ["AWS_1YRI", "aws_ri_1y_hourly_usd"]))
        aws_3y = safe_float(first_non_empty(row, ["AWS_3YRI", "aws_ri_3y_hourly_usd"]))

        azure_paygo = safe_float(first_non_empty(row, ["Azure_paygo", "azure_paygo_hourly_usd", "unit_price_Azure_paygo"]))
        azure_1y = safe_float(first_non_empty(row, ["Azure_1YRI", "azure_ri_1y_hourly_usd"]))
        azure_3y = safe_float(first_non_empty(row, ["Azure_3YRI", "azure_ri_3y_hourly_usd"]))
        sap_azure_paygo = safe_float(first_non_empty(row, ["Azure_SAP_paygo", "sap_azure_paygo_hourly_usd"]))
        sap_azure_1y = safe_float(first_non_empty(row, ["Azure_SAP_1YRI", "sap_azure_ri_1y_hourly_usd"]))
        sap_azure_3y = safe_float(first_non_empty(row, ["Azure_SAP_3YRI", "sap_azure_ri_3y_hourly_usd"]))

        if any(value is not None for value in [aws_paygo, aws_1y, aws_3y]):
            aws_available = True
        if any(value is not None for value in [azure_paygo, azure_1y, azure_3y]):
            azure_available = True

        item_id = str(first_non_empty(row, ["item_id", "nrm_id"], f"item-{idx}"))
        evidence_id = f"ev-{idx}"

        line_items.append(
            {
                "resource_type": str(first_non_empty(row, ["resource_type", "service"], "vm")),
                "system": str(first_non_empty(row, ["system"], "")),
                "env": str(first_non_empty(row, ["env", "environment"], "")),
                "SAP_workload": str(first_non_empty(row, ["SAP_workload", "sap_workload"], "")),
                "workload_type": str(first_non_empty(row, ["workload_type"], "")),
                "vcpu": safe_float(first_non_empty(row, ["vcpu", "parsed_vcpu"], None)),
                "memory_gb": safe_float(first_non_empty(row, ["memory_gb", "parsed_memory_gb"], None)),
                "disk": str(first_non_empty(row, ["disk"], "")),
                "quantity": int(quantity) if float(quantity).is_integer() else quantity,
                "os": os_name,
                "region": str(first_non_empty(row, ["region", "region_input"], "")),
                "item_id": item_id,
                "provider": str(first_non_empty(row, ["provider"], "")),
                "sku/os": os_name,
                "region_azure": str(first_non_empty(row, ["mapped_azure_region", "azure_region", "region_azure"], "")),
                "primary_sku": str(first_non_empty(row, ["primary_sku", "azure_sku"], "")),
                "fallback_sku": str(first_non_empty(row, ["fallback_sku", "fallback_skus"], "")),
                "sap_sku": str(first_non_empty(row, ["sap_sku"], "")),
                "billing_unit": "hour",
                "AWS_paygo": aws_paygo,
                "AWS_1YRI": aws_1y,
                "AWS_3YRI": aws_3y,
                "Azure_paygo": azure_paygo,
                "Azure_1YRI": azure_1y,
                "Azure_3YRI": azure_3y,
                "Azure_SAP_paygo": sap_azure_paygo,
                "Azure_SAP_1YRI": sap_azure_1y,
                "Azure_SAP_3YRI": sap_azure_3y,
                "review_flag": str(first_non_empty(row, ["review_flag"], "")),
                "review_reason": str(first_non_empty(row, ["review_reason", "pricing_error"], "")),
                "evidence_id": evidence_id,
            }
        )

        aws_status = str(first_non_empty(row, ["aws_status"], "")).strip() or "unknown"
        azure_status = str(first_non_empty(row, ["azure_status"], "")).strip() or "unknown"
        source_type = "retail_api"
        source_url = "https://prices.azure.com/api/retail/prices"
        if aws_status == "ok" and azure_status != "ok":
            source_url = "aws-pricing-api:get_products"
        if aws_status == "ok" and azure_status == "ok":
            source_url = "azure-retail-api + aws-pricing-api:get_products"

        evidence.append(
            {
                "evidence_id": evidence_id,
                "item_id": item_id,
                "source_type": source_type,
                "source_url": source_url,
                "fetched_at": datetime.now().isoformat(),
                "mapping_version": "v1",
                "policy_version": "v1",
                "kb_version": "v1",
                "price_date": datetime.now().strftime("%Y-%m-%d"),
                "source_ref": str(first_non_empty(row, ["pricing_result_json"], "")),
                "status": "ok" if (aws_status == "ok" or azure_status == "ok") else "review",
            }
        )

    assumptions = [
        {
            "key": "hourly_price_only",
            "value": True,
            "source": "pricing-policy",
            "notes": "报价仅输出小时单价，不再输出 line total",
        },
        {
            "key": "ri_hourly_normalization",
            "value": "annual_total / (12 * 730)",
            "source": "pricing-policy",
            "notes": "若 RI 为年总价，先折算成小时单价",
        },
        {
            "key": "aws_pricing_available",
            "value": aws_available,
            "source": "vm-pricing-retail-api",
            "notes": "false usually means missing AWS credentials or no matched SKU",
        },
        {
            "key": "azure_pricing_available",
            "value": azure_available,
            "source": "vm-pricing-retail-api",
            "notes": "Azure Retail API public pricing availability",
        },
    ]

    summary = {
        "customer_project": args.customer_project,
        "region": args.region,
        "currency": args.currency,
        "competitor_cloud": args.competitor_cloud,
        "input_provider_present": input_provider_present,
        "pricing_source_date": datetime.now().strftime("%Y-%m-%d"),
        "pricing_source_note": args.pricing_source_note,
    }

    payload = {
        "summary": summary,
        "line_items": line_items,
        "assumptions": assumptions,
        "evidence": evidence,
    }

    output_json = Path(args.output_json)
    if not output_json.is_absolute():
        output_json = Path.cwd() / output_json
    output_json.parent.mkdir(parents=True, exist_ok=True)

    with output_json.open("w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)

    print(
        json.dumps(
            {
                "status": "ok",
                "rows": len(line_items),
                "input_csv": input_csv.as_posix(),
                "output_json": output_json.as_posix(),
                "aws_pricing_available": aws_available,
                "azure_pricing_available": azure_available,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
