from sqlalchemy import select

from app.api.routes.dictionary import (
    ProvisionalConceptCreateIn,
    PromoteConceptIn,
    create_provisional_concept,
    get_concept,
    promote_concept,
    search_relation_types,
    search_terms,
)
from app.api.routes.documents import DocumentPasteIn, paste_document
from app.api.routes.reviews import DismissReviewIn, ResolveReviewIn, dismiss_review, list_reviews, resolve_review
from app.api.routes.translate import TranslateRequest, get_translation_run_expressions, translate_document
from app.db import session as db_session
from app.models.core import Expression, ReviewQueue


def test_dictionary_lookup_and_provisional_create_idempotent(db_engine):
    with db_session.SessionLocal() as db:
        relations = search_relation_types(q="has", limit=20, db=db)
        assert any(item.uid == "rel:has_value" for item in relations)

        payload = ProvisionalConceptCreateIn(
            pref_label="toaster",
            definition="A kitchen device used to toast bread.",
            lang="en",
            terms=["bread toaster", "Toaster appliance"],
        )
        concept_1 = create_provisional_concept(payload, db)
        concept_2 = create_provisional_concept(payload, db)

        assert concept_1.uid.startswith("provisional:concept:")
        assert concept_1.uid == concept_2.uid

        term_rows = search_terms(q="toaster", lang="en", limit=20, db=db)
        assert any(row.concept_uid == concept_1.uid for row in term_rows)

        loaded = get_concept(concept_1.uid, db=db)
        labels = {term.label for term in loaded.terms}
        assert "toaster" in labels
        assert "bread toaster" in labels


def test_review_queue_and_promote_updates_expressions(db_engine):
    with db_session.SessionLocal() as db:
        doc = paste_document(DocumentPasteIn(text="Alpha has value 1. Beta has value 2."), db)
        summary = translate_document(doc.id, TranslateRequest(provider="stub"), db)

        open_reviews = list_reviews(status="open", limit=50, db=db)
        assert len(open_reviews) >= 1

        expressions = get_translation_run_expressions(summary.translation_run_id, db)
        provisional_uid = expressions[0].subject_uid
        assert provisional_uid.startswith("provisional:")

        result = promote_concept(
            provisional_uid,
            PromoteConceptIn(
                new_uid="concept:alpha",
                pref_label="alpha",
                definition="Canonical alpha concept.",
            ),
            db,
        )
        assert result.expressions_updated >= 1

        rows = db.execute(
            select(Expression).where(Expression.translation_run_id == summary.translation_run_id)
        ).scalars().all()
        assert any(row.subject_uid == "concept:alpha" for row in rows)
        assert all(row.subject_uid != provisional_uid for row in rows)

        resolved_reviews = list_reviews(status="resolved", limit=50, db=db)
        assert any(item.item_type == "expression" for item in resolved_reviews)


def test_review_resolve_and_dismiss_endpoints(db_engine):
    with db_session.SessionLocal() as db:
        item = ReviewQueue(item_type="concept", item_ref="provisional:concept:test", reason="check", status="open")
        db.add(item)
        db.commit()
        review_id = item.id

        resolved = resolve_review(review_id, ResolveReviewIn(resolution="accepted", notes="Looks good"), db)
        assert resolved.status == "resolved"
        assert resolved.resolution == "accepted"

        item_2 = ReviewQueue(
            item_type="concept",
            item_ref="provisional:concept:test2",
            reason="check",
            status="open",
        )
        db.add(item_2)
        db.commit()

        dismissed = dismiss_review(item_2.id, DismissReviewIn(reason="duplicate"), db)
        assert dismissed.status == "dismissed"
        assert dismissed.dismissed_reason == "duplicate"
