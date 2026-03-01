from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

AWS_RE = re.compile(r"^(?P<family>[a-z]+)(?P<gen>\d+)(?P<opts>[a-z0-9]*)\.(?P<size>[a-z0-9]+)$")


def parse_aws_instance_type(value: str) -> dict[str, Any]:
    text = (value or "").strip().lower()
    matched = AWS_RE.match(text)
    if not matched:
        raise ValueError(f"Unrecognized AWS instance type format: {value!r}")

    return {
        "raw": value,
        "series": matched.group("family"),
        "generation": int(matched.group("gen")) if matched.group("gen") else None,
        "options": matched.group("opts") or "",
        "size": matched.group("size"),
    }


def aws_size_to_vcpus(size: str) -> int:
    token = (size or "").strip().lower()
    fixed = {
        "nano": 1,
        "micro": 1,
        "small": 1,
        "medium": 1,
        "large": 2,
        "xlarge": 4,
    }
    if token in fixed:
        return fixed[token]

    matched = re.match(r"^(?P<n>\d+)xlarge$", token)
    if matched:
        return 4 * int(matched.group("n"))

    if token.startswith("metal"):
        raise ValueError("Metal size is not supported by this heuristic parser")

    raise ValueError(f"Unsupported AWS size token: {size!r}")


def estimate_memory_gb(series: str, vcpu: int) -> float:
    family = (series or "").lower()
    if family.startswith(("r", "x", "u", "z")):
        ratio = 8.0
    elif family.startswith(("m", "i", "d")):
        ratio = 4.0
    elif family.startswith(("c", "t")):
        ratio = 2.0
    elif family.startswith(("p", "g")):
        ratio = 8.0
    else:
        ratio = 4.0
    return round(vcpu * ratio, 1)


def profile_from_series(series: str) -> str:
    token = (series or "").lower()
    if token.startswith("t"):
        return "burstable"
    if token.startswith("c"):
        return "compute"
    if token.startswith(("r", "x", "u", "z")):
        return "memory"
    if token.startswith(("i", "d", "h")):
        return "storage"
    if token.startswith(("p", "g")):
        return "gpu"
    return "general"


def memory_ratio_from_series(series: str) -> float:
    token = (series or "").lower()
    if token.startswith(("r", "x", "u", "z")):
        return 8.0
    if token.startswith(("m", "i", "d")):
        return 4.0
    if token.startswith(("c", "t")):
        return 2.0
    if token.startswith(("p", "g")):
        return 8.0
    return 4.0


def cpu_arch_from_options(options: str) -> str:
    token = (options or "").lower()
    if "g" in token:
        return "arm64"
    return "x86_64"


def cpu_vendor_from_options(options: str) -> str:
    token = (options or "").lower()
    if "a" in token:
        return "amd"
    if "g" in token:
        return "arm"
    if "i" in token:
        return "intel"
    return "unspecified_x86_vendor"


def requires_intel(options: str) -> bool:
    token = (options or "").lower()
    return "i" in token and "a" not in token and "g" not in token


def build_indicators(instance_type: str) -> dict[str, Any]:
    parsed = parse_aws_instance_type(instance_type)
    vcpu = aws_size_to_vcpus(parsed["size"])
    memory_ratio = memory_ratio_from_series(parsed["series"])
    memory_gb = round(vcpu * memory_ratio, 1)

    profile = profile_from_series(parsed["series"])
    options = parsed["options"]

    has_local_temp_disk = "d" in options or profile == "storage"
    is_ebs_optimized = "b" in options
    is_gpu_accelerated = profile == "gpu"
    is_network_optimized = "n" in options
    is_burstable = profile == "burstable"
    cpu_arch = cpu_arch_from_options(options)
    cpu_vendor = cpu_vendor_from_options(options)
    intel_required = requires_intel(options)

    sap_possible = (
        profile in {"general", "memory"}
        and not is_gpu_accelerated
        and cpu_arch != "arm64"
        and vcpu >= 16
        and memory_gb >= 64
    )

    if parsed["size"] in {"nano", "micro", "small"}:
        size_rule_confidence = "medium"
    else:
        size_rule_confidence = "high"

    return {
        "input_instance_type": instance_type,
        "status": "ok",
        "series": parsed["series"],
        "generation": parsed["generation"],
        "options": options,
        "size": parsed["size"],
        "vcpu": vcpu,
        "memory_gb": memory_gb,
        "memory_ratio": memory_ratio,
        "cpu_arch": cpu_arch,
        "cpu_vendor": cpu_vendor,
        "requires_intel": intel_required,
        "has_local_temp_disk": has_local_temp_disk,
        "is_ebs_optimized": is_ebs_optimized,
        "is_gpu_accelerated": is_gpu_accelerated,
        "is_network_optimized": is_network_optimized,
        "is_burstable": is_burstable,
        "profile": profile,
        "sap_possible": sap_possible,
        "size_rule_confidence": size_rule_confidence,
        "memory_rule_confidence": "high",
        "matched_by": "aws_naming_rules",
    }


def safe_build(instance_type: str) -> dict[str, Any]:
    try:
        return build_indicators(instance_type)
    except Exception as exc:  # noqa: BLE001
        return {
            "input_instance_type": instance_type,
            "status": "unrecognized_format",
            "error": str(exc),
            "matched_by": "none",
        }


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
    parser = argparse.ArgumentParser(description="AWS instance type to VM indicators")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--instance-type", help="single AWS instance type, e.g. m6a.4xlarge")
    group.add_argument("--input-file", help="input CSV path for batch mode")

    parser.add_argument("--column", default="instance_type", help="instance type column name in CSV")
    parser.add_argument("--output", default="output/aws_instance_indicators.csv", help="output CSV path for batch mode")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.instance_type is not None:
        result = safe_build(args.instance_type)
        print(json.dumps(result, ensure_ascii=False))
        return

    input_file = Path(args.input_file)
    if not input_file.is_absolute():
        input_file = Path.cwd() / input_file
    if not input_file.exists():
        raise FileNotFoundError(f"Input file not found: {input_file.as_posix()}")

    rows = load_csv(input_file)
    if not rows:
        print(json.dumps({"status": "ok", "rows": 0, "message": "empty input"}, ensure_ascii=False))
        return

    if args.column not in rows[0]:
        raise ValueError(f"Column not found: {args.column}")

    output_rows: list[dict[str, Any]] = []
    for row in rows:
        instance_type = str(row.get(args.column) or "").strip()
        indicators = safe_build(instance_type)
        merged = dict(row)
        merged.update(indicators)
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
                "column": args.column,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
