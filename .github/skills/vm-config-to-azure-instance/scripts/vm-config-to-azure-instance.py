from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def family_from_shape(vcpu: int, memory_gb: float, burstable: bool, gpu: bool) -> str:
    if gpu:
        return "N"
    if burstable:
        return "B"
    ratio = memory_gb / max(vcpu, 1)
    if ratio >= 6.0:
        return "E"
    if ratio <= 2.5:
        return "F"
    return "D"


def choose_version(family: str) -> str:
    token = family.upper()
    if token == "B":
        return ""
    if token in {"D", "E"}:
        return "_v5"
    if token == "F":
        return "_v2"
    if token.startswith("N"):
        return "_v3"
    return "_v5"


def features_from_config(
    family: str,
    cpu_vendor: str,
    cpu_arch: str,
    burstable: bool,
    gpu: bool,
    local_temp_disk: bool,
    network_optimized: bool,
    prefer_amd: bool,
) -> str:
    features: list[str] = []
    family_token = family.upper()

    if (cpu_vendor == "amd" or (prefer_amd and cpu_vendor == "unknown")) and cpu_arch != "arm64" and not burstable and not gpu:
        features.append("a")
    if cpu_arch == "arm64":
        features.append("p")
    if local_temp_disk:
        features.append("d")
    if network_optimized:
        features.append("n")
    if family_token != "B":
        features.append("s")

    ordered = ["a", "p", "d", "n", "s"]
    features = [item for item in ordered if item in features]

    deduped: list[str] = []
    for feature in features:
        if feature not in deduped:
            deduped.append(feature)
    return "".join(deduped)


def candidate_families(primary: str) -> list[str]:
    token = primary.upper()
    if token == "D":
        return ["D", "E", "F"]
    if token == "E":
        return ["E", "M", "D"]
    if token == "F":
        return ["F", "D", "E"]
    if token == "N":
        return ["N", "E", "D"]
    if token == "B":
        return ["B", "D", "F"]
    return [token, "D", "E", "F"]


def fallback_features(primary_features: str, family: str) -> list[str]:
    family_token = family.upper()
    values = [primary_features]

    if family_token == "B":
        candidates = ["", "a"]
    else:
        candidates = ["as", "s", "a", "ds", "d", ""]

    for candidate in candidates:
        if candidate not in values:
            values.append(candidate)
    return values


def build_candidates(primary_family: str, vcpu: int, features: str, fallback_count: int) -> tuple[str, list[str]]:
    primary = f"Standard_{primary_family}{vcpu}{features}{choose_version(primary_family)}"
    candidates: list[str] = [primary]

    for family in candidate_families(primary_family):
        sizes_to_try = [vcpu]
        if family in {"D", "E", "F", "M"}:
            sizes_to_try.append(vcpu * 2)

        for candidate_vcpu in sizes_to_try:
            for suffix in fallback_features(features, family):
                sku = f"Standard_{family}{candidate_vcpu}{suffix}{choose_version(family)}"
                if sku not in candidates:
                    candidates.append(sku)
                if len(candidates) >= fallback_count + 1:
                    return primary, candidates[1 : fallback_count + 1]

    return primary, candidates[1 : fallback_count + 1]


def confidence_score(primary_family: str, vcpu: int, memory_gb: float, burstable: bool, gpu: bool) -> float:
    ratio = memory_gb / max(vcpu, 1)
    if gpu and primary_family == "N":
        return 0.9
    if burstable and primary_family == "B":
        return 0.86
    if primary_family == "E" and ratio >= 6.0:
        return 0.84
    if primary_family == "F" and ratio <= 2.5:
        return 0.84
    if primary_family == "D" and 2.5 < ratio < 6.0:
        return 0.82
    return 0.72


def map_single(
    vcpu: int,
    memory_gb: float,
    cpu_vendor: str,
    cpu_arch: str,
    burstable: bool,
    gpu: bool,
    local_temp_disk: bool,
    network_optimized: bool,
    prefer_amd: bool,
    fallback_count: int,
) -> dict[str, Any]:
    if vcpu <= 0 or memory_gb <= 0:
        return {
            "status": "invalid_input",
            "error": "vcpu and memory_gb must be positive",
        }

    family = family_from_shape(vcpu, memory_gb, burstable, gpu)
    features = features_from_config(
        family=family,
        cpu_vendor=cpu_vendor,
        cpu_arch=cpu_arch,
        burstable=burstable,
        gpu=gpu,
        local_temp_disk=local_temp_disk,
        network_optimized=network_optimized,
        prefer_amd=prefer_amd,
    )
    primary_sku, fallback_skus = build_candidates(family, vcpu, features, fallback_count)
    confidence = confidence_score(family, vcpu, memory_gb, burstable, gpu)

    assumptions = [
        "version_policy_applied",
        "premium_storage_suffix_default_except_b_family",
        "fallback_suffix_priority_applied",
        "fallback_size_escalation_applied",
    ]
    if cpu_vendor == "unknown" and prefer_amd and cpu_arch != "arm64" and not burstable and not gpu:
        assumptions.append("cpu_vendor_unknown_prefer_amd_applied")

    return {
        "status": "ok",
        "input": {
            "vcpu": vcpu,
            "memory_gb": memory_gb,
            "cpu_vendor": cpu_vendor,
            "cpu_arch": cpu_arch,
            "burstable": burstable,
            "gpu": gpu,
            "local_temp_disk": local_temp_disk,
            "network_optimized": network_optimized,
        },
        "primary_sku": primary_sku,
        "fallback_skus": fallback_skus,
        "mapping_confidence": round(confidence, 2),
        "matched_by": "shape_and_feature_policy",
        "assumptions": assumptions,
    }


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    token = str(value).strip().lower()
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
    parser = argparse.ArgumentParser(description="Map VM config to Azure VM instance")

    parser.add_argument("--vcpu", type=int, help="vCPU count for single mode")
    parser.add_argument("--memory-gb", type=float, help="memory in GB for single mode")
    parser.add_argument("--cpu-vendor", choices=["amd", "intel", "arm", "unknown"], default="unknown")
    parser.add_argument("--cpu-arch", choices=["x86_64", "arm64"], default="x86_64")
    parser.add_argument("--burstable", action="store_true")
    parser.add_argument("--gpu", action="store_true")
    parser.add_argument("--local-temp-disk", action="store_true")
    parser.add_argument("--network-optimized", action="store_true")
    parser.add_argument("--prefer-amd", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--fallback-count", type=int, default=3)

    parser.add_argument("--input-file", help="batch mode CSV input")
    parser.add_argument("--output", default="output/azure_instance_mapping.csv", help="batch output CSV")

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.input_file:
        input_file = Path(args.input_file)
        if not input_file.is_absolute():
            input_file = Path.cwd() / input_file
        if not input_file.exists():
            raise FileNotFoundError(f"Input file not found: {input_file.as_posix()}")

        rows = load_csv(input_file)
        if not rows:
            print(json.dumps({"status": "ok", "rows": 0, "message": "empty input"}, ensure_ascii=False))
            return

        required_any = {
            "vcpu": ["vcpu", "parsed_vcpu"],
            "memory_gb": ["memory_gb", "parsed_memory_gb"],
        }
        missing = [name for name, candidates in required_any.items() if all(col not in rows[0] for col in candidates)]
        if missing:
            raise ValueError(
                "Batch input missing required columns. "
                f"Need at least one of each group: {required_any}; missing groups={missing}"
            )

        output_rows: list[dict[str, Any]] = []
        for row in rows:
            vcpu_value = first_non_empty(row, ["vcpu", "parsed_vcpu"], 0)
            memory_value = first_non_empty(row, ["memory_gb", "parsed_memory_gb"], 0)

            cpu_vendor = str(first_non_empty(row, ["cpu_vendor", "parsed_cpu_vendor"], "unknown")).strip().lower()
            if cpu_vendor in {"", "none", "null", "nan", "unspecified_x86_vendor"}:
                cpu_vendor = "unknown"

            result = map_single(
                vcpu=int(float(vcpu_value or 0)),
                memory_gb=float(memory_value or 0),
                cpu_vendor=cpu_vendor,
                cpu_arch=str(first_non_empty(row, ["cpu_arch", "parsed_cpu_arch"], "x86_64")).strip().lower(),
                burstable=parse_bool(str(first_non_empty(row, ["burstable", "is_burstable"], ""))),
                gpu=parse_bool(str(first_non_empty(row, ["gpu", "is_gpu_accelerated"], ""))),
                local_temp_disk=parse_bool(str(first_non_empty(row, ["local_temp_disk", "has_local_temp_disk"], ""))),
                network_optimized=parse_bool(
                    str(first_non_empty(row, ["network_optimized", "is_network_optimized"], ""))
                ),
                prefer_amd=parse_bool(str(row.get("prefer_amd") or "true"), default=True),
                fallback_count=int(float(row.get("fallback_count") or args.fallback_count)),
            )
            merged = dict(row)
            merged.update(
                {
                    "status": result.get("status"),
                    "primary_sku": result.get("primary_sku"),
                    "fallback_skus": "|".join(result.get("fallback_skus", [])),
                    "mapping_confidence": result.get("mapping_confidence"),
                    "matched_by": result.get("matched_by"),
                    "assumptions": "|".join(result.get("assumptions", [])),
                    "error": result.get("error"),
                }
            )
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
                },
                ensure_ascii=False,
            )
        )
        return

    if args.vcpu is None or args.memory_gb is None:
        raise ValueError("Single mode requires --vcpu and --memory-gb")

    result = map_single(
        vcpu=args.vcpu,
        memory_gb=args.memory_gb,
        cpu_vendor=args.cpu_vendor,
        cpu_arch=args.cpu_arch,
        burstable=args.burstable,
        gpu=args.gpu,
        local_temp_disk=args.local_temp_disk,
        network_optimized=args.network_optimized,
        prefer_amd=args.prefer_amd,
        fallback_count=args.fallback_count,
    )
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
