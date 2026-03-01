from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cloud_quote_agent.config import load_config
from cloud_quote_agent.ingestion import parse_excel, to_nrm_records
from cloud_quote_agent.regions import RegionResolver


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract AWS VM inputs from Excel")
    parser.add_argument("--input-excel", required=True, help="input Excel (.xlsx)")
    parser.add_argument("--output", default="output/aws_vm_inputs.csv", help="output CSV path")
    parser.add_argument("--config", default="config/defaults.yaml", help="config path")
    parser.add_argument("--regions", default="data/get_regions.xlsx", help="regions map path")
    parser.add_argument("--include-review", action="store_true", help="include status != ok rows")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    input_excel = resolve_path(args.input_excel)
    output_csv = resolve_path(args.output)
    config_path = resolve_path(args.config)
    regions_path = resolve_path(args.regions)

    if not input_excel.exists():
        raise FileNotFoundError(f"Input Excel not found: {input_excel.as_posix()}")
    if not config_path.exists():
        raise FileNotFoundError(f"Config not found: {config_path.as_posix()}")
    if not regions_path.exists():
        raise FileNotFoundError(f"Regions file not found: {regions_path.as_posix()}")

    config = load_config(config_path)
    resolver = RegionResolver.from_excel(regions_path)

    df, input_name = parse_excel(str(input_excel))
    records = to_nrm_records(
        df=df,
        file_name=input_name,
        default_region=config.default_region,
        region_resolver=resolver,
    )

    extracted: list[dict[str, Any]] = []
    for record in records:
        if record.resource_type != "vm":
            continue
        if record.provider != "aws":
            continue
        if not record.instance_name:
            continue
        if not args.include_review and record.status != "ok":
            continue

        extracted.append(
            {
                "nrm_id": record.nrm_id,
                "instance_type": record.instance_name,
                "provider": record.provider,
                "resource_type": record.resource_type,
                "vcpu": record.vcpu,
                "memory_gb": record.memory_gb,
                "os": record.os,
                "region_input": record.region_input,
                "region_aws": record.region_aws,
                "region_azure": record.region_azure,
                "workload": record.workload,
                "status": record.status,
                "status_reason": record.status_reason,
            }
        )

    write_csv(output_csv, extracted)

    print(
        json.dumps(
            {
                "status": "ok",
                "input_excel": str(Path(args.input_excel).as_posix()),
                "output_csv": str(Path(args.output).as_posix()),
                "total_rows": len(records),
                "extracted_rows": len(extracted),
                "required_for_next_skill": ["instance_type"],
                "recommended_columns": [
                    "provider",
                    "resource_type",
                    "instance_name",
                    "vcpu",
                    "memory_gb",
                    "os",
                    "region",
                    "workload",
                ],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
