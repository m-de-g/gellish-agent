from __future__ import annotations

import hashlib
import re
import unicodedata


def _slugify_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug or "concept"


def canonical_concept_uid(pref_label: str, definition: str | None) -> str:
    label_norm = " ".join(pref_label.strip().split()).lower()
    definition_norm = " ".join((definition or "").strip().split()).lower()
    digest = hashlib.sha256(f"{label_norm}|{definition_norm}".encode("utf-8")).hexdigest()[:10]
    slug = _slugify_ascii(label_norm)
    return f"concept:{slug}-{digest}"
