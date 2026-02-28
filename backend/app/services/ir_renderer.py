from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExpressionCreate:
    translation_run_id: int
    sentence_id: int
    relation_index: int
    subject_uid: str
    relation_uid: str
    object_uid: str | None
    object_literal: str | None
    qualifiers_json: dict[str, Any] | None
    provenance_json: dict[str, Any]
    confidence: float | None
    status: str = "proposed"


def render_ir_to_expressions(ir_obj: dict[str, Any], provenance: dict[str, Any]) -> list[ExpressionCreate]:
    """Render one expression per relation in stable relation order."""
    translation_run_id = int(provenance["translation_run_id"])
    sentence_id = int(provenance["sentence_id"])

    base_provenance: dict[str, Any] = {
        "document_id": provenance.get("document_id"),
        "sentence_id": sentence_id,
        "translation_run_id": translation_run_id,
    }
    sentence_text = provenance.get("sentence_text")
    if sentence_text is not None:
        base_provenance["sentence_text"] = sentence_text

    rendered: list[ExpressionCreate] = []
    for idx, relation in enumerate(ir_obj.get("relations", [])):
        rendered.append(
            ExpressionCreate(
                translation_run_id=translation_run_id,
                sentence_id=sentence_id,
                relation_index=idx,
                subject_uid=relation.get("subject_uid", "provisional:subject"),
                relation_uid=relation.get("relation_uid", "rel:unknown"),
                object_uid=relation.get("object_uid"),
                object_literal=relation.get("object_literal"),
                qualifiers_json=deepcopy(relation.get("qualifiers")),
                provenance_json=deepcopy(base_provenance),
                confidence=relation.get("confidence"),
                status="proposed",
            )
        )

    return rendered
