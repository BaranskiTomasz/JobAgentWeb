"""Stable source identities and conservative matching aliases."""

from __future__ import annotations

from dataclasses import dataclass
import html
import re
import unicodedata
from urllib.parse import unquote, urlparse


_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w+#./-]+", re.UNICODE)
_ATS_ID_RE = re.compile(r"(?i)(?:jobs?|postings?|positions?|opening|requisitions?)[/_-]([a-z0-9][a-z0-9_-]{2,})")
_HEX_UUID_RE = re.compile(r"(?i)\b[0-9a-f]{8}-[0-9a-f-]{27,}\b")
_NUMERIC_RE = re.compile(r"^\d{3,}$")


def normalize_identifier(value: object | None) -> str:
    if value is None:
        return ""
    text = unicodedata.normalize("NFKC", html.unescape(str(value))).casefold().strip()
    return _SPACE_RE.sub(" ", text)


def _fold_text(value: object | None) -> str:
    text = normalize_identifier(value).translate(str.maketrans({"ł": "l", "ø": "o"}))
    return "".join(
        char for char in unicodedata.normalize("NFKD", text)
        if not unicodedata.combining(char)
    )


def _slug(value: object | None) -> str:
    text = normalize_identifier(value)
    text = re.sub(r"[^a-z0-9]+", "-", unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode())
    return text.strip("-")


def company_alias(value: object | None) -> str:
    text = _fold_text(value)
    text = re.sub(r"[&+]", " and ", text)
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    text = _SPACE_RE.sub(" ", text).strip()
    suffix = r"(?:incorporated|inc|corp(?:oration)?|ltd|limited|llc|plc|gmbh|sa|sp z o o)"
    text = re.sub(rf"(?:\s+|^)({suffix})$", "", text, flags=re.IGNORECASE).strip()
    return text


def title_alias(value: object | None) -> str:
    text = _fold_text(value)
    text = text.replace("&", " and ")
    text = re.sub(r"[\-/|(),.:]+", " ", text)
    text = re.sub(r"\bsr\.?\b", "senior", text)
    text = re.sub(r"\bjr\.?\b", "junior", text)
    text = re.sub(r"\bsoft[- ]?ware\b", "software", text)
    text = _SPACE_RE.sub(" ", text).strip()
    return text


def title_aliases(value: object | None) -> set[str]:
    canonical = title_alias(value)
    if not canonical:
        return set()
    aliases = {canonical}
    parts = canonical.split()
    if len(parts) > 2 and parts[-1] in {"engineer", "developer", "analyst", "designer", "manager"}:
        aliases.add(" ".join(parts[-1:] + parts[:-1]))
    return aliases


def _url_requisition_id(url: object | None) -> str:
    if not url:
        return ""
    parsed = urlparse(str(url))
    path = unquote(parsed.path).strip("/")
    match = _ATS_ID_RE.search(path)
    if match and normalize_identifier(match.group(1)) not in {"view", "search", "list", "all"}:
        return normalize_identifier(match.group(1))
    match = _HEX_UUID_RE.search(path)
    if match:
        return normalize_identifier(match.group(0))
    return ""


@dataclass(frozen=True)
class SourceIdentity:
    provider: str
    requisition_id: str
    key: str
    company_key: str
    title_key: str


def requisition_identity(job: dict) -> SourceIdentity | None:
    provider = _slug(job.get("source") or job.get("provider"))
    raw_id = job.get("source_id") or job.get("requisition_id")
    requisition_id = normalize_identifier(raw_id)
    if not requisition_id or requisition_id in {"none", "null", "-"}:
        requisition_id = _url_requisition_id(job.get("url"))
    if not provider or not requisition_id:
        return None
    requisition_id = re.sub(r"\s+", "", requisition_id)
    return SourceIdentity(
        provider=provider,
        requisition_id=requisition_id,
        key=f"{provider}:{requisition_id}",
        company_key=company_alias(job.get("company")),
        title_key=title_alias(job.get("title")),
    )


def source_identity(job: dict) -> str | None:
    identity = requisition_identity(job)
    return identity.key if identity else None


def identity_aliases(job: dict) -> dict[str, object]:
    identity = requisition_identity(job)
    return {
        "source_identity": identity.key if identity else None,
        "provider": identity.provider if identity else None,
        "requisition_id": identity.requisition_id if identity else None,
        "company_alias": company_alias(job.get("company")),
        "title_aliases": sorted(title_aliases(job.get("title"))),
    }
