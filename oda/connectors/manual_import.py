"""Manual import connector - the always-available path.

This is how real content from platforms with no usable API (TikTok, Instagram,
X, G2, Capterra) legitimately enters the system: the user exports or copies
content they are entitled to access, and the system ingests it with full
provenance. It is REAL data (data_origin='real') because a human collected it
from a real source; the import record states who supplied it and when.

Accepted shapes:
  * JSONL / JSON list of {text, url?, title?, author?, published_at?, kind?, platform?, external_id?}
  * CSV with a `text` column (other columns mapped when present)
  * Plain text, split on blank-line boundaries or a `---` separator
"""
from __future__ import annotations

import csv
import io
import json
from typing import Any, Iterable, Optional

from ..textutil import short_hash
from .base import OK, Capability, Connector, FetchResult, RawItem

FIELD_ALIASES = {
    "text": ("text", "body", "content", "comment", "review", "transcript", "message", "النص", "التعليق"),
    "url": ("url", "link", "permalink", "source_url", "الرابط"),
    "title": ("title", "headline", "subject", "العنوان"),
    "author_ref": ("author", "author_ref", "user", "username", "handle", "الكاتب"),
    "published_at": ("published_at", "date", "created_at", "timestamp", "التاريخ"),
    "kind": ("kind", "type", "content_type"),
    "external_id": ("external_id", "id", "post_id"),
    "platform": ("platform", "source", "المنصة"),
}


def _pick(d: dict, field: str) -> Optional[str]:
    lowered = {str(k).strip().lower(): v for k, v in d.items()}
    for alias in FIELD_ALIASES[field]:
        if alias in lowered and lowered[alias] not in (None, ""):
            return str(lowered[alias])
    return None


class ManualImportConnector(Connector):
    platform = "manual"
    capability = Capability(
        platform="manual",
        access_mechanism="User-supplied export / copy-paste (JSONL, JSON, CSV, plain text)",
        data_available="Whatever the user is entitled to access and chooses to supply",
        credentials_required=[],
        limits="No automation; volume bounded by what the user exports.",
        tos_notes="The user is responsible for being entitled to the content they import. "
                  "Platform text is stored as untrusted data, never executed as instructions.",
        needs_human="By definition - this path exists for human-in-the-loop collection.",
    )

    def available(self) -> tuple[bool, str]:
        return True, ""

    # `search` is not meaningful for a manual source; it is a no-op that says so.
    def search(self, query: str, limit: int = 20, **kw: Any) -> FetchResult:
        return FetchResult(access_status=OK, items=[],
                           reason="manual connector does not search; use parse()")

    # ---------------- parsing ----------------
    def parse(self, payload: str, default_platform: str = "manual",
              default_kind: str = "post", origin_label: str = "user_import") -> FetchResult:
        payload = (payload or "").strip()
        if not payload:
            return FetchResult(access_status=OK, items=[], reason="empty payload")

        records = self._to_records(payload)
        items: list[RawItem] = []
        for i, rec in enumerate(records):
            if isinstance(rec, str):
                text, meta = rec, {}
            else:
                text = _pick(rec, "text") or ""
                meta = rec
            text = text.strip()
            if not text:
                continue
            plat = (_pick(meta, "platform") if meta else None) or default_platform
            ext = (_pick(meta, "external_id") if meta else None)
            url = (_pick(meta, "url") if meta else None)
            if not ext:
                ext = f"manual:{short_hash(text + (url or ''), 20)}"
            items.append(RawItem(
                external_id=ext,
                text=text,
                kind=(_pick(meta, "kind") if meta else None) or default_kind,
                url=url,
                title=(_pick(meta, "title") if meta else None),
                author_ref=(_pick(meta, "author_ref") if meta else None),
                published_at=(_pick(meta, "published_at") if meta else None),
                extraction_method="user_supplied",
                raw_meta={"import_platform": plat, "import_index": i,
                          "origin_label": origin_label},
            ))
        return FetchResult(items=items, access_status=OK,
                           reason=f"parsed {len(items)} item(s) from {len(records)} record(s)")

    @staticmethod
    def _to_records(payload: str) -> list[Any]:
        # 1) JSON array / single object
        if payload[0] in "[{":
            try:
                obj = json.loads(payload)
                if isinstance(obj, list):
                    return obj
                if isinstance(obj, dict):
                    for key in ("items", "data", "results", "comments"):
                        if isinstance(obj.get(key), list):
                            return obj[key]
                    return [obj]
            except json.JSONDecodeError:
                pass
        # 2) JSONL
        lines = [l for l in payload.splitlines() if l.strip()]
        if lines and all(l.lstrip().startswith("{") for l in lines):
            out, ok = [], True
            for l in lines:
                try:
                    out.append(json.loads(l))
                except json.JSONDecodeError:
                    ok = False
                    break
            if ok and out:
                return out
        # 3) CSV / TSV with a header containing a recognised text column
        head = payload.splitlines()[0]
        if ("," in head or "\t" in head):
            try:
                dialect = csv.Sniffer().sniff(payload[:4096], delimiters=",\t;")
                reader = csv.DictReader(io.StringIO(payload), dialect=dialect)
                fields = [f.strip().lower() for f in (reader.fieldnames or [])]
                if any(a in fields for a in FIELD_ALIASES["text"]):
                    return [dict(r) for r in reader]
            except Exception:
                pass
        # 4) Mixed / plain-text blocks. Each block is re-tried as JSON so a
        #    paste that mixes free text with JSON records keeps its metadata.
        if "\n---" in payload:
            blocks = [b.strip() for b in payload.split("\n---") if b.strip()]
        else:
            blocks = [b.strip() for b in payload.split("\n\n") if b.strip()]
        blocks = blocks or [payload]
        out: list[Any] = []
        for b in blocks:
            b = b.strip().lstrip("-").strip()
            if not b:
                continue
            if b[0] == "{":
                try:
                    parsed = json.loads(b)
                    if isinstance(parsed, dict):
                        out.append(parsed)
                        continue
                except json.JSONDecodeError:
                    pass
            out.append(b)
        return out
