from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...ir_validation import validate_ir
from ...models.core import Document, Expression, Sentence, SentenceIR, TranslationRun
from ...providers import StubProvider

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


def _get_provider(name: str):
    if name == "stub":
        return StubProvider(), "stub"
    raise HTTPException(status_code=400, detail=f"Unknown provider: {name}")


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

    run = TranslationRun(
        document_id=document_id,
        llm_provider=provider_name,
        llm_model=provider_name,
        params_json={"max_sentences": payload.max_sentences} if payload.max_sentences else None,
    )
    db.add(run)
    db.flush()

    query = select(Sentence).where(Sentence.document_id == document_id).order_by(Sentence.sentence_index)
    if payload.max_sentences:
        query = query.limit(payload.max_sentences)
    sentences = db.execute(query).scalars().all()

    valid_count = 0
    invalid_count = 0

    for sentence in sentences:
        context = {
            "sentence_id": f"doc{document_id}:s{sentence.sentence_index}",
            "document_id": document_id,
            "sentence_index": sentence.sentence_index,
        }
        ir = provider.generate_ir(sentence.text, context)
        is_valid, errors = validate_ir(ir)
        if is_valid:
            valid_count += 1
        else:
            invalid_count += 1

        db.add(
            SentenceIR(
                translation_run_id=run.id,
                sentence_id=sentence.id,
                ir_json=ir,
                is_valid=is_valid,
                errors_json=errors or None,
            )
        )

        if is_valid:
            for relation in ir.get("relations", []):
                db.add(
                    Expression(
                        subject_uid=relation.get("subject_uid", "provisional:subject"),
                        relation_uid=relation.get("relation_uid", "rel:unknown"),
                        object_uid=relation.get("object_uid"),
                        object_literal=relation.get("object_literal"),
                        qualifiers_json=relation.get("qualifiers"),
                        provenance_json={
                            "document_id": document_id,
                            "sentence_id": sentence.id,
                            "sentence_index": sentence.sentence_index,
                            "char_start": sentence.char_start,
                            "char_end": sentence.char_end,
                        },
                        confidence=relation.get("confidence"),
                        status="proposed",
                    )
                )

    db.commit()

    return TranslateSummary(
        translation_run_id=run.id,
        sentences_processed=len(sentences),
        valid_count=valid_count,
        invalid_count=invalid_count,
    )


@router.get("/translation-runs/{run_id}", response_model=TranslationRunOut)
def get_translation_run(run_id: int, db: Session = Depends(get_db)) -> TranslationRunOut:
    run = db.execute(select(TranslationRun).where(TranslationRun.id == run_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Translation run not found")

    counts = db.execute(
        select(
            func.count(SentenceIR.id),
            func.sum(case((SentenceIR.is_valid == True, 1), else_=0)),
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
