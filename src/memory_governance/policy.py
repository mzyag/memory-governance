"""Policy engine — loads YAML policy and evaluates access/retention rules."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CATEGORIES = ("project", "area", "feedback", "resource")

RETENTION_DEFAULTS: dict[str, int | None] = {
    "project": 365,
    "area": None,
    "feedback": None,
    "resource": None,
}

ACCESS_DEFAULTS: dict[str, dict[str, list[str]]] = {
    "default": {
        "read": list(DEFAULT_CATEGORIES),
        "write": ["project"],
    },
}

PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("email", re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")),
    ("phone", re.compile(r"(?<!\d)(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}(?!\d)")),
    ("bearer_token", re.compile(r"(?i)(Bearer\s+)\S+")),
    ("api_key", re.compile(r"(?i)((?:token|api_key|password|secret|apikey|api-key)[\s=:]+)\S+")),
    ("url", re.compile(r"https?://[^\s]+")),
]


@dataclass
class RetentionPolicy:
    max_age_days: int | None = None
    archive_after_days: int = 30
    episode_cap: int = 10


@dataclass
class AccessRule:
    read: list[str] = field(default_factory=lambda: list(DEFAULT_CATEGORIES))
    write: list[str] = field(default_factory=lambda: ["project"])


@dataclass
class PiiPolicy:
    enabled: bool = True
    redact_emails: bool = True
    redact_phones: bool = True
    redact_tokens: bool = True
    redact_urls: bool = False


@dataclass
class Policy:
    retention: dict[str, RetentionPolicy] = field(default_factory=dict)
    access: dict[str, AccessRule] = field(default_factory=dict)
    pii: PiiPolicy = field(default_factory=PiiPolicy)
    audit_retention_days: int = 2555  # ~7 years

    def can_read(self, role: str, category: str) -> bool:
        rule = self.access.get(role, self.access.get("default"))
        if rule is None:
            return False
        return category in rule.read

    def can_write(self, role: str, category: str) -> bool:
        rule = self.access.get(role, self.access.get("default"))
        if rule is None:
            return False
        return category in rule.write

    def get_retention(self, category: str) -> RetentionPolicy:
        return self.retention.get(category, RetentionPolicy())

    def redact_pii(self, text: str) -> tuple[str, list[str]]:
        if not self.pii.enabled:
            return text, []
        detections: list[str] = []
        result = text
        if self.pii.redact_emails:
            found = PII_PATTERNS[0][1].findall(result)
            if found:
                detections.extend(f"email:{f}" for f in found)
                result = PII_PATTERNS[0][1].sub("[REDACTED:email]", result)
        if self.pii.redact_phones:
            found = PII_PATTERNS[1][1].findall(result)
            if found:
                detections.extend(f"phone:{f}" for f in found)
                result = PII_PATTERNS[1][1].sub("[REDACTED:phone]", result)
        if self.pii.redact_tokens:
            result = PII_PATTERNS[2][1].sub(r"\1[REDACTED]", result)
            result = PII_PATTERNS[3][1].sub(r"\1[REDACTED]", result)
            if result != text and "token" not in str(detections):
                detections.append("token_or_secret")
        if self.pii.redact_urls:
            result = PII_PATTERNS[4][1].sub("[REDACTED:url]", result)
        return result, detections


def load_policy(path: Path | str) -> Policy:
    path = Path(path)
    if not path.exists():
        return _default_policy()
    raw = yaml.safe_load(path.read_text("utf-8")) or {}
    return _parse_policy(raw)


def _default_policy() -> Policy:
    return Policy(
        retention={cat: RetentionPolicy() for cat in DEFAULT_CATEGORIES},
        access={"default": AccessRule()},
    )


def _parse_policy(raw: dict[str, Any]) -> Policy:
    retention: dict[str, RetentionPolicy] = {}
    for cat, conf in (raw.get("retention") or {}).items():
        if isinstance(conf, dict):
            retention[cat] = RetentionPolicy(
                max_age_days=conf.get("max_age_days"),
                archive_after_days=conf.get("archive_after_days", 30),
                episode_cap=conf.get("episode_cap", 10),
            )
    access: dict[str, AccessRule] = {}
    for role, conf in (raw.get("access", {}).get("roles") or {}).items():
        if isinstance(conf, dict):
            access[role] = AccessRule(
                read=conf.get("read", list(DEFAULT_CATEGORIES)),
                write=conf.get("write", []),
            )
    if "default" not in access:
        access["default"] = AccessRule()
    pii_raw = raw.get("pii") or {}
    pii = PiiPolicy(
        enabled=pii_raw.get("enabled", True),
        redact_emails=pii_raw.get("redact_emails", True),
        redact_phones=pii_raw.get("redact_phones", True),
        redact_tokens=pii_raw.get("redact_tokens", True),
        redact_urls=pii_raw.get("redact_urls", False),
    )
    return Policy(
        retention=retention,
        access=access,
        pii=pii,
        audit_retention_days=raw.get("audit", {}).get("retention_days", 2555),
    )
