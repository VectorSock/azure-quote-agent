from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert get_regions.xlsx to get_regions.csv")
    parser.add_argument(
        "--input",
        default="data/get_regions.xlsx",
        help="Source Excel mapping file path",
    )
    parser.add_argument(
        "--output",
        default="data/get_regions.csv",
        help="Target CSV mapping file path",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8",
        help="CSV encoding (default: utf-8)",
    )
    return parser.parse_args()


def _resolve(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def main() -> int:
    args = parse_args()
    input_path = _resolve(args.input)
    output_path = _resolve(args.output)

    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    df = pd.read_excel(input_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_path, index=False, encoding=args.encoding)

    print(f"Converted {input_path.as_posix()} -> {output_path.as_posix()} ({len(df)} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
