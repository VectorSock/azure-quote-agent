from __future__ import annotations

import re
import unicodedata
from typing import Any

CORE_SUITE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("s4", re.compile(r"\bs\s*/?\s*4\s*hana\b|\bs\s*/?\s*4\b|\bs4\b|\bs4hana\b|\bhanadb\b", re.IGNORECASE)),
    ("bw", re.compile(r"\bsap\s*bw\b|\bbw\s*/?\s*4\b|\bbw4\b|\bbusiness\s*warehouse\b|\bbw\b", re.IGNORECASE)),
    ("po", re.compile(r"\bsap\s*po\b|\bprocess\s*orchestration\b|\bprocess\s*integration\b|\bpi\s*/\s*po\b|\bpo\b", re.IGNORECASE)),
]

SAP_APP_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("fiori", re.compile(r"\bfiori\b", re.IGNORECASE)),
    ("solman", re.compile(r"\bsolman\b|\bsolution\s*manager\b", re.IGNORECASE)),
    ("bo", re.compile(r"\bbo\b|\bbusiness\s*object(s)?\b|\bbusinessobjects\b", re.IGNORECASE)),
    ("g4", re.compile(r"\bg4\b", re.IGNORECASE)),
    ("oa", re.compile(r"\boa\b", re.IGNORECASE)),
]

SAP_ECOSYSTEM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("opentext", re.compile(r"\bopentext\b|\botcs\b", re.IGNORECASE)),
    ("wb", re.compile(r"\bwb\b", re.IGNORECASE)),
    ("soterien", re.compile(r"\bsoterien\b", re.IGNORECASE)),
]

NON_SAP_INFRA_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("zabbix", re.compile(r"\bzabbix\b|监控", re.IGNORECASE)),
    ("jumpbox", re.compile(r"\bjump\s*box\b|\bbastion\b|\bjumpbox\b|跳板机", re.IGNORECASE)),
    ("efs_sync_agent", re.compile(r"\befs\b.*\b(sync|agent|proxy)\b|同步.*代理|传输.*代理", re.IGNORECASE)),
]

SAP_HINT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("sap", re.compile(r"\bsap\b", re.IGNORECASE)),
    ("netweaver", re.compile(r"\bnetweaver\b", re.IGNORECASE)),
    ("abap", re.compile(r"\babap\b", re.IGNORECASE)),
    ("hana", re.compile(r"\bhana\b", re.IGNORECASE)),
]

DB_ROLE_PATTERN = re.compile(r"\bdb\b|\bdatabase\b|\bhana\b|\banydb\b|\bora(cle)?\b|\bmssql\b|\bpostgres\b", re.IGNORECASE)
APP_ROLE_PATTERN = re.compile(r"\bapp\b|\bapplication\b|\bnetweaver\b|\bjava\b|\babap\b|\bfiori\b", re.IGNORECASE)

ENV_PATTERNS: dict[str, re.Pattern[str]] = {
    "dev": re.compile(r"\bdev(elop(ment)?)?\b", re.IGNORECASE),
    "qas": re.compile(r"\bqas\b|\bqa\b|\btest\b|\bsit\b|\buat\b|\breg(re(ssion)?)?\b", re.IGNORECASE),
    "prd": re.compile(r"\bprd\b|\bprod(uction)?\b|\blive\b", re.IGNORECASE),
}


def normalize_text(value: Any) -> str:
    text = str(value or "")
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("_", " ").replace("/", " ").replace("-", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


def parse_bool_or_none(value: Any) -> bool | None:
    if value is None:
        return None
    token = str(value).strip().lower()
    if token in {"", "none", "null", "nan", "n/a", "na", "tbd", "pending"}:
        return None
    if token in {"1", "true", "yes", "y", "on"}:
        return True
    if token in {"0", "false", "no", "n", "off"}:
        return False
    return None


def detect_role(text: str) -> str:
    has_db = bool(DB_ROLE_PATTERN.search(text))
    has_app = bool(APP_ROLE_PATTERN.search(text))
    if has_db and has_app:
        return "app+db"
    if has_db:
        return "db"
    if has_app:
        return "app"
    return "unknown"


def normalize_env(env: str) -> str:
    for key, pattern in ENV_PATTERNS.items():
        if pattern.search(env):
            return key
    return "unknown"


def find_matches(text: str, rules: list[tuple[str, re.Pattern[str]]]) -> list[str]:
    matched: list[str] = []
    for key, pattern in rules:
        if pattern.search(text):
            matched.append(key)
    return matched


def infer_sap_workload(system: Any, env: Any, workload_type: Any, workload: Any = None) -> dict[str, Any]:
    system_text = normalize_text(system)
    env_text = normalize_text(env)
    workload_text = normalize_text(workload_type)
    workload_extra = normalize_text(workload)

    merged_text = " | ".join(part for part in [system_text, env_text, workload_text, workload_extra] if part)
    role = detect_role(merged_text)
    env_norm = normalize_env(env_text)

    core_hits = find_matches(merged_text, CORE_SUITE_PATTERNS)
    sap_app_hits = find_matches(merged_text, SAP_APP_PATTERNS)
    sap_ecosystem_hits = find_matches(merged_text, SAP_ECOSYSTEM_PATTERNS)
    non_sap_hits = find_matches(merged_text, NON_SAP_INFRA_PATTERNS)
    sap_hints = find_matches(merged_text, SAP_HINT_PATTERNS)

    score = 0
    reasons: list[str] = []
    category = "unknown"
    subtype = ""

    if non_sap_hits:
        score -= 4
        reasons.append(f"non_sap_indicator:{'|'.join(non_sap_hits)}")

    if core_hits:
        score += 5
        category = "sap_core_suite"
        subtype = core_hits[0]
        reasons.append(f"core_suite:{'|'.join(core_hits)}")

    if sap_app_hits and category == "unknown":
        score += 3
        category = "sap_application"
        subtype = sap_app_hits[0]
        reasons.append(f"sap_app:{'|'.join(sap_app_hits)}")

    if sap_ecosystem_hits and category == "unknown":
        score += 2
        category = "sap_ecosystem"
        subtype = sap_ecosystem_hits[0]
        reasons.append(f"sap_ecosystem:{'|'.join(sap_ecosystem_hits)}")

    if sap_hints:
        score += 1
        reasons.append(f"sap_hint:{'|'.join(sap_hints)}")

    if role == "db" and category in {"sap_core_suite", "sap_ecosystem"}:
        score += 1
        reasons.append("role:db")
    elif role in {"app", "app+db"} and category in {"sap_core_suite", "sap_application", "sap_ecosystem"}:
        score += 1
        reasons.append(f"role:{role}")

    if env_norm in {"dev", "qas", "prd"} and category.startswith("sap_"):
        reasons.append(f"env:{env_norm}")

    is_sap = score >= 2

    if category == "unknown" and not is_sap and non_sap_hits:
        category = "non_sap_infra"

    confidence = "low"
    if is_sap and category == "sap_core_suite":
        confidence = "high"
    elif is_sap and category in {"sap_application", "sap_ecosystem"}:
        confidence = "medium"
    elif not is_sap and category == "non_sap_infra":
        confidence = "high"

    return {
        "is_sap_workload": is_sap,
        "confidence": confidence,
        "category": category,
        "subtype": subtype or None,
        "role": role,
        "env_normalized": env_norm,
        "score": score,
        "reasons": reasons,
        "input": {
            "system": str(system or ""),
            "env": str(env or ""),
            "workload_type": str(workload_type or ""),
            "workload": str(workload or ""),
        },
    }
