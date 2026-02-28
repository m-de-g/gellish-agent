from __future__ import annotations

import hashlib

from .base import IRProvider


class StubProvider(IRProvider):
    def generate_ir(self, sentence_text: str, context: dict) -> dict:
        sentence_id = context.get("sentence_id") or "stub:sentence"
        digest = hashlib.sha256(sentence_text.encode("utf-8")).hexdigest()[:8]
        subject_uid = f"provisional:subject:{digest}"
        object_literal = sentence_text
        return {
            "sentence_id": sentence_id,
            "text": sentence_text,
            "entities": [
                {
                    "span": [0, max(len(sentence_text), 1)],
                    "surface": sentence_text[:50] if sentence_text else "",
                    "candidate_concepts": [
                        {"uid": subject_uid, "score": 1.0}
                    ],
                    "chosen_uid": subject_uid,
                    "needs_review": False,
                }
            ],
            "relations": [
                {
                    "subject_surface": sentence_text[:50] if sentence_text else "",
                    "subject_uid": subject_uid,
                    "relation_uid": "rel:has_value",
                    "object_literal": object_literal,
                    "qualifiers": {},
                    "confidence": 1.0,
                    "needs_review": False,
                    "notes": "stub",
                }
            ],
            "open_terms": [],
        }
