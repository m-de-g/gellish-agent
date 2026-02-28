from sqlalchemy import func, select

from app.api.routes.dictionary import (
    ProvisionalConceptCreateIn,
    PromoteConceptIn,
    create_provisional_concept,
    get_alias,
    get_concept,
    promote_concept,
    search_relation_types,
    search_terms,
)
from app.api.routes.documents import DocumentPasteIn, paste_document
from app.api.routes.reviews import DismissReviewIn, ResolveReviewIn, dismiss_review, resolve_review
from app.api.routes.translate import TranslateRequest, get_translation_run_expressions, translate_document
from app.db import session as db_session
from app.models.core import Concept, ConceptAlias, Expression, ReviewQueue


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
        provisional = create_provisional_concept(
            ProvisionalConceptCreateIn(
                pref_label="Alpha",
                definition="Temporary alpha concept.",
                lang="en",
                terms=["alpha temp"],
            ),
            db,
        )
        provisional_uid = provisional.uid

        doc = paste_document(DocumentPasteIn(text="Alpha has value 1."), db)
        summary = translate_document(doc.id, TranslateRequest(provider="stub"), db)
        expressions = get_translation_run_expressions(summary.translation_run_id, db)

        target_sentence_id = expressions[0].provenance_json["sentence_id"]
        next_relation_idx = db.execute(
            select(func.max(Expression.relation_index)).where(
                Expression.translation_run_id == summary.translation_run_id,
                Expression.sentence_id == target_sentence_id,
            )
        ).scalar_one()
        next_relation_idx = int(next_relation_idx or 0) + 1

        custom_expr = Expression(
            translation_run_id=summary.translation_run_id,
            sentence_id=target_sentence_id,
            relation_index=next_relation_idx,
            subject_uid=provisional_uid,
            relation_uid="rel:has_part",
            object_uid=provisional_uid,
            object_literal=None,
            qualifiers_json=None,
            provenance_json={"source": "test"},
            confidence=1.0,
            status="proposed",
        )
        db.add(custom_expr)
        db.flush()

        db.add(
            ReviewQueue(
                item_type="expression",
                item_ref=f"{summary.translation_run_id}:{target_sentence_id}:{next_relation_idx}",
                reason="Provisional UID requires review",
                status="open",
            )
        )
        db.add(
            ReviewQueue(
                item_type="concept",
                item_ref=provisional_uid,
                reason="Manual review",
                status="open",
            )
        )
        db.commit()

        result_1 = promote_concept(provisional_uid, PromoteConceptIn(), db)
        assert result_1.new_uid.startswith("concept:alpha")
        assert result_1.expressions_updated >= 1
        assert result_1.review_items_resolved >= 1

        alias = db.execute(select(ConceptAlias).where(ConceptAlias.old_uid == provisional_uid)).scalar_one_or_none()
        assert alias is not None
        assert alias.new_uid == result_1.new_uid

        alias_lookup = get_alias(provisional_uid, db)
        assert alias_lookup.new_uid == result_1.new_uid

        old_concept = db.get(Concept, provisional_uid)
        assert old_concept is not None
        assert old_concept.status == "deprecated"

        rows = db.execute(
            select(Expression).where(Expression.translation_run_id == summary.translation_run_id)
        ).scalars().all()
        assert any(row.subject_uid == result_1.new_uid for row in rows)
        assert any(row.object_uid == result_1.new_uid for row in rows)
        assert all(row.subject_uid != provisional_uid for row in rows)
        assert all(row.object_uid != provisional_uid for row in rows)

        promoted_reviews = db.execute(
            select(ReviewQueue).where(
                ReviewQueue.item_ref.in_(
                    [
                        provisional_uid,
                        f"{summary.translation_run_id}:{target_sentence_id}:{next_relation_idx}",
                    ]
                )
            )
        ).scalars().all()
        assert promoted_reviews
        assert all(item.status == "resolved" for item in promoted_reviews)
        assert all(item.resolution == "promoted" for item in promoted_reviews)

        loaded_provisional = get_concept(provisional_uid, db)
        assert loaded_provisional.canonical_uid == result_1.new_uid

        result_2 = promote_concept(provisional_uid, PromoteConceptIn(), db)
        assert result_2.new_uid == result_1.new_uid
        assert result_2.review_items_resolved == 0

        alias_count = db.execute(select(func.count(ConceptAlias.id))).scalar_one()
        assert int(alias_count) == 1


def test_review_resolve_and_dismiss_endpoints(db_engine):
    with db_session.SessionLocal() as db:
        item = ReviewQueue(item_type="concept", item_ref="provisional:concept:test", reason="check", status="open")
        db.add(item)
        db.commit()
        review_id = item.id

        resolved = resolve_review(review_id, ResolveReviewIn(resolution="accepted", notes="Looks good"), db)
        assert resolved.status == "resolved"
        assert resolved.resolution == "accepted"
        assert resolved.updated_at is not None

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
        assert dismissed.updated_at is not None
