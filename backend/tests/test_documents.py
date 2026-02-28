import pytest
from sqlalchemy import select

from app.api.routes.documents import DocumentPasteIn, paste_document
from app.db import session as db_session
from app.models.core import Sentence


def test_paste_ingestion_creates_doc(db_engine):
    payload = DocumentPasteIn(text="Hello world.")
    with db_session.SessionLocal() as db:
        result = paste_document(payload, db)
    doc_id = result.id

    with db_session.SessionLocal() as db:
        sentences = db.execute(
            select(Sentence).where(Sentence.document_id == doc_id)
        ).scalars().all()
    assert len(sentences) >= 1


def test_paste_idempotent(db_engine):
    payload = DocumentPasteIn(text="Hello world. Second sentence?")

    with db_session.SessionLocal() as db:
        response_1 = paste_document(payload, db)
        doc_id = response_1.id
        count_1 = db.execute(
            select(Sentence).where(Sentence.document_id == doc_id)
        ).scalars().all()

    with db_session.SessionLocal() as db:
        response_2 = paste_document(payload, db)
        count_2 = db.execute(
            select(Sentence).where(Sentence.document_id == doc_id)
        ).scalars().all()

    assert response_1.id == response_2.id

    assert len(count_1) == len(count_2)
    assert len(count_1) >= 1
