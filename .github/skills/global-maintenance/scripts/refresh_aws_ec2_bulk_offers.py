from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import socket
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError

import pandas as pd


DEFAULT_AWS_BASE_URL = "https://pricing.us-east-1.amazonaws.com"
SCRIPT_VERSION = "1.1.0"
DEFAULT_USER_AGENT = "aws-ec2-bulk-refresh/1.1"
URL_OPENER = urllib.request.build_opener()


def _now_compact_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _get_bytes_with_retry(
    url: str,
    timeout: int,
    retries: int,
    retry_backoff_seconds: float,
    user_agent: str,
) -> bytes:
    retries = max(1, retries)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept-Encoding": "gzip",
        },
    )
    last_exc: Exception | None = None

    for attempt in range(1, retries + 1):
        try:
            with URL_OPENER.open(req, timeout=timeout) as resp:  # noqa: S310
                payload = resp.read()
                if resp.headers.get("Content-Encoding", "").lower() == "gzip":
                    return gzip.decompress(payload)
                return payload
        except (HTTPError, URLError, TimeoutError, socket.timeout) as exc:
            last_exc = exc
            if attempt == retries:
                break
            backoff = retry_backoff_seconds * (2 ** (attempt - 1))
            time.sleep(backoff)

    assert last_exc is not None
    raise last_exc


def _load_aws_regions_from_excel(excel_path: Path, cloud_col: str, region_col: str) -> list[str]:
    df = pd.read_excel(excel_path)
    if cloud_col not in df.columns:
        raise ValueError(f"Missing required column: {cloud_col}")
    if region_col not in df.columns:
        raise ValueError(f"Missing required column: {region_col}")

    regions: set[str] = set()
    for cloud, region in zip(df[cloud_col], df[region_col], strict=False):
        if not pd.notna(cloud) or str(cloud).strip().lower() != "aws":
            continue
        if not pd.notna(region):
            continue
        region_value = str(region).strip().lower()
        if region_value:
            regions.add(region_value)

    if not regions:
        raise ValueError("No AWS regions found in mapping Excel")

    return sorted(regions)


def _refresh_current_dir(snapshot_dir: Path, current_dir: Path) -> None:
    current_dir.parent.mkdir(parents=True, exist_ok=True)

    suffix = _now_compact_utc()
    temp_dir = current_dir.parent / f".current_tmp_{suffix}"
    backup_dir = current_dir.parent / f".current_backup_{suffix}"

    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    if backup_dir.exists():
        shutil.rmtree(backup_dir)

    # Snapshot copy is recursive so current mirrors any nested structure.
    shutil.copytree(snapshot_dir, temp_dir)

    old_exists = current_dir.exists()
    try:
        if old_exists:
            current_dir.replace(backup_dir)
        temp_dir.replace(current_dir)
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
    except Exception:
        if temp_dir.exists():
            shutil.rmtree(temp_dir)
        if old_exists and backup_dir.exists() and not current_dir.exists():
            backup_dir.replace(current_dir)
        raise


def _download_region_offer(
    region: str,
    offer_url: str,
    snapshot_dir: Path,
    timeout: int,
    retries: int,
    retry_backoff_seconds: float,
    user_agent: str,
) -> dict[str, Any]:
    started = time.perf_counter()
    payload = _get_bytes_with_retry(
        url=offer_url,
        timeout=timeout,
        retries=retries,
        retry_backoff_seconds=retry_backoff_seconds,
        user_agent=user_agent,
    )
    output_file = snapshot_dir / f"{region}.json"
    output_file.write_bytes(payload)

    return {
        "region": region,
        "source_url": offer_url,
        "snapshot_file": output_file.name,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "duration_seconds": round(time.perf_counter() - started, 3),
    }


def _ensure_path(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download AWS EC2 bulk offer JSON for all AWS regions")

    parser.add_argument(
        "--regions-excel",
        default=".github/skills/global-region-mapping/assets/get_regions.xlsx",
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
    parser.add_argument("--max-workers", type=int, default=8, help="Max concurrent region downloads")
    parser.add_argument("--retries", type=int, default=3, help="Retry attempts for network requests")
    parser.add_argument(
        "--retry-backoff-seconds",
        type=float,
        default=1.0,
        help="Exponential backoff base seconds",
    )
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="HTTP User-Agent")
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
    run_started = time.perf_counter()

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
    index_raw = _get_bytes_with_retry(
        url=index_url,
        timeout=args.timeout,
        retries=args.retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        user_agent=args.user_agent,
    )
    (snapshot_dir / "region_index.json").write_bytes(index_raw)
    index_payload = json.loads(index_raw.decode("utf-8"))

    index_regions = index_payload.get("regions", {})
    if not isinstance(index_regions, dict):
        raise ValueError("Invalid region_index.json format: regions is not an object")

    downloaded: list[str] = []
    missing_from_index: list[str] = []
    failed: dict[str, str] = {}
    failed_type_counts: dict[str, int] = {}
    downloaded_region_details: list[dict[str, Any]] = []

    region_urls: dict[str, str] = {}
    for region in aws_regions:
        entry = index_regions.get(region)
        if not isinstance(entry, dict):
            missing_from_index.append(region)
            continue

        current_version_url = entry.get("currentVersionUrl")
        if not current_version_url:
            missing_from_index.append(region)
            continue

        region_urls[region] = f"{args.aws_base_url}{current_version_url}"

    with ThreadPoolExecutor(max_workers=max(1, args.max_workers)) as executor:
        future_to_region = {
            executor.submit(
                _download_region_offer,
                region,
                offer_url,
                snapshot_dir,
                args.timeout,
                args.retries,
                args.retry_backoff_seconds,
                args.user_agent,
            ): region
            for region, offer_url in region_urls.items()
        }

        for future in as_completed(future_to_region):
            region = future_to_region[future]
            try:
                result = future.result()
                downloaded.append(region)
                downloaded_region_details.append(result)
            except Exception as exc:  # noqa: BLE001
                failed[region] = str(exc)
                exc_name = type(exc).__name__
                failed_type_counts[exc_name] = failed_type_counts.get(exc_name, 0) + 1

    downloaded.sort()
    missing_from_index.sort()
    downloaded_region_details.sort(key=lambda item: str(item.get("region", "")))

    manifest = {
        "status": "ok" if not failed else "partial",
        "script_version": SCRIPT_VERSION,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "duration_seconds": round(time.perf_counter() - run_started, 3),
        "regions_excel": str(regions_excel),
        "output_root": str(output_root),
        "snapshot": timestamp,
        "aws_base_url": args.aws_base_url,
        "request": {
            "timeout_seconds": args.timeout,
            "max_workers": args.max_workers,
            "retries": args.retries,
            "retry_backoff_seconds": args.retry_backoff_seconds,
            "user_agent": args.user_agent,
            "accept_encoding": "gzip",
        },
        "total_regions_from_excel": len(aws_regions),
        "downloaded_count": len(downloaded),
        "missing_from_index_count": len(missing_from_index),
        "failed_count": len(failed),
        "downloaded_regions": downloaded,
        "downloaded_region_details": downloaded_region_details,
        "missing_from_index": missing_from_index,
        "failed_regions": failed,
        "failed_type_counts": failed_type_counts,
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
