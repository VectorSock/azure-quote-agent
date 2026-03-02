from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / ".github/skills/vm-quote-pipeline-runner/assets/defaults.yaml"
DEFAULT_TEMPLATE = PROJECT_ROOT / ".github/skills/excel-quote-writer/assets/summary-layout-template.xlsx"


@dataclass(frozen=True)
class Step:
    step_id: str
    script_rel: str


DEFAULT_STEPS: list[Step] = [
    Step("step_01_extract", ".github/skills/excel-input-extraction/scripts/extract_excel_inputs.py"),
    Step("step_02_region_mapping", ".github/skills/region-mapping/scripts/region_mapping.py"),
    Step("step_03_aws_instance_to_config", ".github/skills/vm-aws-instance-to-config/scripts/aws_instance_indicators.py"),
    Step("step_04_config_to_azure_instance", ".github/skills/vm-config-to-azure-instance/scripts/vm-config-to-azure-instance.py"),
    Step("step_05_pricing", ".github/skills/vm-pricing-retail-api/scripts/fetch_vm_prices.py"),
    Step("step_06_build_quote_payload", ".github/skills/excel-quote-writer/scripts/build_vm_quote_payload.py"),
    Step("step_07_write_quote_excel", ".github/skills/excel-quote-writer/scripts/write_quote_excel.py"),
]


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def parse_last_json_line(text: str) -> dict[str, Any] | None:
    for line in reversed(text.splitlines()):
        token = line.strip()
        if not token or not token.startswith("{"):
            continue
        try:
            data = json.loads(token)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    return None


def ensure_file(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_defaults(config_path: Path) -> dict[str, Any]:
    defaults: dict[str, Any] = {
        "profile": "aws_vm",
        "monthly_hours": 730,
        "currency": "USD (excl. tax)",
        "competitor_cloud": "AWS",
        "pricing_source_note": "Azure Retail Prices API + AWS Pricing API (GetProducts)",
        "defaults": {
            "include_review": False,
            "extraction_output_name": "step_01_extracted.csv",
            "region_output_name": "step_02_region_mapped.csv",
            "indicators_output_name": "step_03_aws_indicators.csv",
            "azure_mapping_output_name": "step_04_azure_mapping.csv",
            "pricing_output_name": "step_05_pricing.csv",
            "payload_output_name": "step_06_quote_payload.json",
            "quote_output_name": "quote_result.xlsx",
        },
    }

    if not config_path.exists():
        return defaults

    try:
        import yaml  # type: ignore

        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            for key in ["profile", "monthly_hours", "currency", "competitor_cloud", "pricing_source_note"]:
                if key in loaded:
                    defaults[key] = loaded[key]
            if isinstance(loaded.get("defaults"), dict):
                defaults["defaults"].update(loaded["defaults"])
    except Exception:
        pass

    return defaults


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run VM quote pipeline in fixed order")
    parser.add_argument("--input-excel", required=True, help="Input Excel file")
    parser.add_argument("--output-root", default="output", help="Output root folder")
    parser.add_argument("--resume-from", choices=[step.step_id for step in DEFAULT_STEPS], help="Resume from step id")
    parser.add_argument("--python-exe", default=sys.executable, help="Python executable path")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Defaults YAML path")

    parser.add_argument("--customer-project", default="VM Migration Quote", help="Summary customer/project")
    parser.add_argument("--region", default="", help="Summary region")
    parser.add_argument("--include-review", action="store_true", help="Include review rows during extraction")
    parser.add_argument("--skip-aws", action="store_true", help="Skip AWS pricing")
    parser.add_argument("--skip-azure", action="store_true", help="Skip Azure pricing")

    parser.add_argument("--profile", default=None, help="Extraction profile override")
    parser.add_argument("--template", default=str(DEFAULT_TEMPLATE), help="Quote template path")
    return parser.parse_args()


def run_step(
    step: Step,
    command: list[str],
    report_path: Path,
    expected_artifacts: list[Path],
    cwd: Path,
) -> tuple[bool, dict[str, Any]]:
    started_at = now_iso()
    proc = subprocess.run(command, cwd=str(cwd), capture_output=True, text=True)
    finished_at = now_iso()
    stdout_json = parse_last_json_line(proc.stdout)

    artifacts = [{"path": str(path.as_posix()), "exists": path.exists()} for path in expected_artifacts]
    artifact_ok = all(item["exists"] for item in artifacts)

    reported_status = str(stdout_json.get("status")) if isinstance(stdout_json, dict) and "status" in stdout_json else None

    failed = False
    failure_reason = None
    if proc.returncode != 0:
        failed = True
        failure_reason = f"non_zero_exit:{proc.returncode}"
    elif reported_status == "error":
        failed = True
        failure_reason = "status_error"
    elif stdout_json is None and not artifact_ok:
        failed = True
        failure_reason = "no_json_and_no_artifact"

    report: dict[str, Any] = {
        "step_id": step.step_id,
        "status": "failed" if failed else "ok",
        "started_at": started_at,
        "finished_at": finished_at,
        "command": command,
        "exit_code": proc.returncode,
        "stdout_last_json": stdout_json,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "artifacts": artifacts,
        "error": failure_reason,
    }

    ensure_file(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return (not failed), report


def build_commands(args: argparse.Namespace, run_dir: Path, cfg: dict[str, Any]) -> dict[str, tuple[list[str], list[Path]]]:
    names = cfg["defaults"]
    profile = args.profile or cfg.get("profile", "aws_vm")
    include_review = bool(args.include_review or names.get("include_review", False))

    extract_csv = run_dir / str(names["extraction_output_name"])
    region_csv = run_dir / str(names["region_output_name"])
    indicators_csv = run_dir / str(names["indicators_output_name"])
    azure_map_csv = run_dir / str(names["azure_mapping_output_name"])
    pricing_csv = run_dir / str(names["pricing_output_name"])
    payload_json = run_dir / str(names["payload_output_name"])
    quote_xlsx = run_dir / str(names["quote_output_name"])

    command_map: dict[str, tuple[list[str], list[Path]]] = {
        "step_01_extract": (
            [
                args.python_exe,
                str((PROJECT_ROOT / DEFAULT_STEPS[0].script_rel).as_posix()),
                "--input-excel",
                str(Path(args.input_excel).as_posix()),
                "--output",
                str(extract_csv.as_posix()),
                "--profile",
                str(profile),
            ]
            + (["--include-review"] if include_review else []),
            [extract_csv],
        ),
        "step_02_region_mapping": (
            [
                args.python_exe,
                str((PROJECT_ROOT / DEFAULT_STEPS[1].script_rel).as_posix()),
                "--input-file",
                str(extract_csv.as_posix()),
                "--column",
                "region_input",
                "--output",
                str(region_csv.as_posix()),
            ],
            [region_csv],
        ),
        "step_03_aws_instance_to_config": (
            [
                args.python_exe,
                str((PROJECT_ROOT / DEFAULT_STEPS[2].script_rel).as_posix()),
                "--input-file",
                str(region_csv.as_posix()),
                "--column",
                "instance_type",
                "--output",
                str(indicators_csv.as_posix()),
            ],
            [indicators_csv],
        ),
        "step_04_config_to_azure_instance": (
            [
                args.python_exe,
                str((PROJECT_ROOT / DEFAULT_STEPS[3].script_rel).as_posix()),
                "--input-file",
                str(indicators_csv.as_posix()),
                "--output",
                str(azure_map_csv.as_posix()),
            ],
            [azure_map_csv],
        ),
        "step_05_pricing": (
            [
                args.python_exe,
                str((PROJECT_ROOT / DEFAULT_STEPS[4].script_rel).as_posix()),
                "--input-file",
                str(azure_map_csv.as_posix()),
                "--output",
                str(pricing_csv.as_posix()),
            ]
            + (["--skip-aws"] if args.skip_aws else [])
            + (["--skip-azure"] if args.skip_azure else []),
            [pricing_csv],
        ),
        "step_06_build_quote_payload": (
            [
                args.python_exe,
                str((PROJECT_ROOT / DEFAULT_STEPS[5].script_rel).as_posix()),
                "--input-csv",
                str(pricing_csv.as_posix()),
                "--output-json",
                str(payload_json.as_posix()),
                "--monthly-hours",
                str(cfg.get("monthly_hours", 730)),
                "--customer-project",
                str(args.customer_project),
                "--region",
                str(args.region),
                "--currency",
                str(cfg.get("currency", "USD (excl. tax)")),
                "--competitor-cloud",
                str(cfg.get("competitor_cloud", "AWS")),
                "--pricing-source-note",
                str(cfg.get("pricing_source_note", "Azure Retail Prices API + AWS Pricing API (GetProducts)")),
            ],
            [payload_json],
        ),
        "step_07_write_quote_excel": (
            [
                args.python_exe,
                str((PROJECT_ROOT / DEFAULT_STEPS[6].script_rel).as_posix()),
                "--input-json",
                str(payload_json.as_posix()),
                "--output-xlsx",
                str(quote_xlsx.as_posix()),
                "--template",
                str(Path(args.template).as_posix()),
            ],
            [quote_xlsx],
        ),
    }

    return command_map


def main() -> None:
    args = parse_args()

    input_excel = Path(args.input_excel)
    if not input_excel.is_absolute():
        input_excel = PROJECT_ROOT / input_excel
    if not input_excel.exists():
        raise FileNotFoundError(f"Input Excel not found: {input_excel.as_posix()}")

    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = PROJECT_ROOT / output_root

    run_dir = output_root / input_excel.stem
    run_dir.mkdir(parents=True, exist_ok=True)

    cfg = load_defaults(Path(args.config))
    command_map = build_commands(args=args, run_dir=run_dir, cfg=cfg)

    start_idx = 0
    if args.resume_from:
        start_idx = [step.step_id for step in DEFAULT_STEPS].index(args.resume_from)

    run_reports: list[str] = []
    skipped_reports: list[str] = []

    for idx, step in enumerate(DEFAULT_STEPS):
        report_path = run_dir / f"{step.step_id}.json"

        if idx < start_idx:
            skipped = {
                "step_id": step.step_id,
                "status": "skipped_resume",
                "started_at": now_iso(),
                "finished_at": now_iso(),
                "command": None,
                "exit_code": None,
                "stdout_last_json": None,
                "stdout": "",
                "stderr": "",
                "artifacts": [],
                "error": None,
            }
            report_path.write_text(json.dumps(skipped, ensure_ascii=False, indent=2), encoding="utf-8")
            skipped_reports.append(str(report_path.as_posix()))
            continue

        command, expected_artifacts = command_map[step.step_id]
        ok, report = run_step(step, command, report_path, expected_artifacts, cwd=PROJECT_ROOT)
        run_reports.append(str(report_path.as_posix()))

        if not ok:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "failed_step": step.step_id,
                        "run_dir": run_dir.as_posix(),
                        "step_reports": skipped_reports + run_reports,
                        "last_error": report.get("error"),
                    },
                    ensure_ascii=False,
                )
            )
            return

    print(
        json.dumps(
            {
                "status": "ok",
                "failed_step": None,
                "run_dir": run_dir.as_posix(),
                "step_reports": skipped_reports + run_reports,
                "final_quote": str((run_dir / cfg["defaults"]["quote_output_name"]).as_posix()),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
