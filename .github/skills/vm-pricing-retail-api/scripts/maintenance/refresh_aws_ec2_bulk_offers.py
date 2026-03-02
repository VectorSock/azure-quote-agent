from __future__ import annotations

import argparse
import json
import shutil
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


DEFAULT_AWS_BASE_URL = "https://pricing.us-east-1.amazonaws.com"


def _now_compact_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _get_json(url: str, timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "aws-ec2-bulk-refresh/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _load_aws_regions_from_excel(excel_path: Path, cloud_col: str, region_col: str) -> list[str]:
    df = pd.read_excel(excel_path)
    if cloud_col not in df.columns:
        raise ValueError(f"Missing required column: {cloud_col}")
    if region_col not in df.columns:
        raise ValueError(f"Missing required column: {region_col}")

    regions = {
        str(region).strip().lower()
        for cloud, region in zip(df[cloud_col], df[region_col], strict=False)
        if str(cloud).strip().lower() == "aws" and str(region).strip() != ""
    }
    if not regions:
        raise ValueError("No AWS regions found in mapping Excel")

    return sorted(regions)


def _refresh_current_dir(snapshot_dir: Path, current_dir: Path) -> None:
    if current_dir.exists():
        for child in current_dir.iterdir():
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                shutil.rmtree(child)
    current_dir.mkdir(parents=True, exist_ok=True)

    for child in snapshot_dir.iterdir():
        if child.is_file():
            shutil.copy2(child, current_dir / child.name)


def _ensure_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download AWS EC2 bulk offer JSON for all AWS regions")

    parser.add_argument(
        "--regions-excel",
        default=".github/skills/region-mapping/assets/get_regions.xlsx",
        help="Path to get_regions.xlsx",
    )
    parser.add_argument(
        "--output-root",
        default=".github/skills/vm-pricing-retail-api/assets/aws_ec2_bulk_offers",
        help="Output root directory",
    )
    parser.add_argument("--cloud-column", default="Cloud", help="Excel cloud column name")
    parser.add_argument("--region-column", default="Region", help="Excel region column name")
    parser.add_argument("--timeout", type=int, default=60, help="HTTP timeout seconds")
    parser.add_argument("--aws-base-url", default=DEFAULT_AWS_BASE_URL, help="AWS pricing base URL")
    parser.add_argument(
        "--max-regions",
        type=int,
        default=0,
        help="For testing only: limit number of regions to process; 0 means all",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()

    regions_excel = _ensure_path(Path(args.regions_excel))
    output_root = _ensure_path(Path(args.output_root))

    current_dir = output_root / "current"
    snapshots_dir = output_root / "snapshots"
    manifests_dir = output_root / "manifests"

    current_dir.mkdir(parents=True, exist_ok=True)
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    manifests_dir.mkdir(parents=True, exist_ok=True)

    timestamp = _now_compact_utc()
    snapshot_dir = snapshots_dir / timestamp
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    aws_regions = _load_aws_regions_from_excel(
        excel_path=regions_excel,
        cloud_col=args.cloud_column,
        region_col=args.region_column,
    )
    if args.max_regions and args.max_regions > 0:
        aws_regions = aws_regions[: args.max_regions]

    index_url = f"{args.aws_base_url}/offers/v1.0/aws/AmazonEC2/current/region_index.json"
    index_payload = _get_json(index_url, timeout=args.timeout)
    (snapshot_dir / "region_index.json").write_text(json.dumps(index_payload, ensure_ascii=False), encoding="utf-8")

    index_regions = index_payload.get("regions", {})
    if not isinstance(index_regions, dict):
        raise ValueError("Invalid region_index.json format: regions is not an object")

    downloaded: list[str] = []
    missing_from_index: list[str] = []
    failed: dict[str, str] = {}

    for region in aws_regions:
        entry = index_regions.get(region)
        if not isinstance(entry, dict):
            missing_from_index.append(region)
            continue

        current_version_url = entry.get("currentVersionUrl")
        if not current_version_url:
            missing_from_index.append(region)
            continue

        offer_url = f"{args.aws_base_url}{current_version_url}"
        try:
            payload = _get_json(offer_url, timeout=args.timeout)
            payload["_source_url"] = offer_url
            (snapshot_dir / f"{region}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            downloaded.append(region)
        except Exception as exc:  # noqa: BLE001
            failed[region] = str(exc)

    manifest = {
        "status": "ok" if not failed else "partial",
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "regions_excel": str(regions_excel),
        "output_root": str(output_root),
        "snapshot": timestamp,
        "aws_base_url": args.aws_base_url,
        "total_regions_from_excel": len(aws_regions),
        "downloaded_count": len(downloaded),
        "missing_from_index_count": len(missing_from_index),
        "failed_count": len(failed),
        "downloaded_regions": downloaded,
        "missing_from_index": missing_from_index,
        "failed_regions": failed,
    }

    snapshot_manifest_path = snapshot_dir / "manifest.json"
    snapshot_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    run_manifest_path = manifests_dir / f"{timestamp}.json"
    run_manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_path = output_root / "latest.json"
    latest_payload = {
        "latest_snapshot": timestamp,
        "latest_manifest": str(run_manifest_path.relative_to(output_root)).replace("\\", "/"),
    }
    latest_path.write_text(json.dumps(latest_payload, ensure_ascii=False, indent=2), encoding="utf-8")

    _refresh_current_dir(snapshot_dir=snapshot_dir, current_dir=current_dir)

    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
