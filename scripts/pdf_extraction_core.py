from __future__ import annotations

import csv
import importlib
import json
import os
import re
import subprocess
import unicodedata
from pathlib import Path
from typing import Any

AWS_INSTANCE_RE = re.compile(r"\b([a-z][a-z0-9]*\d+[a-z0-9]*\.[a-z0-9]+)\b", re.IGNORECASE)

REGION_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bus\s*west\b|\boregon\b", re.IGNORECASE), "Oregon"),
    (re.compile(r"\btokyo\b|\basia\s*pacific\s*\(\s*tokyo\s*\)", re.IGNORECASE), "Tokyo"),
    (re.compile(r"\bsydney\b|\basia\s*pacific\s*\(\s*sydney\s*\)", re.IGNORECASE), "Sydney"),
    (re.compile(r"\bfrankfurt\b|\beu\s*\(\s*frankfurt\s*\)", re.IGNORECASE), "Frankfurt"),
    (re.compile(r"\btel\s*aviv\b|\bisrael\s*\(\s*tel\s*aviv\s*\)", re.IGNORECASE), "Tel Aviv"),
    (re.compile(r"\bsingapore\b", re.IGNORECASE), "Singapore"),
    (re.compile(r"\bseoul\b", re.IGNORECASE), "Seoul"),
    (re.compile(r"\bmumbai\b", re.IGNORECASE), "Mumbai"),
    (re.compile(r"\bmelbourne\b", re.IGNORECASE), "Melbourne"),
    (re.compile(r"\blondon\b", re.IGNORECASE), "London"),
    (re.compile(r"\bdublin\b", re.IGNORECASE), "Dublin"),
    (re.compile(r"\bparis\b", re.IGNORECASE), "Paris"),
    (re.compile(r"\bamsterdam\b", re.IGNORECASE), "Amsterdam"),
    (re.compile(r"\bzurich\b", re.IGNORECASE), "Zurich"),
    (re.compile(r"\bstockholm\b", re.IGNORECASE), "Stockholm"),
    (re.compile(r"\bmadrid\b", re.IGNORECASE), "Madrid"),
    (re.compile(r"\bmilan\b", re.IGNORECASE), "Milan"),
    (re.compile(r"\bvirginia\b", re.IGNORECASE), "Virginia"),
    (re.compile(r"\bohio\b", re.IGNORECASE), "Ohio"),
    (re.compile(r"\bcalifornia\b", re.IGNORECASE), "California"),
    (re.compile(r"\bcanada\b", re.IGNORECASE), "Canada"),
    (re.compile(r"\bsao\s*paulo\b", re.IGNORECASE), "Sao Paulo"),
    (re.compile(r"\bhong\s*kong\b", re.IGNORECASE), "Hong Kong"),
    (re.compile(r"\bbeijing\b", re.IGNORECASE), "Beijing"),
    (re.compile(r"\bshanghai\b", re.IGNORECASE), "Shanghai"),
    (re.compile(r"\beast\s*us\b", re.IGNORECASE), "East US"),
    (re.compile(r"\bwest\s*us\b", re.IGNORECASE), "West US"),
    (re.compile(r"\bcentral\s*us\b", re.IGNORECASE), "Central US"),
    (re.compile(r"\bsoutheast\s*asia\b", re.IGNORECASE), "Southeast Asia"),
    (re.compile(r"\beast\s*asia\b", re.IGNORECASE), "East Asia"),
    (re.compile(r"\bjapan\s*east\b", re.IGNORECASE), "Japan East"),
    (re.compile(r"\bjapan\s*west\b", re.IGNORECASE), "Japan West"),
]

VM_LINE_INCLUDE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "on_demand_instance_hour",
        re.compile(r"\bon\s*demand\b.*\binstance\s*hour\b|\binstance\s*hour\b.*\bon\s*demand\b", re.IGNORECASE),
    ),
    (
        "reserved_instance_hour",
        re.compile(
            r"\breserved\s*instance\b|\bri\b|\b(1|3)\s*year\b.*\bupfront\b|\bupfront\b.*\b(1|3)\s*year\b",
            re.IGNORECASE,
        ),
    ),
]

VM_LINE_EXCLUDE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("savings_plan_covered", re.compile(r"\bcovered\s*by\s*compute\s*savings\s*plans?\b", re.IGNORECASE)),
    ("savings_plan_charge", re.compile(r"\bsavings\s*plans?\b", re.IGNORECASE)),
    ("rds_not_ec2", re.compile(r"\brds\b|\brelational\s*database\s*service\b", re.IGNORECASE)),
    ("bandwidth_charge", re.compile(r"\bmbps\b|\bgbps\b", re.IGNORECASE)),
    ("storage_charge", re.compile(r"\bebs\b|\bgp2\b|\bgp3\b|\bsnapshot\b|\biops\b|\bgb\s*-?\s*month\b", re.IGNORECASE)),
    (
        "network_lb_charge",
        re.compile(r"\blcu\b|\bload\s*balancer\b|\bloadbalancer\b|\bnat\s*gateway\b|\bdata\s*processed\b", re.IGNORECASE),
    ),
    ("non_vm_service", re.compile(r"\bkinesis\b|\banalytics\b", re.IGNORECASE)),
    ("zero_price_line", re.compile(r"\$\s*0(?:\.0+)?\s*(?:per\b|$)", re.IGNORECASE)),
]


def load_dotenv_vars(env_file: Path) -> dict[str, str]:
    if not env_file.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def discover_di_endpoint_via_az(
    *,
    subscription_id: str | None,
    resource_group: str | None,
    account_name: str | None,
) -> str | None:
    command = ["az", "cognitiveservices", "account", "list", "-o", "json"]
    if subscription_id:
        command.extend(["--subscription", subscription_id])

    try:
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return None

    if proc.returncode != 0:
        return None

    try:
        payload = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return None

    if not isinstance(payload, list):
        return None

    candidates: list[str] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        if kind not in {"formrecognizer", "documentintelligence"}:
            continue

        rg = str(item.get("resourceGroup") or "").strip().lower()
        name = str(item.get("name") or "").strip().lower()

        if resource_group and rg != resource_group.strip().lower():
            continue
        if account_name and name != account_name.strip().lower():
            continue

        props = item.get("properties") or {}
        endpoint = str(props.get("endpoint") or "").strip()
        if endpoint:
            candidates.append(endpoint)

    unique_candidates = sorted(set(candidates))
    if len(unique_candidates) == 1:
        return unique_candidates[0]

    return None


def resolve_di_config(
    *,
    endpoint: str | None,
    key: str | None,
    auth_mode: str,
    subscription_id: str | None,
    resource_group: str | None,
    account_name: str | None,
) -> tuple[str, str, str | None]:
    normalized_auth = (auth_mode or "auto").strip().lower()
    if normalized_auth not in {"auto", "key", "aad"}:
        raise ValueError("Invalid auth mode. Expected one of: auto, key, aad")

    resolved_auth_mode = normalized_auth
    if normalized_auth == "auto":
        resolved_auth_mode = "key" if (endpoint and key) else "aad"

    if resolved_auth_mode == "key" and not key:
        raise ValueError(
            "Document Intelligence API key required for key auth. Provide key or switch to auth_mode='aad'."
        )

    resolved_endpoint = endpoint
    if not resolved_endpoint and resolved_auth_mode == "aad":
        resolved_endpoint = discover_di_endpoint_via_az(
            subscription_id=subscription_id,
            resource_group=resource_group,
            account_name=account_name,
        )

    if not resolved_endpoint:
        raise ValueError(
            "Document Intelligence endpoint required. Provide endpoint or ensure one DI account is discoverable via az cli."
        )

    return resolved_endpoint, resolved_auth_mode, key


def normalize_text(value: Any) -> str:
    return str(value or "").strip().lower()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    if not rows:
        with path.open("w", encoding="utf-8", newline="") as fp:
            fp.write("")
        return

    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)

    with path.open("w", encoding="utf-8", newline="") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def normalize_os_name(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None

    lowered = raw.lower()
    if "windows" in lowered:
        return "windows"

    linux_keywords = (
        "linux",
        "unix",
        "ubuntu",
        "debian",
        "centos",
        "suse",
        "sles",
        "opensuse",
        "rhel",
        "red hat",
        "rocky",
        "alma",
        "amazon linux",
        "oracle linux",
        "fedora",
    )
    if any(keyword in lowered for keyword in linux_keywords):
        return "linux"
    return None


def detect_os_from_line(line: str) -> str | None:
    return normalize_os_name(line)


def detect_quantity_from_line(line: str) -> float | None:
    patterns = [
        r"(?:qty|quantity|count|instances?)\s*[:=]?\s*(\d+(?:\.\d+)?)",
        r"\b(\d+(?:\.\d+)?)\s*(?:x|units?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, line, flags=re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except (TypeError, ValueError):
                return None
    return None


def normalize_search_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = normalized.replace("\u00a0", " ")
    normalized = normalized.replace("\u2013", "-").replace("\u2014", "-")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def detect_region_hint(text: str) -> str | None:
    normalized = normalize_search_text(text)
    for pattern, canonical in REGION_PATTERNS:
        if pattern.search(normalized):
            return canonical
    return None


def is_likely_instance_type(token: str) -> bool:
    lower = token.lower()
    if lower.startswith("usd"):
        return False
    if lower.startswith("db."):
        return False
    return True


def classify_vm_billing_line(line: str) -> tuple[bool, str]:
    normalized = normalize_search_text(line)

    for reason, pattern in VM_LINE_EXCLUDE_PATTERNS:
        if pattern.search(normalized):
            return False, reason

    for reason, pattern in VM_LINE_INCLUDE_PATTERNS:
        if pattern.search(normalized):
            return True, reason

    return False, "missing_vm_price_signal"


def _build_di_client(endpoint: str, key: str | None, auth_mode: str) -> Any:
    try:
        di_module = importlib.import_module("azure.ai.documentintelligence")
        azure_core_module = importlib.import_module("azure.core.credentials")
    except ImportError as exc:
        raise ImportError(
            "Missing dependency `azure-ai-documentintelligence`. Install with: pip install azure-ai-documentintelligence"
        ) from exc

    DocumentIntelligenceClient = getattr(di_module, "DocumentIntelligenceClient")
    AzureKeyCredential = getattr(azure_core_module, "AzureKeyCredential")

    if auth_mode == "aad":
        try:
            azure_identity_module = importlib.import_module("azure.identity")
        except ImportError as exc:
            raise ImportError(
                "Missing dependency `azure-identity` for AAD auth. Install with: pip install azure-identity"
            ) from exc
        DefaultAzureCredential = getattr(azure_identity_module, "DefaultAzureCredential")
        return DocumentIntelligenceClient(endpoint=endpoint, credential=DefaultAzureCredential())

    if not key:
        raise ValueError("Document Intelligence API key is required when auth_mode='key'")
    return DocumentIntelligenceClient(endpoint=endpoint, credential=AzureKeyCredential(key))


def parse_pdf_with_document_intelligence(
    input_pdf: Path,
    endpoint: str,
    key: str | None,
    auth_mode: str,
    model_id: str,
) -> tuple[list[str], dict[str, Any]]:
    try:
        di_models_module = importlib.import_module("azure.ai.documentintelligence.models")
    except ImportError as exc:
        raise ImportError(
            "Missing dependency `azure-ai-documentintelligence`. Install with: pip install azure-ai-documentintelligence"
        ) from exc

    AnalyzeDocumentRequest = getattr(di_models_module, "AnalyzeDocumentRequest")
    client = _build_di_client(endpoint=endpoint, key=key, auth_mode=auth_mode)

    with input_pdf.open("rb") as fp:
        poller = client.begin_analyze_document(
            model_id=model_id,
            body=AnalyzeDocumentRequest(bytes_source=fp.read()),
        )
    result = poller.result()

    lines: list[str] = []
    for page in (result.pages or []):
        for line in (page.lines or []):
            text = str(getattr(line, "content", "") or "").strip()
            if text:
                lines.append(text)

    if not lines and getattr(result, "content", None):
        lines = [segment.strip() for segment in str(result.content).splitlines() if segment.strip()]

    meta = {
        "model_id": model_id,
        "pages": len(result.pages or []),
        "detected_languages": [
            {"locale": lang.locale, "confidence": lang.confidence} for lang in (result.languages or [])
        ],
    }
    return lines, meta


def validate_di_connection(
    *,
    endpoint: str,
    key: str | None,
    auth_mode: str,
    model_id: str,
    probe_pdf: Path | None,
) -> dict[str, Any]:
    _ = model_id
    _build_di_client(endpoint=endpoint, key=key, auth_mode=auth_mode)

    if probe_pdf is None:
        return {
            "status": "ok",
            "mode": "client_init_only",
            "message": "DI client initialized; pass probe_pdf for end-to-end validation.",
        }

    lines, di_meta = parse_pdf_with_document_intelligence(
        input_pdf=probe_pdf,
        endpoint=endpoint,
        key=key,
        auth_mode=auth_mode,
        model_id=model_id,
    )
    return {
        "status": "ok",
        "mode": "end_to_end",
        "probe_pdf": probe_pdf.as_posix(),
        "lines": len(lines),
        "di_meta": di_meta,
    }


def build_records_from_lines(lines: list[str], include_review: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_text = "\n".join(lines)
    doc_region = detect_region_hint(all_text)
    doc_os = normalize_os_name(all_text)

    records: list[dict[str, Any]] = []
    unmatched_lines = 0
    current_region: str | None = None
    excluded_lines_by_reason: dict[str, int] = {}

    for line in lines:
        line_region = detect_region_hint(line)
        if line_region:
            current_region = line_region

        matches = list(AWS_INSTANCE_RE.finditer(line))
        if not matches:
            unmatched_lines += 1
            continue

        is_vm_line, line_reason = classify_vm_billing_line(line)
        if not is_vm_line:
            excluded_lines_by_reason[line_reason] = excluded_lines_by_reason.get(line_reason, 0) + 1
            continue

        row_os = detect_os_from_line(line) or doc_os
        row_qty = detect_quantity_from_line(line)
        row_region = line_region or current_region or doc_region

        for match in matches:
            instance_type = match.group(1)
            if not is_likely_instance_type(instance_type):
                continue
            row_id = len(records) + 1
            records.append(
                {
                    "nrm_id": f"row-{row_id}",
                    "provider": "aws",
                    "resource_type": "vm",
                    "instance_name": instance_type,
                    "quantity": row_qty if row_qty is not None else 1.0,
                    "vcpu": None,
                    "memory_gb": None,
                    "os": row_os,
                    "region_input": row_region,
                    "region_aws": None,
                    "region_azure": None,
                    "workload": None,
                    "status": "ok",
                    "status_reason": None,
                    "instance_type": instance_type,
                    "match_reason": line_reason,
                    "source_line": line,
                }
            )

    if not records and include_review:
        preview = " | ".join(lines[:3])
        records.append(
            {
                "nrm_id": "row-1",
                "provider": "",
                "resource_type": "",
                "instance_name": "",
                "quantity": None,
                "vcpu": None,
                "memory_gb": None,
                "os": doc_os,
                "region_input": doc_region,
                "region_aws": None,
                "region_azure": None,
                "workload": None,
                "status": "review",
                "status_reason": "no_aws_instance_type_detected",
                "instance_type": "",
                "source_line": preview,
            }
        )

    stats = {
        "source_lines": len(lines),
        "unmatched_lines": unmatched_lines,
        "excluded_lines": int(sum(excluded_lines_by_reason.values())),
        "excluded_lines_by_reason": excluded_lines_by_reason,
        "detected_rows": len(records),
        "document_region_hint": doc_region,
        "document_os_hint": doc_os,
        "regions_detected": sorted({str(row.get("region_input") or "") for row in records if row.get("region_input")}),
    }
    return records, stats


def filter_rows(
    rows: list[dict[str, Any]],
    profile: str,
    provider: str,
    resource_type: str,
    include_review: bool,
) -> list[dict[str, Any]]:
    output_rows: list[dict[str, Any]] = []

    provider_norm = normalize_text(provider)
    resource_norm = normalize_text(resource_type)

    for row in rows:
        if provider_norm and normalize_text(row.get("provider")) != provider_norm:
            continue
        if resource_norm and normalize_text(row.get("resource_type")) != resource_norm:
            continue
        if not include_review and normalize_text(row.get("status")) != "ok":
            continue

        if profile == "aws_vm":
            if normalize_text(row.get("provider")) != "aws":
                continue
            if normalize_text(row.get("resource_type")) != "vm":
                continue
            if not str(row.get("instance_type") or "").strip():
                continue

        output_rows.append(row)

    return output_rows


def load_di_settings(
    *,
    endpoint: str | None,
    key: str | None,
    auth_mode: str,
    env_file: Path | None,
    subscription_id: str | None,
    resource_group: str | None,
    account_name: str | None,
) -> tuple[str, str, str | None]:
    dotenv_vars: dict[str, str] = {}
    if env_file is not None:
        dotenv_vars = load_dotenv_vars(env_file)

    merged_endpoint = endpoint or dotenv_vars.get("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT") or os.getenv(
        "AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT"
    )
    merged_key = key or dotenv_vars.get("AZURE_DOCUMENT_INTELLIGENCE_KEY") or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")

    env_auth_mode = (
        dotenv_vars.get("AZURE_DOCUMENT_INTELLIGENCE_AUTH_MODE")
        or os.getenv("AZURE_DOCUMENT_INTELLIGENCE_AUTH_MODE")
        or auth_mode
    )

    return resolve_di_config(
        endpoint=merged_endpoint,
        key=merged_key,
        auth_mode=env_auth_mode,
        subscription_id=subscription_id,
        resource_group=resource_group,
        account_name=account_name,
    )
