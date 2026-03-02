from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...db.session import get_db
from ...models.core import Document, Sentence
from ...services.ingestion import extract_text_from_url, ingest_text, normalize_text

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentPasteIn(BaseModel):
    source: str | None = None
    text: str
    metadata: dict[str, Any] | None = None


class DocumentUrlIn(BaseModel):
    url: str = Field(..., min_length=1)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str | None
    mime_type: str | None
    content_hash: str
    metadata_json: dict[str, Any] | None
    created_at: Any


class DocumentListItem(BaseModel):
    id: int
    source: str | None
    mime_type: str | None
    created_at: Any


class SentenceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    document_id: int
    sentence_index: int
    text: str
    char_start: int | None
    char_end: int | None
    page_no: int | None


class IngestResult(BaseModel):
    id: int
    existing: bool


@router.post("/paste", response_model=IngestResult)
def paste_document(payload: DocumentPasteIn, db: Session = Depends(get_db)) -> IngestResult:
    normalized = normalize_text(payload.text)
    if not normalized.strip():
        raise HTTPException(status_code=400, detail="Text is empty")
    doc, existing = ingest_text(
        db,
        text=payload.text,
        source=payload.source,
        mime_type="text/plain",
        metadata=payload.metadata,
    )
    return IngestResult(id=doc.id, existing=existing)


@router.get("", response_model=list[DocumentListItem])
def list_documents(
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[DocumentListItem]:
    safe_limit = max(1, min(limit, 200))
    rows = (
        db.execute(select(Document).order_by(Document.created_at.desc(), Document.id.desc()).limit(safe_limit))
        .scalars()
        .all()
    )
    return [
        DocumentListItem(
            id=row.id,
            source=row.source,
            mime_type=row.mime_type,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.post("/upload", response_model=IngestResult)
def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> IngestResult:
    filename = file.filename or "upload.txt"
    content = file.file.read()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("utf-8", errors="replace")

    normalized = normalize_text(text)
    if not normalized.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    doc, existing = ingest_text(
        db,
        text=text,
        source=filename,
        mime_type=file.content_type or "text/plain",
        metadata=None,
    )
    return IngestResult(id=doc.id, existing=existing)


@router.post("/url", response_model=IngestResult)
def ingest_url(payload: DocumentUrlIn, db: Session = Depends(get_db)) -> IngestResult:
    try:
        text = extract_text_from_url(payload.url)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    normalized = normalize_text(text)
    if not normalized.strip():
        raise HTTPException(status_code=400, detail="Text is empty")

    doc, existing = ingest_text(
        db,
        text=text,
        source=payload.url,
        mime_type="text/html",
        metadata=None,
    )
    return IngestResult(id=doc.id, existing=existing)


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)) -> DocumentOut:
    doc = db.execute(select(Document).where(Document.id == document_id)).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentOut.model_validate(doc)


@router.get("/{document_id}/sentences", response_model=list[SentenceOut])
def get_document_sentences(
    document_id: int,
    db: Session = Depends(get_db),
) -> list[SentenceOut]:
    doc = db.execute(select(Document.id).where(Document.id == document_id)).scalar_one_or_none()
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    rows = (
        db.execute(
            select(Sentence).where(Sentence.document_id == document_id).order_by(Sentence.sentence_index)
        )
        .scalars()
        .all()
    )
    return [SentenceOut.model_validate(row) for row in rows]
