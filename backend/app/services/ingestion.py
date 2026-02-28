from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models.core import Document, Sentence


@dataclass(frozen=True)
class SentenceSpan:
    text: str
    start: int | None
    end: int | None


_SPACY_NLP = None
_SPACY_TRIED = False


def normalize_text(text: str) -> str:
    if text is None:
        return ""
    normalized = text.replace("\x00", "")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    return normalized


def compute_content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load_spacy_model():
    global _SPACY_NLP, _SPACY_TRIED
    if _SPACY_TRIED:
        return _SPACY_NLP
    _SPACY_TRIED = True
    try:
        import spacy

        _SPACY_NLP = spacy.load("en_core_web_sm")
    except Exception:
        _SPACY_NLP = None
    return _SPACY_NLP


def _segment_sentences_regex(text: str) -> list[SentenceSpan]:
    pattern = re.compile(r"[^.!?]+[.!?]+|[^.!?]+$")
    spans: list[SentenceSpan] = []
    for match in pattern.finditer(text):
        segment = match.group(0)
        if not segment:
            continue
        lstrip_len = len(segment) - len(segment.lstrip())
        rstrip_len = len(segment.rstrip())
        trimmed = segment.strip()
        if not trimmed:
            continue
        start = match.start() + lstrip_len
        end = match.start() + rstrip_len
        spans.append(SentenceSpan(trimmed, start, end))
    if not spans and text.strip():
        spans.append(SentenceSpan(text.strip(), 0, len(text.strip())))
    return spans


def segment_sentences(text: str) -> list[SentenceSpan]:
    nlp = _load_spacy_model()
    if nlp is None:
        return _segment_sentences_regex(text)
    doc = nlp(text)
    spans: list[SentenceSpan] = []
    for sent in doc.sents:
        sent_text = sent.text.strip()
        if not sent_text:
            continue
        spans.append(SentenceSpan(sent_text, sent.start_char, sent.end_char))
    if not spans and text.strip():
        spans.append(SentenceSpan(text.strip(), 0, len(text.strip())))
    return spans


def extract_text_from_url(url: str) -> str:
    response = httpx.get(url, follow_redirects=True, timeout=15.0)
    response.raise_for_status()
    html = response.text

    extracted: str | None = None
    try:
        import trafilatura

        extracted = trafilatura.extract(html)
    except Exception:
        extracted = None

    if not extracted:
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            extracted = soup.get_text(separator="\n")
        except Exception:
            extracted = None

    if not extracted:
        raise ValueError("Unable to extract text from URL")

    return extracted


def ingest_text(
    db: Session,
    *,
    text: str,
    source: str | None,
    mime_type: str | None,
    metadata: dict | None,
) -> tuple[Document, bool]:
    normalized = normalize_text(text)
    content_hash = compute_content_hash(normalized)

    existing = db.execute(select(Document).where(Document.content_hash == content_hash)).scalar_one_or_none()
    if existing is not None:
        return existing, True

    doc = Document(
        source=source,
        mime_type=mime_type,
        content_hash=content_hash,
        metadata_json=metadata,
    )
    db.add(doc)
    db.flush()

    spans = segment_sentences(normalized)
    sentence_rows = [
        Sentence(
            document_id=doc.id,
            sentence_index=index,
            text=span.text,
            char_start=span.start,
            char_end=span.end,
        )
        for index, span in enumerate(spans)
    ]
    if sentence_rows:
        db.add_all(sentence_rows)

    db.commit()
    db.refresh(doc)
    return doc, False
