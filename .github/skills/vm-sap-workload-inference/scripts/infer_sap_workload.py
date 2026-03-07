from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any
import sys

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[4]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.sap_inference import infer_sap_workload


def parse_bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    token = str(value).strip().lower()
    if token in {"", "none", "null", "nan", "n/a", "na", "tbd", "pending"}:
        return None
    if token in {"1", "true", "yes", "y", "on"}:
        return True
    if token in {"0", "false", "no", "n", "off"}:
        return False
    return None


def load_table(path: Path) -> list[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(path)
        if df is None:
            return []
        return [{key: row.get(key) for key in df.columns} for _, row in df.iterrows()]

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


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(rows).to_excel(path, index=False)
        return
    write_csv(path, rows)


def detect_existing_column(row: dict[str, Any], candidates: list[str]) -> str | None:
    normalized = {str(key).strip().lower(): key for key in row.keys()}
    for candidate in candidates:
        hit = normalized.get(candidate.lower())
        if hit:
            return hit
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Infer SAP_workload from system/env/workload_type")

    parser.add_argument("--system", help="single mode system name")
    parser.add_argument("--env", help="single mode env")
    parser.add_argument("--workload-type", help="single mode workload_type")

    parser.add_argument("--input-file", help="batch mode input csv/xlsx")
    parser.add_argument("--output", default="output/sap_workload_inferred.csv", help="batch mode output csv/xlsx")
    parser.add_argument("--overwrite", action="store_true", help="overwrite existing SAP_workload value")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.input_file:
        input_file = Path(args.input_file)
        if not input_file.is_absolute():
            input_file = Path.cwd() / input_file
        if not input_file.exists():
            raise FileNotFoundError(f"Input file not found: {input_file.as_posix()}")

        rows = load_table(input_file)
        if not rows:
            print(json.dumps({"status": "ok", "rows": 0, "message": "empty input"}, ensure_ascii=False))
            return

        sap_col = detect_existing_column(rows[0], ["sap_workload", "SAP_workload"])
        system_col = detect_existing_column(rows[0], ["system", "sys", "application", "landscape_system"])
        env_col = detect_existing_column(rows[0], ["env", "environment"])
        workload_col = detect_existing_column(rows[0], ["workload_type", "workload", "type", "scenario", "usage"])

        if system_col is None and workload_col is None:
            raise ValueError("Batch input should contain at least one of: system, workload_type")

        output_rows: list[dict[str, Any]] = []
        for row in rows:
            result = infer_sap_workload(
                system=row.get(system_col) if system_col else None,
                env=row.get(env_col) if env_col else None,
                workload_type=row.get(workload_col) if workload_col else None,
            )

            merged = dict(row)
            existing = parse_bool_or_none(merged.get(sap_col)) if sap_col else None
            inferred = result["is_sap_workload"]

            target_col = sap_col or "SAP_workload"
            if args.overwrite or existing is None:
                merged[target_col] = "True" if inferred else "False"

            merged["sap_workload_inferred"] = inferred
            merged["sap_workload_confidence"] = result["confidence"]
            merged["sap_workload_category"] = result["category"]
            merged["sap_workload_subtype"] = result["subtype"]
            merged["sap_workload_role"] = result["role"]
            merged["sap_workload_env_norm"] = result["env_normalized"]
            merged["sap_workload_score"] = result["score"]
            merged["sap_workload_reason"] = "|".join(result["reasons"])

            output_rows.append(merged)

        output_file = Path(args.output)
        if not output_file.is_absolute():
            output_file = Path.cwd() / output_file
        write_table(output_file, output_rows)

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

    if args.system is None and args.workload_type is None:
        raise ValueError("Single mode requires at least --system or --workload-type")

    result = infer_sap_workload(system=args.system, env=args.env, workload_type=args.workload_type)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
