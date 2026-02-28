from sqlalchemy import select

from app.api.routes.documents import DocumentPasteIn, paste_document
from app.api.routes.translate import TranslateRequest, translate_document
from app.db import session as db_session
from app.models.core import SentenceIR, TranslationRun


def test_translate_document_stub(db_engine):
    payload = DocumentPasteIn(text="Alpha. Beta!")
    with db_session.SessionLocal() as db:
        doc = paste_document(payload, db)

    request = TranslateRequest(provider="stub")
    with db_session.SessionLocal() as db:
        summary = translate_document(doc.id, request, db)

    assert summary.translation_run_id is not None
    assert summary.sentences_processed >= 1
    assert summary.valid_count == summary.sentences_processed

    with db_session.SessionLocal() as db:
        run = db.execute(
            select(TranslationRun).where(TranslationRun.id == summary.translation_run_id)
        ).scalar_one_or_none()
        assert run is not None
        rows = db.execute(
            select(SentenceIR).where(SentenceIR.translation_run_id == summary.translation_run_id)
        ).scalars().all()

    assert len(rows) == summary.sentences_processed
