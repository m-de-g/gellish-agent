from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.core import (
    Concept,
    ConceptUidMapping,
    Expression,
    RelationType,
    ReviewQueue,
    SentenceIR,
    Term,
)

router = APIRouter(prefix="/dictionary", tags=["dictionary"])


def _norm_label(label: str) -> str:
    return " ".join(label.strip().lower().split())


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "concept"


def _replace_uid_in_json(value: Any, old_uid: str, new_uid: str) -> tuple[Any, bool]:
    if isinstance(value, dict):
        changed = False
        output: dict[str, Any] = {}
        for key, child in value.items():
            replaced, child_changed = _replace_uid_in_json(child, old_uid, new_uid)
            output[key] = replaced
            changed = changed or child_changed
        return output, changed
    if isinstance(value, list):
        changed = False
        output_list: list[Any] = []
        for child in value:
            replaced, child_changed = _replace_uid_in_json(child, old_uid, new_uid)
            output_list.append(replaced)
            changed = changed or child_changed
        return output_list, changed
    if isinstance(value, str) and value == old_uid:
        return new_uid, True
    return value, False


class TermSearchItem(BaseModel):
    term_id: int
    label: str
    concept_uid: str
    concept_pref_label: str
    is_preferred: bool


class ConceptTermItem(BaseModel):
    id: int
    label: str
    lang: str
    is_preferred: bool


class ConceptOut(BaseModel):
    uid: str
    pref_label: str
    definition: str | None
    status: str
    terms: list[ConceptTermItem]


class RelationTypeItem(BaseModel):
    uid: str
    pref_label: str
    definition: str | None
    status: str


class ProvisionalConceptCreateIn(BaseModel):
    pref_label: str = Field(..., min_length=1)
    definition: str | None = None
    lang: str = "en"
    terms: list[str] | None = None


class PromoteConceptIn(BaseModel):
    new_uid: str = Field(..., min_length=1)
    pref_label: str | None = None
    definition: str | None = None


class PromoteConceptOut(BaseModel):
    old_uid: str
    new_uid: str
    expressions_updated: int
    sentence_ir_updated: int


@router.get("/terms", response_model=list[TermSearchItem])
def search_terms(
    q: str = Query(..., min_length=1),
    lang: str = Query("en", min_length=1),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[TermSearchItem]:
    q_norm = _norm_label(q)
    contains_pattern = f"%{q_norm}%"
    prefix_pattern = f"{q_norm}%"

    rank = case(
        (Term.label_norm == q_norm, 0),
        (Term.label_norm.like(prefix_pattern), 1),
        (Term.label_norm.like(contains_pattern), 2),
        else_=3,
    )

    rows = db.execute(
        select(Term, Concept.pref_label)
        .join(Concept, Concept.uid == Term.concept_uid)
        .where(
            Term.lang == lang,
            or_(
                Term.label_norm == q_norm,
                Term.label_norm.like(prefix_pattern),
                Term.label_norm.like(contains_pattern),
            ),
        )
        .order_by(rank, Term.is_preferred.desc(), Term.label.asc(), Term.id.asc())
        .limit(limit)
    ).all()

    return [
        TermSearchItem(
            term_id=term.id,
            label=term.label,
            concept_uid=term.concept_uid,
            concept_pref_label=concept_pref_label,
            is_preferred=term.is_preferred,
        )
        for term, concept_pref_label in rows
    ]


@router.get("/concepts/{uid}", response_model=ConceptOut)
def get_concept(uid: str, db: Session = Depends(get_db)) -> ConceptOut:
    concept = db.get(Concept, uid)
    if concept is None:
        raise HTTPException(status_code=404, detail="Concept not found")

    terms = db.execute(
        select(Term)
        .where(Term.concept_uid == uid)
        .order_by(Term.is_preferred.desc(), Term.lang.asc(), Term.label.asc(), Term.id.asc())
    ).scalars().all()

    return ConceptOut(
        uid=concept.uid,
        pref_label=concept.pref_label,
        definition=concept.definition,
        status=concept.status,
        terms=[
            ConceptTermItem(id=term.id, label=term.label, lang=term.lang, is_preferred=term.is_preferred)
            for term in terms
        ],
    )


@router.get("/relations", response_model=list[RelationTypeItem])
def search_relation_types(
    q: str = Query(..., min_length=1),
    limit: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[RelationTypeItem]:
    q_norm = _norm_label(q)
    contains_pattern = f"%{q_norm}%"
    prefix_pattern = f"{q_norm}%"

    rank = case(
        (RelationType.pref_label == q_norm, 0),
        (RelationType.pref_label.like(prefix_pattern), 1),
        (RelationType.pref_label.like(contains_pattern), 2),
        else_=3,
    )

    rows = db.execute(
        select(RelationType)
        .where(
            or_(
                RelationType.pref_label.like(contains_pattern),
                RelationType.uid.like(contains_pattern),
            )
        )
        .order_by(rank, RelationType.pref_label.asc(), RelationType.uid.asc())
        .limit(limit)
    ).scalars().all()

    return [
        RelationTypeItem(
            uid=row.uid,
            pref_label=row.pref_label,
            definition=row.definition,
            status=row.status,
        )
        for row in rows
    ]


@router.post("/concepts", response_model=ConceptOut)
def create_provisional_concept(
    payload: ProvisionalConceptCreateIn,
    db: Session = Depends(get_db),
) -> ConceptOut:
    pref_label_norm = _norm_label(payload.pref_label)
    definition_norm = _norm_label(payload.definition or "")
    hash_input = f"{pref_label_norm}|{definition_norm}".encode("utf-8")
    digest = hashlib.sha256(hash_input).hexdigest()[:16]
    slug = _slugify(pref_label_norm)
    uid = f"provisional:concept:{slug}-{digest}"

    concept = db.get(Concept, uid)
    if concept is None:
        concept = Concept(
            uid=uid,
            pref_label=payload.pref_label.strip(),
            definition=payload.definition,
            status="provisional",
        )
        db.add(concept)
        db.flush()

    preferred_exists = db.execute(
        select(Term.id).where(
            Term.concept_uid == uid,
            Term.lang == payload.lang,
            Term.label_norm == pref_label_norm,
        )
    ).scalar_one_or_none()
    if preferred_exists is None:
        db.add(
            Term(
                concept_uid=uid,
                lang=payload.lang,
                label=payload.pref_label.strip(),
                label_norm=pref_label_norm,
                is_preferred=True,
            )
        )

    for label in payload.terms or []:
        label_clean = label.strip()
        if not label_clean:
            continue
        label_norm = _norm_label(label_clean)
        existing = db.execute(
            select(Term.id).where(
                Term.concept_uid == uid,
                Term.lang == payload.lang,
                Term.label_norm == label_norm,
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                Term(
                    concept_uid=uid,
                    lang=payload.lang,
                    label=label_clean,
                    label_norm=label_norm,
                    is_preferred=False,
                )
            )

    open_review = db.execute(
        select(ReviewQueue.id).where(
            ReviewQueue.item_type == "concept",
            ReviewQueue.item_ref == uid,
            ReviewQueue.status == "open",
        )
    ).scalar_one_or_none()
    if open_review is None:
        db.add(
            ReviewQueue(
                item_type="concept",
                item_ref=uid,
                reason="Provisional concept requires review",
                status="open",
            )
        )

    db.commit()
    return get_concept(uid, db)


@router.post("/concepts/{uid}/promote", response_model=PromoteConceptOut)
def promote_concept(uid: str, payload: PromoteConceptIn, db: Session = Depends(get_db)) -> PromoteConceptOut:
    old_concept = db.get(Concept, uid)
    if old_concept is None:
        raise HTTPException(status_code=404, detail="Concept not found")
    if not uid.startswith("provisional:"):
        raise HTTPException(status_code=400, detail="Only provisional concepts can be promoted")

    refs = db.execute(
        select(Expression.translation_run_id, Expression.sentence_id, Expression.relation_index).where(
            or_(Expression.subject_uid == uid, Expression.object_uid == uid)
        )
    ).all()
    expression_review_refs = {f"{run}:{sentence}:{idx}" for run, sentence, idx in refs}

    expressions_updated = 0
    sentence_ir_updated = 0
    now = datetime.now(timezone.utc)

    try:
        canonical = db.get(Concept, payload.new_uid)
        if canonical is None:
            canonical = Concept(
                uid=payload.new_uid,
                pref_label=payload.pref_label or old_concept.pref_label,
                definition=payload.definition if payload.definition is not None else old_concept.definition,
                status="active",
            )
            db.add(canonical)
            db.flush()
        else:
            if payload.pref_label is not None:
                canonical.pref_label = payload.pref_label
            if payload.definition is not None:
                canonical.definition = payload.definition
            if canonical.status != "active":
                canonical.status = "active"

        canonical_pref_norm = _norm_label(canonical.pref_label)
        canonical_pref_term = db.execute(
            select(Term.id).where(
                Term.concept_uid == canonical.uid,
                Term.lang == "en",
                Term.label_norm == canonical_pref_norm,
            )
        ).scalar_one_or_none()
        if canonical_pref_term is None:
            db.add(
                Term(
                    concept_uid=canonical.uid,
                    lang="en",
                    label=canonical.pref_label,
                    label_norm=canonical_pref_norm,
                    is_preferred=True,
                )
            )

        expressions = db.execute(
            select(Expression).where(
                or_(Expression.subject_uid == uid, Expression.object_uid == uid)
            )
        ).scalars().all()
        for expr in expressions:
            if expr.subject_uid == uid:
                expr.subject_uid = payload.new_uid
            if expr.object_uid == uid:
                expr.object_uid = payload.new_uid
            expressions_updated += 1

        ir_rows = db.execute(select(SentenceIR).where(SentenceIR.ir_json.is_not(None))).scalars().all()
        for row in ir_rows:
            replaced, changed = _replace_uid_in_json(row.ir_json, uid, payload.new_uid)
            if changed:
                row.ir_json = replaced
                sentence_ir_updated += 1

        old_concept.status = "deprecated"

        mapping = db.execute(
            select(ConceptUidMapping).where(
                ConceptUidMapping.old_uid == uid,
                ConceptUidMapping.new_uid == payload.new_uid,
            )
        ).scalar_one_or_none()
        if mapping is None:
            db.add(
                ConceptUidMapping(
                    old_uid=uid,
                    new_uid=payload.new_uid,
                    mapping_type="promotion",
                )
            )

        if expression_review_refs:
            review_rows = db.execute(
                select(ReviewQueue).where(
                    ReviewQueue.status == "open",
                    ReviewQueue.item_type == "expression",
                    ReviewQueue.item_ref.in_(expression_review_refs),
                )
            ).scalars().all()
            for item in review_rows:
                item.status = "resolved"
                item.resolution = f"promoted:{uid}->{payload.new_uid}"
                item.resolved_at = now

        concept_reviews = db.execute(
            select(ReviewQueue).where(
                ReviewQueue.status == "open",
                ReviewQueue.item_type == "concept",
                ReviewQueue.item_ref == uid,
            )
        ).scalars().all()
        for item in concept_reviews:
            item.status = "resolved"
            item.resolution = f"promoted:{uid}->{payload.new_uid}"
            item.resolved_at = now

        db.commit()
    except Exception:
        db.rollback()
        raise

    return PromoteConceptOut(
        old_uid=uid,
        new_uid=payload.new_uid,
        expressions_updated=expressions_updated,
        sentence_ir_updated=sentence_ir_updated,
    )
