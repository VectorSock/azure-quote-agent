from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from math import hypot
from pathlib import Path
from typing import Any

import pandas as pd


def _normalize(value: str | None) -> str:
    if value is None:
        return ""
    return "".join(ch for ch in str(value).strip().lower() if ch.isalnum())


def _parse_float(value: object) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


@dataclass
class RegionResolution:
    input_value: str | None
    city: str | None
    aws_region: str | None
    azure_region: str | None
    gcp_region: str | None
    matched_by: str


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
        df = pd.read_excel(excel_path)

        expected_columns = {"Cloud", "Region", "City"}
        if not expected_columns.issubset(set(df.columns)):
            missing = sorted(expected_columns.difference(set(df.columns)))
            raise ValueError(f"映射表缺少列: {missing}")

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
            latitude = _parse_float(row.get("Latitude"))
            longitude = _parse_float(row.get("Longitude"))

            if cloud not in {"aws", "azure", "gcp"}:
                continue
            if not region or not city:
                continue

            city_key = _normalize(city)
            city_display.setdefault(city_key, city)
            city_index.setdefault(city_key, {})[cloud] = region

            if city_key not in city_geo_meta:
                city_geo_meta[city_key] = {
                    "country": country,
                    "latitude": latitude,
                    "longitude": longitude,
                }

            region_index[_normalize(region)] = (cloud, city_key)

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
                region_long_name_index[_normalize(region_long_name)] = {
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
        probe_key = _normalize(probe)

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
                city=self.city_display.get(city_key),
                aws_region=regions.get("aws"),
                azure_region=azure_region or default_azure_region,
                gcp_region=regions.get("gcp"),
                matched_by="city_name" if regions.get("azure") else "city_geo",
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
                city=self.city_display.get(city_key),
                aws_region=regions.get("aws"),
                azure_region=azure_region or (probe.lower() if "-" not in probe else default_azure_region),
                gcp_region=regions.get("gcp"),
                matched_by="region_id" if regions.get("azure") else "city_geo",
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
                city=self.city_display.get(city_key),
                aws_region=regions.get("aws"),
                azure_region=azure_region or default_azure_region,
                gcp_region=regions.get("gcp"),
                matched_by="region_long_name" if regions.get("azure") else "city_geo",
            )

        return RegionResolution(
            input_value=location_input,
            city=None,
            aws_region=probe.lower() if "-" in probe else None,
            azure_region=probe.lower() if "-" not in probe else default_azure_region,
            gcp_region=None,
            matched_by="fallback",
        )


def resolve_project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def resolve_mapping_file(path_arg: str | None) -> Path:
    if path_arg:
        path = Path(path_arg)
        return path if path.is_absolute() else resolve_project_root() / path

    candidates = [
        resolve_project_root() / ".github" / "skills" / "global-region-mapping" / "assets" / "get_regions.xlsx",
        resolve_project_root() / "skills" / "global-region-mapping" / "assets" / "get_regions.xlsx",
        resolve_project_root() / "data" / "get_regions.xlsx",
        Path(__file__).resolve().parents[1] / "assets" / "get_regions.xlsx",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate

    return candidates[0]


def load_input(input_path: Path) -> pd.DataFrame:
    suffix = input_path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(input_path)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(input_path)
    raise ValueError(f"不支持的输入文件类型: {suffix}")


def write_output(df: pd.DataFrame, output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    suffix = output_path.suffix.lower()
    if suffix == ".csv":
        df.to_csv(output_path, index=False)
        return
    if suffix in {".xlsx", ".xls"}:
        df.to_excel(output_path, index=False)
        return
    raise ValueError(f"不支持的输出文件类型: {suffix}")


def detect_column(df: pd.DataFrame, preferred: str | None) -> str:
    if preferred:
        if preferred not in df.columns:
            raise ValueError(f"指定列不存在: {preferred}")
        return preferred

    normalized_cols = {_normalize(str(col)): col for col in df.columns}
    aliases = [
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
    ]
    for alias in aliases:
        key = _normalize(alias)
        if key in normalized_cols:
            return str(normalized_cols[key])

    raise ValueError("未找到位置列，请通过 --column 指定")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Region mapping skill")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--location", help="单条位置输入")
    group.add_argument("--input-file", help="批量输入文件路径")

    parser.add_argument("--column", help="批量输入位置列名")
    parser.add_argument("--output", default="output/region_mapping_results.csv", help="批量输出文件路径")
    parser.add_argument("--mapping-file", help="映射表路径")
    parser.add_argument("--default-azure-region", default="eastasia", help="回退 Azure Region")
    return parser.parse_args()


def format_result(result: RegionResolution) -> dict[str, Any]:
    return {
        "input_value": result.input_value,
        "city": result.city,
        "aws_region": result.aws_region,
        "azure_region": result.azure_region,
        "gcp_region": result.gcp_region,
        "matched_by": result.matched_by,
    }


def run_single(resolver: RegionResolver, location: str, default_azure_region: str) -> None:
    result = resolver.resolve(location, default_azure_region)
    print(json.dumps(format_result(result), ensure_ascii=False))


def run_batch(
    resolver: RegionResolver,
    input_file: Path,
    output_file: Path,
    column: str | None,
    default_azure_region: str,
) -> None:
    df = load_input(input_file)
    location_col = detect_column(df, column)

    mapped = []
    for value in df[location_col].tolist():
        location = None if pd.isna(value) else str(value)
        mapped.append(format_result(resolver.resolve(location, default_azure_region)))

    mapped_df = pd.DataFrame(mapped).rename(
        columns={
            "city": "mapped_city",
            "aws_region": "mapped_aws_region",
            "azure_region": "mapped_azure_region",
            "gcp_region": "mapped_gcp_region",
            "matched_by": "mapped_by",
        }
    )
    result_df = pd.concat([df.reset_index(drop=True), mapped_df.drop(columns=["input_value"])], axis=1)
    write_output(result_df, output_file)

    summary = {
        "status": "ok",
        "rows": len(result_df),
        "input_file": str(input_file.as_posix()),
        "output_file": str(output_file.as_posix()),
        "location_column": location_col,
    }
    print(json.dumps(summary, ensure_ascii=False))


def main() -> None:
    args = parse_args()

    mapping_file = resolve_mapping_file(args.mapping_file)
    if not mapping_file.exists():
        raise FileNotFoundError(
            "未找到映射表，请提供 --mapping-file 或确认 skills/global-region-mapping/assets/get_regions.xlsx 存在"
        )

    resolver = RegionResolver.from_excel(mapping_file)

    if args.location is not None:
        run_single(resolver, args.location, args.default_azure_region)
        return

    input_file = Path(args.input_file)
    if not input_file.is_absolute():
        input_file = resolve_project_root() / input_file
    if not input_file.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_file.as_posix()}")

    output_file = Path(args.output)
    if not output_file.is_absolute():
        output_file = resolve_project_root() / output_file

    run_batch(
        resolver=resolver,
        input_file=input_file,
        output_file=output_file,
        column=args.column,
        default_azure_region=args.default_azure_region,
    )


if __name__ == "__main__":
    main()
