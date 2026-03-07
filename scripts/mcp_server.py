from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from scripts.region_mapping_core import RegionResolver
from scripts.region_mapping_core import resolve_file
from scripts.region_mapping_core import resolve_locations
from scripts.region_mapping_core import resolve_mapping_file
from scripts.region_mapping_core import resolve_project_root
from scripts.pdf_extraction_core import build_records_from_lines
from scripts.pdf_extraction_core import filter_rows
from scripts.pdf_extraction_core import load_di_settings
from scripts.pdf_extraction_core import parse_pdf_with_document_intelligence
from scripts.pdf_extraction_core import validate_di_connection as validate_di_connection_core
from scripts.pdf_extraction_core import write_csv

PROFILE_REQUIRED = {
    "aws_vm": ["instance_type"],
    "all_resources": ["resource_type"],
}

PROFILE_RECOMMENDED = {
    "aws_vm": [
        "provider",
        "resource_type",
        "instance_name",
        "quantity",
        "vcpu",
        "memory_gb",
        "os",
        "region_input",
        "workload",
    ],
    "all_resources": [
        "provider",
        "resource_type",
        "instance_name",
        "quantity",
        "vcpu",
        "memory_gb",
        "os",
        "region_input",
        "region_aws",
        "region_azure",
        "workload",
    ],
}


class MappingService:
    def __init__(self) -> None:
        self.project_root = resolve_project_root()
        self.mapping_file = resolve_mapping_file(None)
        self.resolver: RegionResolver | None = None
        self.reload_mapping()

    def _resolve_workspace_path(self, path_str: str) -> Path:
        path = Path(path_str)
        if not path.is_absolute():
            path = self.project_root / path
        return path.resolve()

    def _is_under(self, path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False

    def _validate_file_path(self, path_str: str, mode: str) -> Path:
        _ = mode
        candidate = self._resolve_workspace_path(path_str)
        allowed_roots = [
            (self.project_root / "input").resolve(),
            (self.project_root / "output").resolve(),
        ]
        if not any(self._is_under(candidate, root) for root in allowed_roots):
            roots = ", ".join(str(root) for root in allowed_roots)
            raise ValueError(f"path is outside allowed workspace roots: {roots}")
        return candidate

    def _validate_mapping_file_path(self, path_str: str) -> Path:
        candidate = self._resolve_workspace_path(path_str)
        allowed_roots = [
            (self.project_root / "data").resolve(),
        ]
        if not any(self._is_under(candidate, root) for root in allowed_roots):
            roots = ", ".join(str(root) for root in allowed_roots)
            raise ValueError(f"mapping_file must be under approved roots: {roots}")
        return candidate

    def _validate_project_file_path(self, path_str: str) -> Path:
        candidate = self._resolve_workspace_path(path_str)
        if not self._is_under(candidate, self.project_root):
            raise ValueError(f"path is outside project root: {self.project_root.as_posix()}")
        return candidate

    def reload_mapping(self, mapping_file: str | None = None) -> dict[str, Any]:
        if mapping_file:
            self.mapping_file = self._validate_mapping_file_path(mapping_file)
        if not self.mapping_file.exists():
            raise FileNotFoundError(
                "mapping file not found; pass mapping_file or ensure data/rget_regions.xlsx exists"
            )
        self.resolver = RegionResolver.from_excel(self.mapping_file)
        return {
            "status": "ok",
            "mapping_file": str(self.mapping_file.as_posix()),
            "message": "mapping cache reloaded",
        }


service = MappingService()
mcp = FastMCP("global-region-mapping")


@mcp.tool(
    name="map_region_single",
    description=(
        "Map one location into canonical cloud region fields. "
        "Returns mapped_city, mapped_aws_region, mapped_azure_region, mapped_gcp_region, mapped_by, confidence, warning."
    ),
)
def map_region_single(location: str, default_azure_region: str = "eastasia") -> dict[str, Any]:
    if service.resolver is None:
        raise RuntimeError("mapping resolver is not initialized")
    result = service.resolver.resolve(location, default_azure_region)
    return {
        "mapped_city": result.mapped_city,
        "mapped_aws_region": result.mapped_aws_region,
        "mapped_azure_region": result.mapped_azure_region,
        "mapped_gcp_region": result.mapped_gcp_region,
        "mapped_by": result.mapped_by,
        "confidence": result.confidence,
        "warning": result.warning,
    }


@mcp.tool(
    name="map_region_batch",
    description=(
        "Map multiple locations in one call. "
        "Returns per-row results with strict mapped_* fields and summary stats including fallback_count and hit_rate."
    ),
)
def map_region_batch(locations: list[str | None], default_azure_region: str = "eastasia") -> dict[str, Any]:
    if service.resolver is None:
        raise RuntimeError("mapping resolver is not initialized")

    rows, stats = resolve_locations(service.resolver, locations, default_azure_region)
    return {
        "rows": rows,
        "summary": {
            "rows": stats["rows"],
            "fallback_count": stats["fallback_count"],
            "hit_rate": stats["hit_rate"],
        },
    }


@mcp.tool(
    name="map_region_file",
    description=(
        "Read a CSV/XLSX location file, map regions, and write results to a file under allowed workspace roots. "
        "Use this for file-driven pipelines."
    ),
)
def map_region_file(
    input_file: str,
    column: str | None = None,
    output_file: str = "output/region_mapping_results.csv",
    default_azure_region: str = "eastasia",
) -> dict[str, Any]:
    if service.resolver is None:
        raise RuntimeError("mapping resolver is not initialized")

    safe_input = service._validate_file_path(input_file, mode="read")
    safe_output = service._validate_file_path(output_file, mode="write")

    if not safe_input.exists():
        raise FileNotFoundError(f"input file does not exist: {safe_input.as_posix()}")

    summary = resolve_file(
        resolver=service.resolver,
        input_file=safe_input,
        output_file=safe_output,
        column=column,
        default_azure_region=default_azure_region,
    )
    return {
        "rows": summary["rows"],
        "location_column": summary["location_column"],
        "output_file": summary["output_file"],
        "fallback_count": summary["fallback_count"],
        "hit_rate": summary["hit_rate"],
    }


@mcp.tool(
    name="reload_mapping",
    description="Reload mapping Excel into memory cache. Optional mapping_file path can be passed.",
)
def reload_mapping(mapping_file: str | None = None) -> dict[str, Any]:
    return service.reload_mapping(mapping_file)


@mcp.tool(
    name="extract_pdf_inputs",
    description=(
        "Extract normalized quote rows from one PDF using Azure Document Intelligence and write CSV under input/output roots. "
        "Returns summary and output_file."
    ),
)
def extract_pdf_inputs(
    input_pdf: str,
    output_file: str = "output/extracted_inputs_from_pdf.csv",
    profile: str = "aws_vm",
    include_review: bool = False,
    provider: str | None = None,
    resource_type: str | None = None,
    endpoint: str | None = None,
    key: str | None = None,
    env_file: str = ".env",
    auth_mode: str = "auto",
    subscription_id: str | None = None,
    resource_group: str | None = None,
    account_name: str | None = None,
    model_id: str = "prebuilt-layout",
) -> dict[str, Any]:
    if profile not in {"aws_vm", "all_resources"}:
        raise ValueError("profile must be one of: aws_vm, all_resources")

    safe_input = service._validate_file_path(input_pdf, mode="read")
    safe_output = service._validate_file_path(output_file, mode="write")
    safe_env = service._validate_project_file_path(env_file)

    if not safe_input.exists():
        raise FileNotFoundError(f"input PDF does not exist: {safe_input.as_posix()}")

    resolved_endpoint, resolved_auth_mode, resolved_key = load_di_settings(
        endpoint=endpoint,
        key=key,
        auth_mode=auth_mode,
        env_file=safe_env,
        subscription_id=subscription_id,
        resource_group=resource_group,
        account_name=account_name,
    )

    lines, di_meta = parse_pdf_with_document_intelligence(
        input_pdf=safe_input,
        endpoint=resolved_endpoint,
        key=resolved_key,
        auth_mode=resolved_auth_mode,
        model_id=model_id,
    )
    raw_rows, parse_stats = build_records_from_lines(lines=lines, include_review=include_review)
    output_rows = filter_rows(
        rows=raw_rows,
        profile=profile,
        provider=provider or "",
        resource_type=resource_type or "",
        include_review=include_review,
    )
    write_csv(safe_output, output_rows)

    return {
        "status": "ok",
        "input_pdf": safe_input.as_posix(),
        "output_file": safe_output.as_posix(),
        "profile": profile,
        "filters": {
            "provider": provider,
            "resource_type": resource_type,
            "include_review": include_review,
        },
        "total_rows": len(raw_rows),
        "eligible_rows": len(output_rows),
        "extracted_rows": len(output_rows),
        "required_for_next_skill": PROFILE_REQUIRED[profile],
        "recommended_columns": PROFILE_RECOMMENDED[profile],
        "auth_mode": resolved_auth_mode,
        "di_meta": di_meta,
        "parse_stats": parse_stats,
    }


@mcp.tool(
    name="extract_pdf_inputs_batch",
    description=(
        "Batch extract normalized quote rows from multiple PDFs. "
        "Each file writes one CSV under output roots and returns per-file summary and aggregate stats."
    ),
)
def extract_pdf_inputs_batch(
    input_pdfs: list[str],
    output_dir: str = "output",
    output_suffix: str = "_extracted.csv",
    profile: str = "aws_vm",
    include_review: bool = False,
    provider: str | None = None,
    resource_type: str | None = None,
    endpoint: str | None = None,
    key: str | None = None,
    env_file: str = ".env",
    auth_mode: str = "auto",
    subscription_id: str | None = None,
    resource_group: str | None = None,
    account_name: str | None = None,
    model_id: str = "prebuilt-layout",
) -> dict[str, Any]:
    if not input_pdfs:
        raise ValueError("input_pdfs must not be empty")
    if profile not in {"aws_vm", "all_resources"}:
        raise ValueError("profile must be one of: aws_vm, all_resources")

    safe_output_dir = service._validate_file_path(output_dir, mode="write")
    safe_env = service._validate_project_file_path(env_file)

    resolved_endpoint, resolved_auth_mode, resolved_key = load_di_settings(
        endpoint=endpoint,
        key=key,
        auth_mode=auth_mode,
        env_file=safe_env,
        subscription_id=subscription_id,
        resource_group=resource_group,
        account_name=account_name,
    )

    results: list[dict[str, Any]] = []
    total_extracted_rows = 0
    total_input_files = 0

    for input_pdf in input_pdfs:
        safe_input = service._validate_file_path(input_pdf, mode="read")
        if not safe_input.exists():
            raise FileNotFoundError(f"input PDF does not exist: {safe_input.as_posix()}")

        output_name = f"{safe_input.stem}{output_suffix}"
        safe_output = service._validate_file_path((safe_output_dir / output_name).as_posix(), mode="write")

        lines, di_meta = parse_pdf_with_document_intelligence(
            input_pdf=safe_input,
            endpoint=resolved_endpoint,
            key=resolved_key,
            auth_mode=resolved_auth_mode,
            model_id=model_id,
        )
        raw_rows, parse_stats = build_records_from_lines(lines=lines, include_review=include_review)
        output_rows = filter_rows(
            rows=raw_rows,
            profile=profile,
            provider=provider or "",
            resource_type=resource_type or "",
            include_review=include_review,
        )
        write_csv(safe_output, output_rows)

        extracted_rows = len(output_rows)
        total_extracted_rows += extracted_rows
        total_input_files += 1
        results.append(
            {
                "status": "ok",
                "input_pdf": safe_input.as_posix(),
                "output_file": safe_output.as_posix(),
                "total_rows": len(raw_rows),
                "extracted_rows": extracted_rows,
                "di_meta": di_meta,
                "parse_stats": parse_stats,
            }
        )

    return {
        "status": "ok",
        "profile": profile,
        "auth_mode": resolved_auth_mode,
        "files": results,
        "summary": {
            "input_files": total_input_files,
            "output_files": len(results),
            "extracted_rows": total_extracted_rows,
        },
        "required_for_next_skill": PROFILE_REQUIRED[profile],
        "recommended_columns": PROFILE_RECOMMENDED[profile],
    }


@mcp.tool(
    name="validate_di_connection",
    description=(
        "Validate Azure Document Intelligence credentials and connectivity. "
        "Optionally provide probe_input_pdf for end-to-end validation using real document parsing."
    ),
)
def validate_di_connection(
    endpoint: str | None = None,
    key: str | None = None,
    env_file: str = ".env",
    auth_mode: str = "auto",
    subscription_id: str | None = None,
    resource_group: str | None = None,
    account_name: str | None = None,
    model_id: str = "prebuilt-layout",
    probe_input_pdf: str | None = None,
) -> dict[str, Any]:
    safe_env = service._validate_project_file_path(env_file)
    safe_probe: Path | None = None
    if probe_input_pdf:
        safe_probe = service._validate_file_path(probe_input_pdf, mode="read")
        if not safe_probe.exists():
            raise FileNotFoundError(f"probe_input_pdf does not exist: {safe_probe.as_posix()}")

    resolved_endpoint, resolved_auth_mode, resolved_key = load_di_settings(
        endpoint=endpoint,
        key=key,
        auth_mode=auth_mode,
        env_file=safe_env,
        subscription_id=subscription_id,
        resource_group=resource_group,
        account_name=account_name,
    )

    result = validate_di_connection_core(
        endpoint=resolved_endpoint,
        key=resolved_key,
        auth_mode=resolved_auth_mode,
        model_id=model_id,
        probe_pdf=safe_probe,
    )
    result["auth_mode"] = resolved_auth_mode
    result["endpoint"] = resolved_endpoint
    return result


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
