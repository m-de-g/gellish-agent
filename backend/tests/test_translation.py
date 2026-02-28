from sqlalchemy import select

from app.api.routes.documents import DocumentPasteIn, paste_document
from app.api.routes.translate import (
    TranslateRequest,
    export_translation_run_csv,
    get_translation_run_expressions,
    translate_document,
)
from app.db import session as db_session
from app.models.core import Expression, SentenceIR, TranslationRun


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
