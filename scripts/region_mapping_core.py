from __future__ import annotations

from dataclasses import dataclass
from math import hypot
from pathlib import Path
from typing import Any

import pandas as pd


def normalize_token(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value).strip().lower() if ch.isalnum())


def parse_float(value: object) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class RegionResolution:
    input_value: str | None
    mapped_city: str | None
    mapped_aws_region: str | None
    mapped_azure_region: str | None
    mapped_gcp_region: str | None
    mapped_by: str
    confidence: str
    warning: str | None


@dataclass
class AzureGeoEntry:
    region: str
    country: str | None
    city: str | None
    latitude: float | None
    longitude: float | None


class RegionResolver:
    def __init__(
        self,
        city_index: dict[str, dict[str, str]],
        city_display: dict[str, str],
        region_index: dict[str, tuple[str, str]],
        region_long_name_index: dict[str, dict[str, object]],
        city_geo_meta: dict[str, dict[str, object]],
        azure_geo_entries: list[AzureGeoEntry],
    ) -> None:
        self.city_index = city_index
        self.city_display = city_display
        self.region_index = region_index
        self.region_long_name_index = region_long_name_index
        self.city_geo_meta = city_geo_meta
        self.azure_geo_entries = azure_geo_entries

    def _nearest_azure_region(
        self,
        country: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> str | None:
        candidates = self.azure_geo_entries
        if country:
            same_country = [entry for entry in candidates if (entry.country or "").strip().lower() == country.strip().lower()]
            if same_country:
                candidates = same_country

        if not candidates:
            return None

        if latitude is None or longitude is None:
            return candidates[0].region

        with_geo = [entry for entry in candidates if entry.latitude is not None and entry.longitude is not None]
        if not with_geo:
            return candidates[0].region

        nearest = min(with_geo, key=lambda entry: hypot(entry.latitude - latitude, entry.longitude - longitude))
        return nearest.region

    @classmethod
    def from_excel(cls, excel_path: Path) -> "RegionResolver":
        suffix = excel_path.suffix.lower()
        if suffix == ".csv":
            df = pd.read_csv(excel_path)
        elif suffix in {".xlsx", ".xls"}:
            df = pd.read_excel(excel_path)
        else:
            raise ValueError(f"unsupported mapping file type: {suffix}")

        expected_columns = {"Cloud", "Region", "City"}
        if not expected_columns.issubset(set(df.columns)):
            missing = sorted(expected_columns.difference(set(df.columns)))
            raise ValueError(f"mapping file missing columns: {missing}")

        city_index: dict[str, dict[str, str]] = {}
        city_display: dict[str, str] = {}
        region_index: dict[str, tuple[str, str]] = {}
        region_long_name_index: dict[str, dict[str, object]] = {}
        city_geo_meta: dict[str, dict[str, object]] = {}
        azure_geo_entries: list[AzureGeoEntry] = []

        for _, row in df.iterrows():
            cloud = str(row.get("Cloud") or "").strip().lower()
            region = str(row.get("Region") or "").strip().lower()
            region_long_name = str(row.get("Region Long Name") or "").strip()
            city = str(row.get("City") or "").strip()
            country = str(row.get("Country") or "").strip() or None
            latitude = parse_float(row.get("Latitude"))
            longitude = parse_float(row.get("Longitude"))

            if cloud not in {"aws", "azure", "gcp"}:
                continue
            if not region or not city:
                continue

            city_key = normalize_token(city)
            city_display.setdefault(city_key, city)
            city_index.setdefault(city_key, {})[cloud] = region

            if city_key not in city_geo_meta:
                city_geo_meta[city_key] = {
                    "country": country,
                    "latitude": latitude,
                    "longitude": longitude,
                }

            region_index[normalize_token(region)] = (cloud, city_key)

            if cloud == "azure":
                azure_geo_entries.append(
                    AzureGeoEntry(
                        region=region,
                        country=country,
                        city=city,
                        latitude=latitude,
                        longitude=longitude,
                    )
                )

            if region_long_name:
                region_long_name_index[normalize_token(region_long_name)] = {
                    "cloud": cloud,
                    "city_key": city_key,
                    "country": country,
                    "latitude": latitude,
                    "longitude": longitude,
                }

        return cls(
            city_index=city_index,
            city_display=city_display,
            region_index=region_index,
            region_long_name_index=region_long_name_index,
            city_geo_meta=city_geo_meta,
            azure_geo_entries=azure_geo_entries,
        )

    def resolve(self, location_input: str | None, default_azure_region: str) -> RegionResolution:
        raw = (location_input or "").strip()
        probe = raw or default_azure_region
        probe_key = normalize_token(probe)

        if probe_key in self.city_index:
            city_key = probe_key
            regions = self.city_index[city_key]
            city_meta = self.city_geo_meta.get(city_key, {})
            azure_region = regions.get("azure") or self._nearest_azure_region(
                country=city_meta.get("country"),
                latitude=city_meta.get("latitude"),
                longitude=city_meta.get("longitude"),
            )
            return RegionResolution(
                input_value=location_input,
                mapped_city=self.city_display.get(city_key),
                mapped_aws_region=regions.get("aws"),
                mapped_azure_region=azure_region or default_azure_region,
                mapped_gcp_region=regions.get("gcp"),
                mapped_by="city_name" if regions.get("azure") else "city_geo",
                confidence="high",
                warning=None,
            )

        if probe_key in self.region_index:
            _, city_key = self.region_index[probe_key]
            regions = self.city_index.get(city_key, {})
            city_meta = self.city_geo_meta.get(city_key, {})
            azure_region = regions.get("azure") or self._nearest_azure_region(
                country=city_meta.get("country"),
                latitude=city_meta.get("latitude"),
                longitude=city_meta.get("longitude"),
            )
            return RegionResolution(
                input_value=location_input,
                mapped_city=self.city_display.get(city_key),
                mapped_aws_region=regions.get("aws"),
                mapped_azure_region=azure_region or (probe.lower() if "-" not in probe else default_azure_region),
                mapped_gcp_region=regions.get("gcp"),
                mapped_by="region_id" if regions.get("azure") else "city_geo",
                confidence="high",
                warning=None,
            )

        if probe_key in self.region_long_name_index:
            info = self.region_long_name_index[probe_key]
            city_key = str(info.get("city_key") or "")
            regions = self.city_index.get(city_key, {})
            azure_region = regions.get("azure") or self._nearest_azure_region(
                country=info.get("country") if isinstance(info.get("country"), str | type(None)) else None,
                latitude=info.get("latitude") if isinstance(info.get("latitude"), float | type(None)) else None,
                longitude=info.get("longitude") if isinstance(info.get("longitude"), float | type(None)) else None,
            )
            return RegionResolution(
                input_value=location_input,
                mapped_city=self.city_display.get(city_key),
                mapped_aws_region=regions.get("aws"),
                mapped_azure_region=azure_region or default_azure_region,
                mapped_gcp_region=regions.get("gcp"),
                mapped_by="region_long_name" if regions.get("azure") else "city_geo",
                confidence="high",
                warning=None,
            )

        warning = "Low-confidence fallback mapping. Please verify mapped regions manually."
        return RegionResolution(
            input_value=location_input,
            mapped_city=None,
            mapped_aws_region=probe.lower() if "-" in probe else None,
            mapped_azure_region=probe.lower() if "-" not in probe else default_azure_region,
            mapped_gcp_region=None,
            mapped_by="fallback",
            confidence="low",
            warning=warning,
        )


def format_resolution(result: RegionResolution) -> dict[str, Any]:
    return {
        "mapped_city": result.mapped_city,
        "mapped_aws_region": result.mapped_aws_region,
        "mapped_azure_region": result.mapped_azure_region,
        "mapped_gcp_region": result.mapped_gcp_region,
        "mapped_by": result.mapped_by,
        "confidence": result.confidence,
        "warning": result.warning,
    }


def detect_column(df: pd.DataFrame, preferred: str | None) -> str:
    if preferred:
        if preferred not in df.columns:
            raise ValueError(f"column does not exist: {preferred}")
        return preferred

    lowered = {str(col).strip().lower(): col for col in df.columns}
    for candidate in [
        "region_input",
        "region",
        "location",
        "city",
        "site",
        "region_name",
        "region long name",
        "区域",
        "地区",
        "城市",
        "地域",
    ]:
        if candidate in lowered:
            return str(lowered[candidate])

    raise ValueError("location column not found, pass --column")


def load_input(input_path: Path) -> pd.DataFrame:
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(input_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(input_path)
    raise ValueError(f"unsupported input file type: {suffix}")


def write_output(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    if suffix == ".csv":
        df.to_csv(output_path, index=False)
        return
    if suffix in {".xlsx", ".xls"}:
        df.to_excel(output_path, index=False)
        return
    raise ValueError(f"unsupported output file type: {suffix}")


def resolve_locations(
    resolver: RegionResolver,
    locations: list[str | None],
    default_azure_region: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = [format_resolution(resolver.resolve(location, default_azure_region)) for location in locations]
    fallback_count = sum(1 for row in rows if row["mapped_by"] == "fallback")
    resolved_count = len(rows) - fallback_count
    hit_rate = (resolved_count / len(rows)) if rows else 0.0
    stats = {
        "rows": len(rows),
        "fallback_count": fallback_count,
        "resolved_count": resolved_count,
        "hit_rate": hit_rate,
    }
    return rows, stats


def resolve_file(
    resolver: RegionResolver,
    input_file: Path,
    output_file: Path,
    column: str | None,
    default_azure_region: str,
) -> dict[str, Any]:
    df = load_input(input_file)
    location_col = detect_column(df, column)
    raw_locations: list[str | None] = []
    for value in df[location_col].tolist():
        raw_locations.append(None if pd.isna(value) else str(value))

    mapped_rows, stats = resolve_locations(resolver, raw_locations, default_azure_region)
    mapped_df = pd.DataFrame(mapped_rows)
    result_df = pd.concat([df.reset_index(drop=True), mapped_df], axis=1)
    write_output(result_df, output_file)

    return {
        "status": "ok",
        "rows": stats["rows"],
        "fallback_count": stats["fallback_count"],
        "hit_rate": stats["hit_rate"],
        "location_column": location_col,
        "input_file": str(input_file.as_posix()),
        "output_file": str(output_file.as_posix()),
    }


def resolve_project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_mapping_file(path_arg: str | None) -> Path:
    if path_arg:
        path = Path(path_arg)
        return path if path.is_absolute() else resolve_project_root() / path

    candidates = [
        resolve_project_root() / "data" / "get_regions.csv",
        resolve_project_root() / "data" / "rget_regions.csv",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]
