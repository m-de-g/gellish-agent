from __future__ import annotations

import csv
import io
import time
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session

from .dictionary import PromoteConceptIn, promote_concept_internal
from ...db.session import get_db
from ...ir_validation import validate_ir
from ...models.core import (
    Concept,
    ConceptAlias,
    Document,
    ExportArtifact,
    Expression,
    Sentence,
    SentenceIR,
    Term,
    TranslationRun,
)
from ...services.ir_renderer import render_ir_to_expressions
from ...services.export_artifacts import (
    FACTS_BUNDLE_KIND,
    SOUFFLE_FORMAT,
    artifact_dir_from_storage_path,
    artifact_storage_path,
    load_manifest,
    upsert_artifact_manifest_metadata,
    write_souffle_bundle,
)
from ...services.providers import ProviderError, ProviderResult, ProviderUsage, get_provider
from ...services.reviews import enqueue_review_item
from ...services.uid import canonical_concept_uid

router = APIRouter(tags=["translation"])


class TranslateRequest(BaseModel):
    provider: str = Field(..., min_length=1)
    start_sentence_index: int = Field(default=0, ge=0)
    max_sentences: int | None = Field(default=None, ge=1)
    translation_run_id: int | None = Field(default=None, ge=1)
    openai: OpenAITranslateOptions | None = None


class OpenAITranslateOptions(BaseModel):
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    seed: int | None = None


class TranslateSummary(BaseModel):
    translation_run_id: int
    sentences_processed: int
    valid_count: int
    invalid_count: int
    next_sentence_index: int | None = None
    is_complete: bool = False
    aborted_reason: str | None = None


class TranslationRunOut(BaseModel):
    id: int
    document_id: int
    llm_provider: str | None
    llm_model: str | None
    params_json: dict[str, Any] | None
    created_at: Any
    started_at: Any | None
    finished_at: Any | None
    provider: str | None
    model: str | None
    total_sentences: int
    processed_sentences: int
    sentences_processed: int
    valid_count: int
    invalid_count: int
    retries_total: int
    token_prompt_total: int | None
    token_completion_total: int | None
    token_total: int | None
    aborted_reason: str | None


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


class SentenceIROut(BaseModel):
    id: int
    translation_run_id: int
    sentence_id: int
    is_valid: bool
    errors_json: list[str] | None
    ir_json: dict[str, Any]
    created_at: Any


class TranslationRunProvisionalsOut(BaseModel):
    run_id: int
    provisional_uids: list[str]
    counts: dict[str, int]


class ExportArtifactOut(BaseModel):
    id: int
    translation_run_id: int
    format: str
    kind: str
    storage_path: str
    sha256: str | None
    row_count: int | None
    schema_version: str | None
    created_at: Any
    meta_json: dict[str, Any] | None


class ExportArtifactCreateOut(BaseModel):
    export_id: int
    run_id: int
    created_at: Any
    row_count: int
    download_url: str


class ExportArtifactListItem(BaseModel):
    export_id: int
    run_id: int
    format: str
    kind: str
    created_at: Any
    row_count: int | None


class ExportPreviewOut(BaseModel):
    export_id: int
    file: str
    lines: list[str]


class PromoteProvisionalsMappingItem(BaseModel):
    new_uid: str | None = Field(default=None, min_length=1)
    pref_label: str | None = None
    definition: str | None = None


class TranslationRunPromoteProvisionalsIn(BaseModel):
    mapping: dict[str, PromoteProvisionalsMappingItem] = Field(default_factory=dict)
    auto_generate_missing: bool = False


class TranslationRunPromoteProvisionalsOut(BaseModel):
    run_id: int
    promoted: dict[str, str]
    skipped: list[str]
    expressions_updated: int
    review_items_resolved: int


def _get_or_create_translation_run(
    *,
    db: Session,
    document_id: int,
    provider_name: str,
    model_name: str,
    params_json: dict[str, Any] | None,
) -> TranslationRun:
    # Reuse matching runs so repeated translate requests are idempotent.
    existing_runs = db.execute(
        select(TranslationRun)
        .where(
            TranslationRun.document_id == document_id,
            TranslationRun.llm_provider == provider_name,
            TranslationRun.llm_model == model_name,
        )
        .order_by(TranslationRun.id.desc())
    ).scalars().all()

    for run in existing_runs:
        if (run.params_json or None) == (params_json or None):
            run.provider = provider_name
            run.model = model_name
            return run

    run = TranslationRun(
        document_id=document_id,
        llm_provider=provider_name,
        llm_model=model_name,
        provider=provider_name,
        model=model_name,
        params_json=params_json,
    )
    db.add(run)
    db.flush()
    return run


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _retry_backoff_seconds(retry_count: int) -> float:
    if retry_count <= 0:
        return 0.0
    if retry_count == 1:
        return 0.5
    return 1.5


def _provider_error_to_errors_json(error: ProviderError) -> list[str]:
    return [f"provider_error kind={error.kind} message={error.message}"]


def _apply_usage_totals(run: TranslationRun, usage: ProviderUsage | None) -> None:
    if usage is None:
        return
    if usage.prompt_tokens is not None:
        run.token_prompt_total = int(run.token_prompt_total or 0) + int(usage.prompt_tokens)
    if usage.completion_tokens is not None:
        run.token_completion_total = int(run.token_completion_total or 0) + int(usage.completion_tokens)
    if usage.total_tokens is not None:
        run.token_total = int(run.token_total or 0) + int(usage.total_tokens)


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

    enqueue_review_item(
        db=db,
        item_type="concept",
        item_ref=concept.uid,
        reason="Provisional concept requires review",
    )


def _collect_run_provisionals(run_id: int, db: Session) -> tuple[list[str], dict[str, int]]:
    rows = db.execute(
        select(Expression.subject_uid, Expression.object_uid).where(Expression.translation_run_id == run_id)
    ).all()

    counts: dict[str, int] = {}
    for subject_uid, object_uid in rows:
        if subject_uid and subject_uid.startswith("provisional:"):
            counts[subject_uid] = counts.get(subject_uid, 0) + 1
        if object_uid and object_uid.startswith("provisional:"):
            counts[object_uid] = counts.get(object_uid, 0) + 1

    return sorted(counts.keys()), counts


def _build_translate_summary(
    run_id: int,
    db: Session,
    *,
    next_sentence_index: int | None = None,
    is_complete: bool = False,
) -> TranslateSummary:
    counts = db.execute(
        select(
            func.count(SentenceIR.id),
            func.sum(case((SentenceIR.is_valid.is_(True), 1), else_=0)),
        ).where(SentenceIR.translation_run_id == run_id)
    ).one()
    sentences_processed = int(counts[0] or 0)
    valid_count = int(counts[1] or 0)
    invalid_count = sentences_processed - valid_count
    aborted_reason = db.execute(
        select(TranslationRun.aborted_reason).where(TranslationRun.id == run_id)
    ).scalar_one_or_none()
    return TranslateSummary(
        translation_run_id=run_id,
        sentences_processed=sentences_processed,
        valid_count=valid_count,
        invalid_count=invalid_count,
        next_sentence_index=next_sentence_index,
        is_complete=is_complete,
        aborted_reason=aborted_reason,
    )


def _get_run_or_404(run_id: int, db: Session) -> TranslationRun:
    run = db.execute(select(TranslationRun).where(TranslationRun.id == run_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Translation run not found")
    return run


def _get_export_or_404(export_id: int, db: Session) -> ExportArtifact:
    artifact = db.execute(select(ExportArtifact).where(ExportArtifact.id == export_id)).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Export artifact not found")
    return artifact


def _export_to_out(artifact: ExportArtifact) -> ExportArtifactOut:
    return ExportArtifactOut(
        id=artifact.id,
        translation_run_id=artifact.translation_run_id,
        format=artifact.format,
        kind=artifact.kind,
        storage_path=artifact.storage_path,
        sha256=artifact.sha256,
        row_count=artifact.row_count,
        schema_version=artifact.schema_version,
        created_at=artifact.created_at,
        meta_json=artifact.meta_json,
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

    provider_options: dict[str, Any] = {}
    if payload.provider == "openai":
        provider_options = payload.openai.model_dump(exclude_none=True) if payload.openai else {}

    try:
        provider, provider_name, model_name = get_provider(payload.provider, provider_options)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    params_payload: dict[str, Any] = {"start_sentence_index": payload.start_sentence_index}
    if payload.max_sentences:
        params_payload["max_sentences"] = payload.max_sentences
    if provider_options:
        params_payload[payload.provider] = provider_options
    params_json = params_payload or None

    if payload.translation_run_id is not None:
        run = db.execute(
            select(TranslationRun).where(TranslationRun.id == payload.translation_run_id)
        ).scalar_one_or_none()
        if run is None:
            raise HTTPException(status_code=404, detail="Translation run not found")
        if run.document_id != document_id:
            raise HTTPException(status_code=400, detail="translation_run_id does not match document")
        if run.llm_provider and run.llm_provider != provider_name:
            raise HTTPException(status_code=400, detail="translation_run_id provider mismatch")
        run.llm_provider = provider_name
        run.llm_model = model_name
        run.provider = provider_name
        run.model = model_name
    else:
        run = _get_or_create_translation_run(
            db=db,
            document_id=document_id,
            provider_name=provider_name,
            model_name=model_name,
            params_json=params_json,
        )

    total_sentences = int(
        db.execute(select(func.count(Sentence.id)).where(Sentence.document_id == document_id)).scalar_one()
        or 0
    )
    run.total_sentences = total_sentences
    if run.started_at is None:
        run.started_at = _now_utc()
    run.finished_at = None
    run.aborted_reason = None

    query = (
        select(Sentence)
        .where(
            Sentence.document_id == document_id,
            Sentence.sentence_index >= payload.start_sentence_index,
        )
        .order_by(Sentence.sentence_index)
    )
    if payload.max_sentences:
        query = query.limit(payload.max_sentences)
    sentences = db.execute(query).scalars().all()

    aborted_reason: str | None = None
    abort_run = False
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
        max_attempts = 1 if provider_name == "stub" else 3
        provider_error_retries = 0
        ir: dict[str, Any] = {}
        errors: list[str] = []
        is_valid = False
        usage: ProviderUsage | None = None

        for attempt in range(max_attempts):
            attempt_context = dict(context)
            attempt_context["retry_attempt"] = attempt
            if errors:
                attempt_context["validation_errors"] = errors

            try:
                candidate_ir = provider.generate_ir(sentence.text, attempt_context)
            except ProviderError as error:
                errors = _provider_error_to_errors_json(error)
                is_valid = False
                if error.kind in {"auth", "quota"}:
                    aborted_reason = f"{error.kind}: {error.message}"
                    abort_run = True
                    break
                if error.kind in {"rate_limit", "timeout", "server"} and provider_error_retries < 2:
                    provider_error_retries += 1
                    run.retries_total = int(run.retries_total or 0) + 1
                    time.sleep(_retry_backoff_seconds(provider_error_retries))
                    continue
                break

            result = candidate_ir if isinstance(candidate_ir, ProviderResult) else ProviderResult(ir=candidate_ir)
            usage = result.usage
            if isinstance(result.ir, dict):
                ir = result.ir
                is_valid, errors = validate_ir(ir)
            else:
                ir = {}
                is_valid = False
                errors = [f"Provider returned non-object IR: {type(result.ir).__name__}"]

            if is_valid:
                break

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
            if errors and errors[0].startswith("provider_error"):
                reason = errors[0].replace("provider_error ", "Provider error ")
                enqueue_review_item(
                    db=db,
                    item_type="sentence_ir",
                    item_ref=f"{run.id}:{sentence.id}",
                    reason=reason,
                )
            else:
                first_error = errors[0] if errors else "unknown validation error"
                enqueue_review_item(
                    db=db,
                    item_type="sentence_ir",
                    item_ref=f"{run.id}:{sentence.id}",
                    reason=f"SentenceIR validation failed: {first_error}",
                )
            if abort_run:
                break
            continue

        _apply_usage_totals(run, usage)
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
                enqueue_review_item(
                    db=db,
                    item_type="expression",
                    item_ref=f"{run.id}:{sentence.id}:{rendered.relation_index}",
                    reason="Provisional UID requires review",
                )

    run.processed_sentences = int(
        db.execute(
            select(func.count(SentenceIR.id)).where(SentenceIR.translation_run_id == run.id)
        ).scalar_one()
        or 0
    )
    run.valid_count = int(
        db.execute(
            select(func.sum(case((SentenceIR.is_valid.is_(True), 1), else_=0))).where(
                SentenceIR.translation_run_id == run.id
            )
        ).scalar_one()
        or 0
    )
    run.invalid_count = int(run.processed_sentences - run.valid_count)
    run.aborted_reason = aborted_reason
    run.finished_at = _now_utc()

    slice_end = payload.start_sentence_index + len(sentences)
    next_sentence_index = None if abort_run else (slice_end if slice_end < total_sentences else None)
    is_complete = (next_sentence_index is None) and (not abort_run)

    db.commit()
    return _build_translate_summary(
        run.id,
        db,
        next_sentence_index=next_sentence_index,
        is_complete=is_complete,
    )


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
        started_at=run.started_at,
        finished_at=run.finished_at,
        provider=run.provider,
        model=run.model,
        total_sentences=int(run.total_sentences or 0),
        processed_sentences=int(run.processed_sentences or 0),
        sentences_processed=sentences_processed,
        valid_count=valid_count,
        invalid_count=invalid_count,
        retries_total=int(run.retries_total or 0),
        token_prompt_total=run.token_prompt_total,
        token_completion_total=run.token_completion_total,
        token_total=run.token_total,
        aborted_reason=run.aborted_reason,
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


@router.get("/translation-runs/{run_id}/provisionals", response_model=TranslationRunProvisionalsOut)
def get_translation_run_provisionals(run_id: int, db: Session = Depends(get_db)) -> TranslationRunProvisionalsOut:
    run = db.execute(select(TranslationRun.id).where(TranslationRun.id == run_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Translation run not found")

    provisional_uids, counts = _collect_run_provisionals(run_id, db)
    return TranslationRunProvisionalsOut(run_id=run_id, provisional_uids=provisional_uids, counts=counts)


@router.post(
    "/translation-runs/{run_id}/promote-provisionals",
    response_model=TranslationRunPromoteProvisionalsOut,
)
def promote_translation_run_provisionals(
    run_id: int,
    payload: TranslationRunPromoteProvisionalsIn,
    db: Session = Depends(get_db),
) -> TranslationRunPromoteProvisionalsOut:
    run = db.execute(select(TranslationRun.id).where(TranslationRun.id == run_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Translation run not found")

    provisional_uids, _ = _collect_run_provisionals(run_id, db)
    provisional_uid_set = set(provisional_uids)
    for mapped_uid in payload.mapping:
        if not mapped_uid.startswith("provisional:") or mapped_uid in provisional_uid_set:
            continue
        alias_exists = db.execute(
            select(ConceptAlias.id).where(ConceptAlias.old_uid == mapped_uid)
        ).scalar_one_or_none()
        if alias_exists is not None:
            provisional_uid_set.add(mapped_uid)
    provisional_uids = sorted(provisional_uid_set)
    promoted: dict[str, str] = {}
    skipped: list[str] = []
    expressions_updated = 0
    review_items_resolved = 0

    try:
        for provisional_uid in provisional_uids:
            mapping_item = payload.mapping.get(provisional_uid)
            if mapping_item is None and not payload.auto_generate_missing:
                skipped.append(provisional_uid)
                continue

            existing_alias = db.execute(
                select(ConceptAlias).where(ConceptAlias.old_uid == provisional_uid)
            ).scalar_one_or_none()
            if existing_alias is not None:
                if (
                    mapping_item is not None
                    and mapping_item.new_uid is not None
                    and mapping_item.new_uid != existing_alias.new_uid
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=f"{provisional_uid} already mapped to {existing_alias.new_uid}",
                    )
                promoted[provisional_uid] = existing_alias.new_uid
                continue

            run_matches = int(
                db.execute(
                    select(func.count(Expression.id)).where(
                        Expression.translation_run_id == run_id,
                        or_(Expression.subject_uid == provisional_uid, Expression.object_uid == provisional_uid),
                    )
                ).scalar_one()
                or 0
            )

            source_label = provisional_uid.rsplit(":", maxsplit=1)[-1].replace("_", " ").replace("-", " ").strip()
            preferred_label = (
                mapping_item.pref_label
                if mapping_item is not None and mapping_item.pref_label is not None
                else source_label
            )
            definition = mapping_item.definition if mapping_item is not None else None
            target_uid = (
                mapping_item.new_uid
                if mapping_item is not None and mapping_item.new_uid is not None
                else canonical_concept_uid(preferred_label, definition)
            )

            result = promote_concept_internal(
                provisional_uid,
                PromoteConceptIn(new_uid=target_uid, pref_label=preferred_label, definition=definition),
                db,
            )
            promoted[provisional_uid] = result.new_uid
            expressions_updated += run_matches
            review_items_resolved += result.review_items_resolved

        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Batch promotion failed: {exc}") from exc

    return TranslationRunPromoteProvisionalsOut(
        run_id=run_id,
        promoted=promoted,
        skipped=skipped,
        expressions_updated=expressions_updated,
        review_items_resolved=review_items_resolved,
    )


@router.get("/translation-runs/{run_id}/sentence-irs", response_model=list[SentenceIROut])
def get_translation_run_sentence_irs(run_id: int, db: Session = Depends(get_db)) -> list[SentenceIROut]:
    run = db.execute(select(TranslationRun.id).where(TranslationRun.id == run_id)).scalar_one_or_none()
    if run is None:
        raise HTTPException(status_code=404, detail="Translation run not found")

    rows = (
        db.execute(
            select(SentenceIR)
            .where(SentenceIR.translation_run_id == run_id)
            .order_by(SentenceIR.sentence_id.asc(), SentenceIR.id.asc())
        )
        .scalars()
        .all()
    )

    return [
        SentenceIROut(
            id=row.id,
            translation_run_id=row.translation_run_id,
            sentence_id=row.sentence_id,
            is_valid=row.is_valid,
            errors_json=row.errors_json,
            ir_json=row.ir_json,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/translation-runs/{run_id}/exports/souffle", response_model=ExportArtifactCreateOut)
def create_translation_run_souffle_export(
    run_id: int,
    db: Session = Depends(get_db),
) -> ExportArtifactCreateOut:
    _get_run_or_404(run_id, db)

    artifact = ExportArtifact(
        translation_run_id=run_id,
        format=SOUFFLE_FORMAT,
        kind=FACTS_BUNDLE_KIND,
        storage_path=f"exports/tmp-{uuid4()}",
    )
    db.add(artifact)
    db.flush()

    artifact.storage_path = artifact_storage_path(artifact.id)
    db.flush()
    db.refresh(artifact)

    write_result = write_souffle_bundle(
        db=db,
        run_id=run_id,
        export_id=artifact.id,
        created_at=artifact.created_at,
    )
    upsert_artifact_manifest_metadata(artifact, write_result)
    db.commit()
    db.refresh(artifact)

    return ExportArtifactCreateOut(
        export_id=artifact.id,
        run_id=run_id,
        created_at=artifact.created_at,
        row_count=int(artifact.row_count or 0),
        download_url=f"/exports/{artifact.id}/download",
    )


@router.get("/translation-runs/{run_id}/exports", response_model=list[ExportArtifactListItem])
def list_translation_run_exports(
    run_id: int,
    db: Session = Depends(get_db),
) -> list[ExportArtifactListItem]:
    _get_run_or_404(run_id, db)
    rows = (
        db.execute(
            select(ExportArtifact)
            .where(ExportArtifact.translation_run_id == run_id)
            .order_by(ExportArtifact.created_at.desc(), ExportArtifact.id.desc())
        )
        .scalars()
        .all()
    )
    return [
        ExportArtifactListItem(
            export_id=row.id,
            run_id=row.translation_run_id,
            format=row.format,
            kind=row.kind,
            created_at=row.created_at,
            row_count=row.row_count,
        )
        for row in rows
    ]


@router.get("/exports", response_model=list[ExportArtifactListItem])
def list_exports(
    format_: str | None = Query(default=None, alias="format"),
    kind: str | None = Query(default=None),
    run_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> list[ExportArtifactListItem]:
    query = select(ExportArtifact)
    if format_ is not None:
        query = query.where(ExportArtifact.format == format_)
    if kind is not None:
        query = query.where(ExportArtifact.kind == kind)
    if run_id is not None:
        query = query.where(ExportArtifact.translation_run_id == run_id)
    rows = (
        db.execute(
            query.order_by(ExportArtifact.created_at.desc(), ExportArtifact.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return [
        ExportArtifactListItem(
            export_id=row.id,
            run_id=row.translation_run_id,
            format=row.format,
            kind=row.kind,
            created_at=row.created_at,
            row_count=row.row_count,
        )
        for row in rows
    ]


@router.get("/exports/{export_id}", response_model=ExportArtifactOut)
def get_export_artifact(export_id: int, db: Session = Depends(get_db)) -> ExportArtifactOut:
    artifact = _get_export_or_404(export_id, db)
    manifest = load_manifest(artifact.storage_path)
    if manifest is not None:
        base_meta = artifact.meta_json or {}
        artifact.meta_json = {
            **base_meta,
            "manifest": manifest,
        }
    return _export_to_out(artifact)


@router.get("/exports/{export_id}/download")
def download_export_artifact(export_id: int, db: Session = Depends(get_db)) -> Response:
    artifact = _get_export_or_404(export_id, db)
    artifact_dir = artifact_dir_from_storage_path(artifact.storage_path)
    if not artifact_dir.exists():
        raise HTTPException(status_code=404, detail="Artifact files not found")
    required_files = ["triple.facts", "program.dl", "manifest.json", "README.txt"]
    for filename in required_files:
        if not (artifact_dir / filename).exists():
            raise HTTPException(status_code=404, detail=f"Artifact file not found: {filename}")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        for filename in required_files:
            archive.write(artifact_dir / filename, arcname=filename)

    filename = f"export_{export_id}_{artifact.format}.zip"
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/exports/{export_id}/preview", response_model=ExportPreviewOut)
def preview_export_artifact_file(
    export_id: int,
    file: str = Query(default="triple.facts"),
    lines: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ExportPreviewOut:
    artifact = _get_export_or_404(export_id, db)
    allowed_files = {"triple.facts", "program.dl", "manifest.json", "README.txt"}
    if file not in allowed_files:
        raise HTTPException(status_code=400, detail=f"Unsupported preview file: {file}")

    preview_path = artifact_dir_from_storage_path(artifact.storage_path) / file
    if not preview_path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")

    collected: list[str] = []
    with preview_path.open("r", encoding="utf-8") as handle:
        for idx, line in enumerate(handle):
            if idx >= lines:
                break
            collected.append(line.rstrip("\n"))

    return ExportPreviewOut(export_id=export_id, file=file, lines=collected)


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
