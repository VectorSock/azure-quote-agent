from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.pdf_extraction_core import build_records_from_lines
from scripts.pdf_extraction_core import filter_rows
from scripts.pdf_extraction_core import load_di_settings
from scripts.pdf_extraction_core import parse_pdf_with_document_intelligence
from scripts.pdf_extraction_core import write_csv
from scripts.region_mapping_core import RegionResolver
from scripts.region_mapping_core import resolve_mapping_file
from scripts.region_mapping_core import resolve_project_root


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def _run_python_script(script_path: Path, args: list[str]) -> dict[str, Any]:
    command = [sys.executable, str(script_path), *args]
    proc = subprocess.run(command, capture_output=True, text=True, check=False)
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()

    if proc.returncode != 0:
        raise RuntimeError(
            json.dumps(
                {
                    "status": "error",
                    "script": script_path.as_posix(),
                    "command": command,
                    "exit_code": proc.returncode,
                    "stdout": stdout,
                    "stderr": stderr,
                },
                ensure_ascii=False,
            )
        )

    parsed: dict[str, Any] = {
        "status": "ok",
        "script": script_path.as_posix(),
        "stdout": stdout,
    }
    if stdout:
        try:
            parsed["result"] = json.loads(stdout)
            return parsed
        except json.JSONDecodeError:
            pass

        start_obj = stdout.find("{")
        end_obj = stdout.rfind("}")
        if 0 <= start_obj < end_obj:
            maybe_obj = stdout[start_obj : end_obj + 1]
            try:
                parsed["result"] = json.loads(maybe_obj)
                return parsed
            except json.JSONDecodeError:
                pass

        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if not line:
                continue
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                parsed["result"] = json.loads(line)
                break
            except json.JSONDecodeError:
                continue

    return parsed


def _ensure_instance_type_column(input_csv: Path) -> None:
    with input_csv.open("r", encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))
        if not rows:
            return

    headers = list(rows[0].keys())
    has_instance_type = "instance_type" in headers
    has_instance_name = "instance_name" in headers

    if has_instance_type:
        return

    if not has_instance_name:
        return

    for row in rows:
        row["instance_type"] = str(row.get("instance_name") or "").strip()

    headers.append("instance_type")
    with input_csv.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)


def _map_regions(input_csv: Path, output_csv: Path, default_azure_region: str, mapping_file: Path | None) -> dict[str, Any]:
    resolver = RegionResolver.from_excel(mapping_file or resolve_mapping_file(None))

    with input_csv.open("r", encoding="utf-8-sig", newline="") as fp:
        rows = list(csv.DictReader(fp))

    if not rows:
        write_csv(output_csv, [])
        return {
            "status": "ok",
            "rows": 0,
            "fallback_count": 0,
            "output_csv": output_csv.as_posix(),
        }

    location_candidates = ["region_input", "region", "location", "city", "site", "region_name"]
    location_col = None
    for candidate in location_candidates:
        if candidate in rows[0]:
            location_col = candidate
            break

    if location_col is None:
        raise ValueError("Cannot find location column in extracted csv for region mapping")

    fallback_count = 0
    output_rows: list[dict[str, Any]] = []
    for row in rows:
        location = row.get(location_col)
        resolution = resolver.resolve(location, default_azure_region)
        if resolution.mapped_by == "fallback":
            fallback_count += 1

        merged = dict(row)
        merged.update(
            {
                "mapped_city": resolution.mapped_city,
                "mapped_aws_region": resolution.mapped_aws_region,
                "mapped_azure_region": resolution.mapped_azure_region,
                "mapped_gcp_region": resolution.mapped_gcp_region,
                "mapped_by": resolution.mapped_by,
                "confidence": resolution.confidence,
                "warning": resolution.warning,
            }
        )
        output_rows.append(merged)

    write_csv(output_csv, output_rows)
    return {
        "status": "ok",
        "rows": len(output_rows),
        "fallback_count": fallback_count,
        "location_column": location_col,
        "output_csv": output_csv.as_posix(),
    }


def _extract_from_pdf(
    input_pdf: Path,
    output_csv: Path,
    profile: str,
    include_review: bool,
    endpoint: str | None,
    key: str | None,
    env_file: Path,
    auth_mode: str,
    model_id: str,
    subscription_id: str | None,
    resource_group: str | None,
    account_name: str | None,
) -> dict[str, Any]:
    resolved_endpoint, resolved_auth_mode, resolved_key = load_di_settings(
        endpoint=endpoint,
        key=key,
        auth_mode=auth_mode,
        env_file=env_file,
        subscription_id=subscription_id,
        resource_group=resource_group,
        account_name=account_name,
    )

    lines, di_meta = parse_pdf_with_document_intelligence(
        input_pdf=input_pdf,
        endpoint=resolved_endpoint,
        key=resolved_key,
        auth_mode=resolved_auth_mode,
        model_id=model_id,
    )
    raw_rows, parse_stats = build_records_from_lines(lines=lines, include_review=include_review)
    output_rows = filter_rows(
        rows=raw_rows,
        profile=profile,
        provider="",
        resource_type="",
        include_review=include_review,
    )
    write_csv(output_csv, output_rows)

    return {
        "status": "ok",
        "auth_mode": resolved_auth_mode,
        "di_meta": di_meta,
        "parse_stats": parse_stats,
        "rows": len(output_rows),
        "output_csv": output_csv.as_posix(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run end-to-end VM quote pipeline in one command")
    parser.add_argument("--input", required=True, help="Input file path (.xlsx/.xls/.csv/.pdf)")
    parser.add_argument("--work-dir", help="Output work directory, default output/pipeline_runs/<timestamp>")
    parser.add_argument("--profile", choices=["aws_vm", "all_resources"], default="aws_vm")
    parser.add_argument("--include-review", action="store_true", help="Keep review rows in extraction")
    parser.add_argument("--default-azure-region", default="eastasia")
    parser.add_argument("--mapping-file", help="Override region mapping file path")

    parser.add_argument("--skip-sap-inference", action="store_true")
    parser.add_argument("--skip-aws-indicators", action="store_true")
    parser.add_argument("--skip-region-mapping", action="store_true")

    parser.add_argument("--customer-project", default="VM Migration Quote")
    parser.add_argument("--region", default="")
    parser.add_argument("--currency", default="USD (excl. tax)")
    parser.add_argument("--competitor-cloud", default="AWS")
    parser.add_argument("--pricing-source-note", default="Azure Retail Prices API + AWS EC2 Offer File")

    parser.add_argument("--di-endpoint", help="Azure Document Intelligence endpoint (PDF mode)")
    parser.add_argument("--di-key", help="Azure Document Intelligence key (PDF mode)")
    parser.add_argument("--di-auth-mode", default="auto", choices=["auto", "key", "aad"])
    parser.add_argument("--di-model-id", default="prebuilt-layout")
    parser.add_argument("--env-file", default=".env", help=".env path for PDF mode")
    parser.add_argument("--subscription-id", help="Azure subscription id for DI discovery")
    parser.add_argument("--resource-group", help="Azure resource group for DI discovery")
    parser.add_argument("--account-name", help="Azure DI account name for discovery")

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = resolve_project_root()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = project_root / input_path
    input_path = input_path.resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"Input not found: {input_path.as_posix()}")

    work_dir = Path(args.work_dir).resolve() if args.work_dir else (project_root / "output" / "pipeline_runs" / _now_tag())
    work_dir.mkdir(parents=True, exist_ok=True)

    mapping_file = None
    if args.mapping_file:
        mapping_file = Path(args.mapping_file)
        if not mapping_file.is_absolute():
            mapping_file = project_root / mapping_file
        mapping_file = mapping_file.resolve()

    env_file = Path(args.env_file)
    if not env_file.is_absolute():
        env_file = project_root / env_file

    artifacts = {
        "step_1_extracted": (work_dir / "1_extracted.csv").as_posix(),
        "step_2_sap": (work_dir / "2_sap.csv").as_posix(),
        "step_3_region": (work_dir / "3_region.csv").as_posix(),
        "step_4_indicators": (work_dir / "4_indicators.csv").as_posix(),
        "step_5_mapping": (work_dir / "5_azure_mapping.csv").as_posix(),
        "step_6_pricing": (work_dir / "6_pricing.csv").as_posix(),
        "step_7_payload": (work_dir / "7_quote_payload.json").as_posix(),
        "step_8_excel": (work_dir / "8_quote.xlsx").as_posix(),
    }

    extracted_csv = Path(artifacts["step_1_extracted"])
    sap_csv = Path(artifacts["step_2_sap"])
    region_csv = Path(artifacts["step_3_region"])
    indicators_csv = Path(artifacts["step_4_indicators"])
    azure_mapping_csv = Path(artifacts["step_5_mapping"])
    pricing_csv = Path(artifacts["step_6_pricing"])
    payload_json = Path(artifacts["step_7_payload"])
    quote_xlsx = Path(artifacts["step_8_excel"])

    execution_log: list[dict[str, Any]] = []

    suffix = input_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        step = _run_python_script(
            project_root / "scripts" / "extract_excel_inputs.py",
            [
                "--input-excel",
                str(input_path),
                "--output",
                str(extracted_csv),
                "--profile",
                args.profile,
                *(["--include-review"] if args.include_review else []),
            ],
        )
        execution_log.append({"step": "extract_excel", **step})
    elif suffix == ".pdf":
        step = _extract_from_pdf(
            input_pdf=input_path,
            output_csv=extracted_csv,
            profile=args.profile,
            include_review=args.include_review,
            endpoint=args.di_endpoint,
            key=args.di_key,
            env_file=env_file,
            auth_mode=args.di_auth_mode,
            model_id=args.di_model_id,
            subscription_id=args.subscription_id,
            resource_group=args.resource_group,
            account_name=args.account_name,
        )
        execution_log.append({"step": "extract_pdf", **step})
    elif suffix == ".csv":
        with input_path.open("r", encoding="utf-8-sig", newline="") as src, extracted_csv.open(
            "w", encoding="utf-8", newline=""
        ) as dst:
            dst.write(src.read())
        execution_log.append({"step": "extract_csv_passthrough", "status": "ok", "output": extracted_csv.as_posix()})
    else:
        raise ValueError("Unsupported input type. Use .xlsx/.xls/.csv/.pdf")

    current_csv = extracted_csv

    if not args.skip_sap_inference:
        step = _run_python_script(
            project_root
            / ".github"
            / "skills"
            / "vm-sap-workload-inference"
            / "scripts"
            / "infer_sap_workload.py",
            [
                "--input-file",
                str(current_csv),
                "--output",
                str(sap_csv),
            ],
        )
        execution_log.append({"step": "sap_inference", **step})
        current_csv = sap_csv

    if not args.skip_region_mapping:
        step = _map_regions(
            input_csv=current_csv,
            output_csv=region_csv,
            default_azure_region=args.default_azure_region,
            mapping_file=mapping_file,
        )
        execution_log.append({"step": "region_mapping", **step})
        current_csv = region_csv

    if not args.skip_aws_indicators:
        _ensure_instance_type_column(current_csv)
        step = _run_python_script(
            project_root
            / ".github"
            / "skills"
            / "vm-aws-instance-to-config"
            / "scripts"
            / "aws_instance_indicators.py",
            [
                "--input-file",
                str(current_csv),
                "--column",
                "instance_type",
                "--output",
                str(indicators_csv),
            ],
        )
        execution_log.append({"step": "aws_instance_indicators", **step})
        current_csv = indicators_csv

    step = _run_python_script(
        project_root
        / ".github"
        / "skills"
        / "vm-config-to-azure-instance"
        / "scripts"
        / "vm_config_to_azure_instance.py",
        [
            "--input-file",
            str(current_csv),
            "--output",
            str(azure_mapping_csv),
        ],
    )
    execution_log.append({"step": "azure_mapping", **step})

    step = _run_python_script(
        project_root
        / ".github"
        / "skills"
        / "vm-pricing-retail-api"
        / "scripts"
        / "fetch_vm_prices.py",
        [
            "--input-file",
            str(azure_mapping_csv),
            "--output",
            str(pricing_csv),
        ],
    )
    execution_log.append({"step": "pricing", **step})

    step = _run_python_script(
        project_root / "scripts" / "build_vm_quote_payload.py",
        [
            "--input-csv",
            str(pricing_csv),
            "--output-json",
            str(payload_json),
            "--customer-project",
            args.customer_project,
            "--region",
            args.region,
            "--currency",
            args.currency,
            "--competitor-cloud",
            args.competitor_cloud,
            "--pricing-source-note",
            args.pricing_source_note,
        ],
    )
    execution_log.append({"step": "build_payload", **step})

    step = _run_python_script(
        project_root / "scripts" / "write_quote_excel.py",
        [
            "--input-json",
            str(payload_json),
            "--output-xlsx",
            str(quote_xlsx),
        ],
    )
    execution_log.append({"step": "write_excel", **step})

    manifest = {
        "status": "ok",
        "input": input_path.as_posix(),
        "work_dir": work_dir.as_posix(),
        "artifacts": artifacts,
        "steps": execution_log,
        "finished_at": datetime.now().isoformat(),
    }

    manifest_path = work_dir / "run_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
