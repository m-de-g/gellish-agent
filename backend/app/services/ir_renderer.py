from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import re
from typing import Any
import unicodedata


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


def _slugify_ascii(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return slug or "concept"


def _entity_id_to_provisional_uid(entity_id: str) -> str:
    suffix = entity_id.split(":", maxsplit=1)[-1]
    return f"provisional:{_slugify_ascii(suffix)}"


def _resolve_entity_uid(entity: dict[str, Any] | None, entity_id: str | None) -> str | None:
    if entity:
        chosen_uid = entity.get("chosen_uid")
        if isinstance(chosen_uid, str) and chosen_uid.strip():
            return chosen_uid.strip()
        existing_uid = entity.get("uid")
        if isinstance(existing_uid, str) and existing_uid.strip():
            return existing_uid.strip()
    if isinstance(entity_id, str) and entity_id.strip():
        return _entity_id_to_provisional_uid(entity_id.strip())
    return None


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

    entities_by_id: dict[str, dict[str, Any]] = {}
    for entity in ir_obj.get("entities", []):
        if not isinstance(entity, dict):
            continue
        entity_id = entity.get("entity_id")
        if isinstance(entity_id, str) and entity_id.strip():
            entities_by_id[entity_id.strip()] = entity
    rendered: list[ExpressionCreate] = []
    for idx, relation in enumerate(ir_obj.get("relations", [])):
        if not isinstance(relation, dict):
            continue

        source_entity_id = relation.get("source_entity_id")
        target_entity_id = relation.get("target_entity_id")

        source_entity = (
            entities_by_id.get(source_entity_id.strip())
            if isinstance(source_entity_id, str)
            else None
        )
        target_entity = (
            entities_by_id.get(target_entity_id.strip())
            if isinstance(target_entity_id, str)
            else None
        )

        # --- SUBJECT ---
        subject_uid = relation.get("subject_uid")
        if isinstance(subject_uid, str):
            subject_uid = subject_uid.strip()
        else:
            subject_uid = ""

        if not subject_uid:
            subject_uid = _resolve_entity_uid(
                source_entity,
                source_entity_id.strip() if isinstance(source_entity_id, str) else None,
            )
        subject_uid = subject_uid or None

        # --- OBJECT ---
        object_uid = relation.get("object_uid")
        if isinstance(object_uid, str):
            object_uid = object_uid.strip()
        else:
            object_uid = ""

        object_literal = relation.get("object_literal")

        if not object_uid:
            object_uid = _resolve_entity_uid(
                target_entity,
                target_entity_id.strip() if isinstance(target_entity_id, str) else None,
            )
        object_uid = object_uid or None

        # If we have an object UID, we must not also set a literal.
        if object_uid:
            object_literal = None

        # --- RELATION UID ---
        relation_uid = relation.get("relation_uid")
        if isinstance(relation_uid, str):
            relation_uid = relation_uid.strip()
        else:
            relation_uid = ""
        if not relation_uid:
            relation_uid = "rel:unknown"

        # --- GUARDS: skip malformed expressions instead of inventing placeholders ---
        if subject_uid is None:
            # Cannot render an expression without a subject
            continue
        if object_uid is None and object_literal is None:
            # Must have either object_uid or object_literal
            continue

        rendered.append(
            ExpressionCreate(
                translation_run_id=translation_run_id,
                sentence_id=sentence_id,
                relation_index=idx,
                subject_uid=subject_uid,
                relation_uid=relation_uid,
                object_uid=object_uid or None,
                object_literal=object_literal,
                qualifiers_json=deepcopy(relation.get("qualifiers")),
                provenance_json=deepcopy(base_provenance),
                confidence=relation.get("confidence"),
                status="proposed",
            )
        )

    return rendered
