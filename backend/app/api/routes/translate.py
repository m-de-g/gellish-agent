from __future__ import annotations

import csv
import io
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...ir_validation import validate_ir
from ...models.core import Concept, Document, Expression, ReviewQueue, Sentence, SentenceIR, Term, TranslationRun
from ...providers import StubProvider
from ...services.ir_renderer import render_ir_to_expressions

router = APIRouter(tags=["translation"])


class TranslateRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    max_sentences: int | None = Field(default=None, ge=1)


class TranslateSummary(BaseModel):
    translation_run_id: int
    sentences_processed: int
    valid_count: int
    invalid_count: int


class TranslationRunOut(BaseModel):
    id: int
    document_id: int
    llm_provider: str | None
    llm_model: str | None
    params_json: dict[str, Any] | None
    created_at: Any
    sentences_processed: int
    valid_count: int
    invalid_count: int


class ExpressionOut(BaseModel):
    id: int
    subject_uid: str
    relation_uid: str
    object_uid: str | None
    object_literal: str | None
    confidence: float | None
    status: str
    qualifiers_json: dict[str, Any] | None
    provenance_json: dict[str, Any] | None


def _get_provider(name: str):
    if name == "stub":
        return StubProvider(), "stub"
    raise HTTPException(status_code=400, detail=f"Unknown provider: {name}")


def _get_or_create_translation_run(
    *,
    db: Session,
    document_id: int,
    provider_name: str,
    params_json: dict[str, Any] | None,
) -> TranslationRun:
    # Reuse matching runs so repeated translate requests are idempotent.
    existing_runs = db.execute(
        select(TranslationRun)
        .where(
            TranslationRun.document_id == document_id,
            TranslationRun.llm_provider == provider_name,
            TranslationRun.llm_model == provider_name,
        )
        .order_by(TranslationRun.id.desc())
    ).scalars().all()

    for run in existing_runs:
        if (run.params_json or None) == (params_json or None):
            return run

    run = TranslationRun(
        document_id=document_id,
        llm_provider=provider_name,
        llm_model=provider_name,
        params_json=params_json,
    )
    db.add(run)
    db.flush()
    return run


def _create_review_item_if_missing(
    *,
    db: Session,
    item_type: str,
    item_ref: str,
    reason: str,
) -> None:
    existing = db.execute(
        select(ReviewQueue.id).where(
            ReviewQueue.item_type == item_type,
            ReviewQueue.item_ref == item_ref,
            ReviewQueue.status == "open",
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(ReviewQueue(item_type=item_type, item_ref=item_ref, reason=reason, status="open"))


def _norm_label(label: str) -> str:
    return " ".join(label.strip().lower().split())


def _ensure_provisional_concept(db: Session, uid: str) -> None:
    if not uid.startswith("provisional:"):
        return

    concept = db.get(Concept, uid)
    if concept is None:
        label = uid.rsplit(":", maxsplit=1)[-1].replace("_", " ").replace("-", " ").strip() or uid
        concept = Concept(uid=uid, pref_label=label, definition=None, status="provisional")
        db.add(concept)
        db.flush()

    term_norm = _norm_label(concept.pref_label)
    existing = db.execute(
        select(Term.id).where(
            Term.concept_uid == concept.uid,
            Term.lang == "en",
            Term.label_norm == term_norm,
        )
    ).scalar_one_or_none()
    if existing is None:
        db.add(
            Term(
                concept_uid=concept.uid,
                lang="en",
                label=concept.pref_label,
                label_norm=term_norm,
                is_preferred=True,
            )
        )

    _create_review_item_if_missing(
        db=db,
        item_type="concept",
        item_ref=concept.uid,
        reason="Provisional concept requires review",
    )


def _build_translate_summary(run_id: int, db: Session) -> TranslateSummary:
    counts = db.execute(
        select(
            func.count(SentenceIR.id),
            func.sum(case((SentenceIR.is_valid.is_(True), 1), else_=0)),
        ).where(SentenceIR.translation_run_id == run_id)
    ).one()
    sentences_processed = int(counts[0] or 0)
    valid_count = int(counts[1] or 0)
    invalid_count = sentences_processed - valid_count
    return TranslateSummary(
        translation_run_id=run_id,
        sentences_processed=sentences_processed,
        valid_count=valid_count,
        invalid_count=invalid_count,
    )


@router.post("/translate/document/{document_id}", response_model=TranslateSummary)
def translate_document(
    document_id: int,
    payload: TranslateRequest,
    db: Session = Depends(get_db),
) -> TranslateSummary:
    doc = db.execute(select(Document).where(Document.id == document_id)).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    provider, provider_name = _get_provider(payload.provider)
    params_json = {"max_sentences": payload.max_sentences} if payload.max_sentences else None
    run = _get_or_create_translation_run(
        db=db,
        document_id=document_id,
        provider_name=provider_name,
        params_json=params_json,
    )

    query = select(Sentence).where(Sentence.document_id == document_id).order_by(Sentence.sentence_index)
    if payload.max_sentences:
        query = query.limit(payload.max_sentences)
    sentences = db.execute(query).scalars().all()

    for sentence in sentences:
        existing_sentence_ir = db.execute(
            select(SentenceIR).where(
                SentenceIR.translation_run_id == run.id,
                SentenceIR.sentence_id == sentence.id,
            )
        ).scalar_one_or_none()
        if existing_sentence_ir is not None:
            continue

        context = {
            "sentence_id": f"doc{document_id}:s{sentence.sentence_index}",
            "document_id": document_id,
            "sentence_index": sentence.sentence_index,
        }
        ir = provider.generate_ir(sentence.text, context)
        is_valid, errors = validate_ir(ir)

        db.add(
            SentenceIR(
                translation_run_id=run.id,
                sentence_id=sentence.id,
                ir_json=ir,
                is_valid=is_valid,
                errors_json=errors or None,
            )
        )

        if not is_valid:
            _create_review_item_if_missing(
                db=db,
                item_type="sentence_ir",
                item_ref=f"{run.id}:{sentence.id}",
                reason="SentenceIR validation failed",
            )
            continue

        rendered_rows = render_ir_to_expressions(
            ir,
            provenance={
                "document_id": document_id,
                "sentence_id": sentence.id,
                "translation_run_id": run.id,
                "sentence_text": sentence.text,
            },
        )
        existing_relation_indices = set(
            db.execute(
                select(Expression.relation_index).where(
                    Expression.translation_run_id == run.id,
                    Expression.sentence_id == sentence.id,
                )
            ).scalars()
        )

        for rendered in rendered_rows:
            if rendered.relation_index in existing_relation_indices:
                continue

            db.add(
                Expression(
                    translation_run_id=rendered.translation_run_id,
                    sentence_id=rendered.sentence_id,
                    relation_index=rendered.relation_index,
                    subject_uid=rendered.subject_uid,
                    relation_uid=rendered.relation_uid,
                    object_uid=rendered.object_uid,
                    object_literal=rendered.object_literal,
                    qualifiers_json=rendered.qualifiers_json,
                    provenance_json=rendered.provenance_json,
                    confidence=rendered.confidence,
                    status=rendered.status,
                )
            )
            existing_relation_indices.add(rendered.relation_index)

            uids = [rendered.subject_uid, rendered.object_uid]
            has_provisional = False
            for uid in uids:
                if uid is None or not uid.startswith("provisional:"):
                    continue
                has_provisional = True
                _ensure_provisional_concept(db, uid)
            if has_provisional:
                _create_review_item_if_missing(
                    db=db,
                    item_type="expression",
                    item_ref=f"{run.id}:{sentence.id}:{rendered.relation_index}",
                    reason="Provisional UID requires review",
                )

    db.commit()
    return _build_translate_summary(run.id, db)


@router.get("/translation-runs/{run_id}", response_model=TranslationRunOut)
def get_translation_run(run_id: int, db: Session = Depends(get_db)) -> TranslationRunOut:
    run = db.execute(select(TranslationRun).where(TranslationRun.id == run_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Translation run not found")

    counts = db.execute(
        select(
            func.count(SentenceIR.id),
            func.sum(case((SentenceIR.is_valid.is_(True), 1), else_=0)),
        ).where(SentenceIR.translation_run_id == run_id)
    ).one()

    sentences_processed = int(counts[0] or 0)
    valid_count = int(counts[1] or 0)
    invalid_count = sentences_processed - valid_count

    return TranslationRunOut(
        id=run.id,
        document_id=run.document_id,
        llm_provider=run.llm_provider,
        llm_model=run.llm_model,
        params_json=run.params_json,
        created_at=run.created_at,
        sentences_processed=sentences_processed,
        valid_count=valid_count,
        invalid_count=invalid_count,
    )


@router.get("/translation-runs/{run_id}/expressions", response_model=list[ExpressionOut])
def get_translation_run_expressions(run_id: int, db: Session = Depends(get_db)) -> list[ExpressionOut]:
    run = db.execute(select(TranslationRun.id).where(TranslationRun.id == run_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Translation run not found")

    rows = (
        db.execute(
            select(Expression)
            .where(Expression.translation_run_id == run_id)
            .order_by(Expression.sentence_id, Expression.relation_index, Expression.id)
        )
        .scalars()
        .all()
    )

    return [
        ExpressionOut(
            id=row.id,
            subject_uid=row.subject_uid,
            relation_uid=row.relation_uid,
            object_uid=row.object_uid,
            object_literal=row.object_literal,
            confidence=row.confidence,
            status=row.status,
            qualifiers_json=row.qualifiers_json,
            provenance_json=row.provenance_json,
        )
        for row in rows
    ]


@router.get("/translation-runs/{run_id}/export.csv")
def export_translation_run_csv(run_id: int, db: Session = Depends(get_db)) -> Response:
    run = db.execute(select(TranslationRun.id).where(TranslationRun.id == run_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Translation run not found")

    rows = (
        db.execute(
            select(Expression)
            .where(Expression.translation_run_id == run_id)
            .order_by(Expression.sentence_id, Expression.relation_index, Expression.id)
        )
        .scalars()
        .all()
    )

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "expression_id",
            "subject_uid",
            "relation_uid",
            "object_uid",
            "object_literal",
            "confidence",
            "status",
            "qualifiers_json",
            "provenance_json",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.id,
                row.subject_uid,
                row.relation_uid,
                row.object_uid,
                row.object_literal,
                row.confidence,
                row.status,
                row.qualifiers_json,
                row.provenance_json,
            ]
        )

    return Response(content=output.getvalue(), media_type="text/csv")
