from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from ..db.session import Base

PK_TYPE = BigInteger().with_variant(Integer, "sqlite")


class Document(Base):
    __tablename__ = "document"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)  # filename or URL
    mime_type: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Sentence(Base):
    __tablename__ = "sentence"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("document.id", ondelete="CASCADE"), index=True)
    sentence_index: Mapped[int] = mapped_column(BigInteger, nullable=False)  # order within doc
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_start: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    char_end: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    page_no: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    __table_args__ = (
        Index("ix_sentence_doc_idx", "document_id", "sentence_index", unique=True),
    )

class Concept(Base):
    __tablename__ = "concept"
    uid: Mapped[str] = mapped_column(String(255), primary_key=True)
    pref_label: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")  # active|provisional|deprecated
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class Term(Base):
    __tablename__ = "term"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    concept_uid: Mapped[str] = mapped_column(String(255), ForeignKey("concept.uid", ondelete="CASCADE"), index=True)
    lang: Mapped[str] = mapped_column(String(16), nullable=False, default="en")
    label: Mapped[str] = mapped_column(Text, nullable=False)
    label_norm: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    is_preferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        Index("ux_term_concept_lang_norm", "concept_uid", "lang", "label_norm", unique=True),
        Index("ix_term_lang_norm", "lang", "label_norm"),
    )

class RelationType(Base):
    __tablename__ = "relation_type"
    uid: Mapped[str] = mapped_column(String(255), primary_key=True)
    pref_label: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class TranslationRun(Base):
    __tablename__ = "translation_run"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("document.id", ondelete="CASCADE"), index=True)
    tool_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    params_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    total_sentences: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    processed_sentences: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    valid_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    invalid_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    retries_total: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    token_prompt_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    token_completion_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    token_total: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    aborted_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class SentenceIR(Base):
    __tablename__ = "sentence_ir"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    translation_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("translation_run.id", ondelete="CASCADE"),
        index=True,
    )
    sentence_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sentence.id", ondelete="CASCADE"),
        index=True,
    )
    ir_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    errors_json: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index("ix_sentence_ir_run_sentence", "translation_run_id", "sentence_id", unique=True),
    )

class Expression(Base):
    __tablename__ = "expression"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    translation_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("translation_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sentence_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("sentence.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_index: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_uid: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    relation_uid: Mapped[str] = mapped_column(String(255), ForeignKey("relation_type.uid"), nullable=False, index=True)
    object_uid: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)  # concept UID
    object_literal: Mapped[str | None] = mapped_column(Text, nullable=True)  # if literal value
    qualifiers_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provenance_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")  # proposed|accepted|rejected
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        Index(
            "ix_expression_run_sentence_relation_idx",
            "translation_run_id",
            "sentence_id",
            "relation_index",
            unique=True,
        ),
    )

class AdvisorCall(Base):
    __tablename__ = "advisor_call"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    translation_run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("translation_run.id", ondelete="CASCADE"), index=True)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    response_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    decision_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ReviewQueue(Base):
    __tablename__ = "review_queue"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    item_type: Mapped[str] = mapped_column(String(64), nullable=False)  # concept|relation|expression
    item_ref: Mapped[str] = mapped_column(Text, nullable=False)         # UID or expression id, etc.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")  # open|resolved|dismissed
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    dismissed_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resolved_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    dismissed_at: Mapped[str | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConceptAlias(Base):
    __tablename__ = "concept_alias"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    old_uid: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    new_uid: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, default="concept")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ExportArtifact(Base):
    __tablename__ = "export_artifact"
    id: Mapped[int] = mapped_column(PK_TYPE, primary_key=True, autoincrement=True)
    translation_run_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("translation_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    format: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    storage_path: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[str] = mapped_column(DateTime(timezone=True), server_default=func.now())
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
