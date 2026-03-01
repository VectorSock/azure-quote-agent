import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd
from openpyxl import load_workbook


SHEETS = ["Summary", "LineItems", "Assumptions", "Evidence"]


def _print(obj: Dict[str, Any]) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def init_template(template_path: Path) -> None:
    template_path.parent.mkdir(parents=True, exist_ok=True)
    with pd.ExcelWriter(template_path, engine="openpyxl") as writer:
        pd.DataFrame(columns=["metric", "value", "notes"]).to_excel(
            writer, sheet_name="Summary", index=False
        )
        pd.DataFrame(
            columns=[
                "item_id",
                "provider",
                "service",
                "sku",
                "region",
                "quantity",
                "unit",
                "unit_price_hourly",
                "monthly_hours",
                "monthly_cost",
                "term",
                "currency",
                "confidence",
                "notes",
            ]
        ).to_excel(writer, sheet_name="LineItems", index=False)
        pd.DataFrame(columns=["key", "value", "source", "notes"]).to_excel(
            writer, sheet_name="Assumptions", index=False
        )
        pd.DataFrame(columns=["evidence_type", "ref", "detail"]).to_excel(
            writer, sheet_name="Evidence", index=False
        )


def load_payload(input_json: Path) -> Dict[str, Any]:
    with input_json.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    if "summary" not in payload or "line_items" not in payload:
        raise ValueError("input json must contain `summary` and `line_items`")
    return payload


def _to_df_summary(summary: Dict[str, Any]) -> pd.DataFrame:
    rows = []
    for key, value in summary.items():
        if isinstance(value, dict):
            rows.append({"metric": key, "value": json.dumps(value, ensure_ascii=False), "notes": ""})
        else:
            rows.append({"metric": key, "value": value, "notes": ""})
    return pd.DataFrame(rows, columns=["metric", "value", "notes"])


def _to_df_line_items(line_items: List[Dict[str, Any]]) -> pd.DataFrame:
    default_cols = [
        "item_id",
        "provider",
        "service",
        "sku",
        "region",
        "quantity",
        "unit",
        "unit_price_hourly",
        "monthly_hours",
        "monthly_cost",
        "term",
        "currency",
        "confidence",
        "notes",
    ]
    df = pd.DataFrame(line_items)
    for col in default_cols:
        if col not in df.columns:
            df[col] = None
    return df[default_cols]


def _to_df_assumptions(assumptions: Any) -> pd.DataFrame:
    if assumptions is None:
        return pd.DataFrame(columns=["key", "value", "source", "notes"])
    if isinstance(assumptions, list):
        if len(assumptions) == 0:
            return pd.DataFrame(columns=["key", "value", "source", "notes"])
        return pd.DataFrame(assumptions)
    if isinstance(assumptions, dict):
        return pd.DataFrame(
            [{"key": key, "value": value, "source": "", "notes": ""} for key, value in assumptions.items()]
        )
    raise ValueError("assumptions must be dict or list")


def _to_df_evidence(evidence: Any) -> pd.DataFrame:
    if evidence is None:
        return pd.DataFrame(columns=["evidence_type", "ref", "detail"])
    if isinstance(evidence, list):
        if len(evidence) == 0:
            return pd.DataFrame(columns=["evidence_type", "ref", "detail"])
        return pd.DataFrame(evidence)
    raise ValueError("evidence must be list")


def write_quote_excel(payload: Dict[str, Any], output_xlsx: Path, template: Path) -> Dict[str, Any]:
    if not template.exists():
        raise FileNotFoundError(f"template not found: {template}")

    output_xlsx.parent.mkdir(parents=True, exist_ok=True)

    workbook = load_workbook(template)
    workbook.save(output_xlsx)

    summary_df = _to_df_summary(payload.get("summary", {}))
    line_df = _to_df_line_items(payload.get("line_items", []))
    assumptions_df = _to_df_assumptions(payload.get("assumptions"))
    evidence_df = _to_df_evidence(payload.get("evidence"))

    with pd.ExcelWriter(
        output_xlsx, engine="openpyxl", mode="a", if_sheet_exists="replace"
    ) as writer:
        summary_df.to_excel(writer, sheet_name="Summary", index=False)
        line_df.to_excel(writer, sheet_name="LineItems", index=False)
        assumptions_df.to_excel(writer, sheet_name="Assumptions", index=False)
        evidence_df.to_excel(writer, sheet_name="Evidence", index=False)

    return {
        "status": "ok",
        "output_file": str(output_xlsx),
        "sheets_written": SHEETS,
        "row_counts": {
            "Summary": len(summary_df),
            "LineItems": len(line_df),
            "Assumptions": len(assumptions_df),
            "Evidence": len(evidence_df),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Write structured quote payload into Excel workbook.")
    parser.add_argument("--input-json", help="Path to structured quote JSON payload.")
    parser.add_argument("--output-xlsx", help="Output Excel path.")
    parser.add_argument(
        "--template",
        default="skills/excel-quote-writer/assets/summary-layout-template.xlsx",
        help="Template workbook path.",
    )
    parser.add_argument("--init-template", action="store_true", help="Initialize template workbook and exit.")
    args = parser.parse_args()

    template = Path(args.template)

    try:
        if args.init_template:
            init_template(template)
            _print(
                {
                    "status": "ok",
                    "message": "template initialized",
                    "template_file": str(template),
                }
            )
            return

        if not args.input_json or not args.output_xlsx:
            raise ValueError("`--input-json` and `--output-xlsx` are required unless `--init-template` is used")

        payload = load_payload(Path(args.input_json))
        result = write_quote_excel(payload, Path(args.output_xlsx), template)
        _print(result)

    except Exception as exc:  # noqa: BLE001
        _print({"status": "error", "error": str(exc)})


if __name__ == "__main__":
    main()
