import pytest
from fastapi import HTTPException
from sqlalchemy import func, select

from app.api.routes.documents import DocumentPasteIn, paste_document
from app.api.routes.translate import (
    OpenAITranslateOptions,
    PromoteProvisionalsMappingItem,
    TranslateRequest,
    TranslationRunPromoteProvisionalsIn,
    export_translation_run_csv,
    get_translation_run_provisionals,
    get_translation_run_sentence_irs,
    get_translation_run_expressions,
    promote_translation_run_provisionals,
    translate_document,
)
from app.db import session as db_session
from app.main import create_app
from app.models.core import ConceptAlias, Expression, ReviewQueue, SentenceIR, TranslationRun
from app.services.providers import register_provider, reset_provider_registry


def test_translate_document_stub_persists_expressions_and_exports_csv(db_engine):
    payload = DocumentPasteIn(text="Alpha has value 1. Beta has value 2.")
    with db_session.SessionLocal() as db:
        doc = paste_document(payload, db)

    request = TranslateRequest(provider="stub")
    with db_session.SessionLocal() as db:
        summary_1 = translate_document(doc.id, request, db)

    assert summary_1.translation_run_id is not None
    assert summary_1.sentences_processed == 2
    assert summary_1.valid_count == summary_1.sentences_processed

    with db_session.SessionLocal() as db:
        run = db.execute(
            select(TranslationRun).where(TranslationRun.id == summary_1.translation_run_id)
        ).scalar_one_or_none()
        assert run is not None

        sentence_ir_rows = db.execute(
            select(SentenceIR).where(SentenceIR.translation_run_id == summary_1.translation_run_id)
        ).scalars().all()
        assert len(sentence_ir_rows) == summary_1.sentences_processed
        assert all(row.is_valid for row in sentence_ir_rows)

        expression_rows = db.execute(
            select(Expression).where(Expression.translation_run_id == summary_1.translation_run_id)
        ).scalars().all()
        assert len(expression_rows) >= summary_1.sentences_processed

        expression_count_before = len(expression_rows)

    with db_session.SessionLocal() as db:
        summary_2 = translate_document(doc.id, request, db)

    assert summary_2.translation_run_id == summary_1.translation_run_id

    with db_session.SessionLocal() as db:
        expression_rows_after = db.execute(
            select(Expression).where(Expression.translation_run_id == summary_1.translation_run_id)
        ).scalars().all()
        assert len(expression_rows_after) == expression_count_before

        expression_payload = get_translation_run_expressions(summary_1.translation_run_id, db)
        assert len(expression_payload) >= 1

        csv_response = export_translation_run_csv(summary_1.translation_run_id, db)

    csv_lines = [line for line in csv_response.body.decode("utf-8").splitlines() if line.strip()]
    assert csv_lines[0] == (
        "expression_id,subject_uid,relation_uid,object_uid,object_literal,confidence,status,"
        "qualifiers_json,provenance_json"
    )
    assert len(csv_lines) >= 2


def test_translate_document_openai_with_fake_provider(db_engine):
    class FakeOpenAIProvider:
        def generate_ir(self, sentence_text: str, context: dict) -> dict:
            sentence_id = context["sentence_id"]
            return {
                "sentence_id": sentence_id,
                "text": sentence_text,
                "entities": [],
                "relations": [
                    {
                        "subject_surface": "Alpha",
                        "subject_uid": "concept:alpha",
                        "relation_uid": "rel:has_value",
                        "object_uid": "concept:value_1",
                        "confidence": 0.9,
                        "needs_review": False,
                    }
                ],
                "open_terms": [],
            }

    register_provider("openai", lambda _: (FakeOpenAIProvider(), "fake-openai-model"))
    try:
        payload = DocumentPasteIn(text="Alpha has value 1.")
        with db_session.SessionLocal() as db:
            doc = paste_document(payload, db)
            summary = translate_document(
                doc.id,
                TranslateRequest(provider="openai", openai=OpenAITranslateOptions(model="ignored")),
                db,
            )
            run = db.execute(
                select(TranslationRun).where(TranslationRun.id == summary.translation_run_id)
            ).scalar_one()

        assert summary.sentences_processed == 1
        assert summary.valid_count == 1
        assert summary.invalid_count == 0
        assert run.llm_provider == "openai"
        assert run.llm_model == "fake-openai-model"
    finally:
        reset_provider_registry()


def test_translate_document_openai_retry_invalid_then_valid(db_engine):
    class FlakyProvider:
        def __init__(self):
            self.calls = 0

        def generate_ir(self, sentence_text: str, context: dict) -> dict:
            self.calls += 1
            if self.calls == 1:
                return {"sentence_id": context["sentence_id"], "text": sentence_text}
            return {
                "sentence_id": context["sentence_id"],
                "text": sentence_text,
                "entities": [],
                "relations": [
                    {
                        "subject_surface": "Alpha",
                        "subject_uid": "concept:alpha",
                        "relation_uid": "rel:has_value",
                        "object_literal": "1",
                        "confidence": 0.8,
                        "needs_review": False,
                    }
                ],
                "open_terms": [],
            }

    flaky = FlakyProvider()
    register_provider("openai", lambda _: (flaky, "fake-openai-model"))
    try:
        with db_session.SessionLocal() as db:
            doc = paste_document(DocumentPasteIn(text="Alpha has value 1."), db)
            summary = translate_document(doc.id, TranslateRequest(provider="openai"), db)

        assert summary.valid_count == 1
        assert summary.invalid_count == 0
        assert flaky.calls == 2
    finally:
        reset_provider_registry()


def test_translate_document_openai_retry_exhausted_creates_review(db_engine):
    class AlwaysInvalidProvider:
        def generate_ir(self, sentence_text: str, context: dict) -> dict:
            return {"sentence_id": context["sentence_id"], "text": sentence_text}

    register_provider("openai", lambda _: (AlwaysInvalidProvider(), "fake-openai-model"))
    try:
        with db_session.SessionLocal() as db:
            doc = paste_document(DocumentPasteIn(text="Alpha has value 1."), db)
            summary = translate_document(doc.id, TranslateRequest(provider="openai"), db)
            sentence_row = db.execute(
                select(SentenceIR).where(SentenceIR.translation_run_id == summary.translation_run_id)
            ).scalar_one()
            review_row = db.execute(
                select(ReviewQueue).where(
                    ReviewQueue.item_type == "sentence_ir",
                    ReviewQueue.item_ref == f"{summary.translation_run_id}:{sentence_row.sentence_id}",
                )
            ).scalar_one()

        assert summary.valid_count == 0
        assert summary.invalid_count == 1
        assert sentence_row.is_valid is False
        assert sentence_row.errors_json
        assert review_row.reason is not None
        assert "SentenceIR validation failed:" in review_row.reason
    finally:
        reset_provider_registry()


def test_translate_document_openai_maps_entity_relations_to_non_null_expression_uids(db_engine):
    class EntityGraphProvider:
        def generate_ir(self, sentence_text: str, context: dict) -> dict:
            return {
                "sentence_id": context["sentence_id"],
                "text": sentence_text,
                "entities": [
                    {"entity_id": "entity:toaster", "entity_type": "object", "confidence": 1.0},
                    {"entity_id": "entity:lever", "entity_type": "object", "confidence": 1.0},
                ],
                "relations": [
                    {
                        "relation_uid": "rel:has_part",
                        "source_entity_id": "entity:toaster",
                        "target_entity_id": "entity:lever",
                        "confidence": 1.0,
                        "needs_review": False,
                        "subject_surface": "toaster",
                        "subject_uid": "provisional:toaster",
                    }
                ],
            }

    register_provider("openai", lambda _: (EntityGraphProvider(), "fake-openai-model"))
    try:
        with db_session.SessionLocal() as db:
            doc = paste_document(DocumentPasteIn(text="A toaster has a lever."), db)
            summary = translate_document(doc.id, TranslateRequest(provider="openai"), db)
            expression = db.execute(
                select(Expression).where(Expression.translation_run_id == summary.translation_run_id)
            ).scalar_one()
            concept_reviews = db.execute(
                select(ReviewQueue).where(
                    ReviewQueue.item_type == "concept",
                    ReviewQueue.item_ref.in_(["provisional:toaster", "provisional:lever"]),
                )
            ).scalars().all()

        assert summary.valid_count == 1
        assert expression.subject_uid == "provisional:toaster"
        assert expression.relation_uid == "rel:has_part"
        assert expression.object_uid == "provisional:lever"
        assert expression.object_uid is not None
        assert expression.object_literal is None
        assert {item.item_ref for item in concept_reviews} == {
            "provisional:toaster",
            "provisional:lever",
        }
    finally:
        reset_provider_registry()


def test_translation_run_batch_promote_provisionals_and_review_resolution(db_engine):
    class EntityGraphProvider:
        def generate_ir(self, sentence_text: str, context: dict) -> dict:
            return {
                "sentence_id": context["sentence_id"],
                "text": sentence_text,
                "entities": [
                    {"entity_id": "entity:toaster", "entity_type": "object", "confidence": 1.0},
                    {"entity_id": "entity:lever", "entity_type": "object", "confidence": 1.0},
                ],
                "relations": [
                    {
                        "relation_uid": "rel:has_part",
                        "source_entity_id": "entity:toaster",
                        "target_entity_id": "entity:lever",
                        "confidence": 1.0,
                        "needs_review": False,
                        "subject_surface": "toaster",
                        "subject_uid": "provisional:toaster",
                    }
                ],
            }

    register_provider("openai", lambda _: (EntityGraphProvider(), "fake-openai-model"))
    try:
        with db_session.SessionLocal() as db:
            doc = paste_document(DocumentPasteIn(text="A toaster has a lever!"), db)
            summary = translate_document(doc.id, TranslateRequest(provider="openai"), db)

            provisionals = get_translation_run_provisionals(summary.translation_run_id, db)
            assert set(provisionals.provisional_uids) == {"provisional:toaster", "provisional:lever"}
            assert provisionals.counts["provisional:toaster"] == 1
            assert provisionals.counts["provisional:lever"] == 1

            result_1 = promote_translation_run_provisionals(
                summary.translation_run_id,
                TranslationRunPromoteProvisionalsIn(
                    mapping={
                        "provisional:toaster": PromoteProvisionalsMappingItem(
                            new_uid="concept:toaster",
                            pref_label="toaster",
                            definition=None,
                        ),
                        "provisional:lever": PromoteProvisionalsMappingItem(
                            new_uid="concept:lever",
                            pref_label="lever",
                        ),
                    },
                    auto_generate_missing=False,
                ),
                db,
            )
            assert result_1.promoted == {
                "provisional:toaster": "concept:toaster",
                "provisional:lever": "concept:lever",
            }
            assert result_1.skipped == []
            assert result_1.expressions_updated == 2
            assert result_1.review_items_resolved >= 2

            rows_after = db.execute(
                select(Expression).where(Expression.translation_run_id == summary.translation_run_id)
            ).scalars().all()
            assert rows_after
            assert all(row.subject_uid != "provisional:toaster" for row in rows_after)
            assert all(row.object_uid != "provisional:lever" for row in rows_after)
            assert any(row.subject_uid == "concept:toaster" for row in rows_after)
            assert any(row.object_uid == "concept:lever" for row in rows_after)

            aliases = db.execute(
                select(ConceptAlias).where(
                    ConceptAlias.old_uid.in_(["provisional:toaster", "provisional:lever"])
                )
            ).scalars().all()
            assert len(aliases) == 2
            assert {row.old_uid for row in aliases} == {"provisional:toaster", "provisional:lever"}
            assert {row.new_uid for row in aliases} == {"concept:toaster", "concept:lever"}

            review_rows = db.execute(
                select(ReviewQueue).where(
                    ReviewQueue.item_type == "concept",
                    ReviewQueue.item_ref.in_(["provisional:toaster", "provisional:lever"]),
                )
            ).scalars().all()
            assert review_rows
            assert all(row.status == "resolved" for row in review_rows)
            assert all(row.resolution == "promoted" for row in review_rows)

            alias_count_before = int(db.execute(select(func.count(ConceptAlias.id))).scalar_one())

            result_2 = promote_translation_run_provisionals(
                summary.translation_run_id,
                TranslationRunPromoteProvisionalsIn(
                    mapping={
                        "provisional:toaster": PromoteProvisionalsMappingItem(
                            new_uid="concept:toaster",
                            pref_label="toaster",
                            definition=None,
                        ),
                        "provisional:lever": PromoteProvisionalsMappingItem(
                            new_uid="concept:lever",
                            pref_label="lever",
                        ),
                    },
                    auto_generate_missing=False,
                ),
                db,
            )
            assert result_2.promoted == {
                "provisional:toaster": "concept:toaster",
                "provisional:lever": "concept:lever",
            }
            assert result_2.skipped == []
            assert result_2.expressions_updated == 0
            assert result_2.review_items_resolved == 0

            alias_count_after = int(db.execute(select(func.count(ConceptAlias.id))).scalar_one())
            assert alias_count_after == alias_count_before
    finally:
        reset_provider_registry()


def test_review_queue_dedup_and_sentence_ir_inspection_endpoint(db_engine):
    class EntityGraphProvider:
        def generate_ir(self, sentence_text: str, context: dict) -> dict:
            return {
                "sentence_id": context["sentence_id"],
                "text": sentence_text,
                "entities": [
                    {"entity_id": "entity:toaster", "entity_type": "object", "confidence": 1.0},
                    {"entity_id": "entity:lever", "entity_type": "object", "confidence": 1.0},
                ],
                "relations": [
                    {
                        "relation_uid": "rel:has_part",
                        "source_entity_id": "entity:toaster",
                        "target_entity_id": "entity:lever",
                        "confidence": 1.0,
                        "needs_review": False,
                        "subject_surface": "toaster",
                        "subject_uid": "provisional:toaster",
                    }
                ],
            }

    register_provider("openai", lambda _: (EntityGraphProvider(), "fake-openai-model"))
    try:
        with db_session.SessionLocal() as db:
            doc = paste_document(DocumentPasteIn(text="A toaster has a lever."), db)
            summary_1 = translate_document(doc.id, TranslateRequest(provider="openai"), db)
            open_concept_reviews_1 = db.execute(
                select(ReviewQueue).where(
                    ReviewQueue.item_type == "concept",
                    ReviewQueue.item_ref == "provisional:toaster",
                    ReviewQueue.status == "open",
                )
            ).scalars().all()

        with db_session.SessionLocal() as db:
            summary_2 = translate_document(
                doc.id,
                TranslateRequest(provider="openai", max_sentences=1),
                db,
            )
            open_concept_reviews_2 = db.execute(
                select(ReviewQueue).where(
                    ReviewQueue.item_type == "concept",
                    ReviewQueue.item_ref == "provisional:toaster",
                    ReviewQueue.status == "open",
                )
            ).scalars().all()

        assert summary_1.translation_run_id != summary_2.translation_run_id
        assert len(open_concept_reviews_1) == 1
        assert len(open_concept_reviews_2) == 1

        with db_session.SessionLocal() as db:
            payload = get_translation_run_sentence_irs(summary_1.translation_run_id, db)

        assert len(payload) == summary_1.sentences_processed == 1
        assert payload[0].is_valid is True
        assert payload[0].ir_json is not None

        openapi = create_app().openapi()
        assert "/translation-runs/{run_id}/sentence-irs" in openapi["paths"]
    finally:
        reset_provider_registry()


def test_translate_document_openai_requires_api_key(db_engine, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with db_session.SessionLocal() as db:
        doc = paste_document(DocumentPasteIn(text="Alpha has value 1."), db)
        with pytest.raises(HTTPException) as exc_info:
            translate_document(doc.id, TranslateRequest(provider="openai"), db)

    exc = exc_info.value
    assert exc.status_code == 400
    assert "OPENAI_API_KEY" in str(exc.detail)
