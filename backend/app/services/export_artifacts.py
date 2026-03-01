from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.config import get_artifact_root
from ..models.core import Expression, ExportArtifact

SOUFFLE_FORMAT = "souffle"
FACTS_BUNDLE_KIND = "facts_bundle"
SOUFFLE_SCHEMA_VERSION = "souffle-triple-v1"


@dataclass
class SouffleWriteResult:
    artifact_dir: Path
    row_count: int
    sha256: str
    files: list[dict[str, int | str]]
    relations: list[str]


def _sanitize_token(value: str | None) -> str:
    if value is None:
        return ""
    text = str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ").strip()
    return text


def _build_program_dl() -> str:
    return ".decl triple(s:symbol, p:symbol, o:symbol)\n.input triple\n.output triple\n"


def _build_readme() -> str:
    return "Souffle invocation:\n\nsouffle -F . -D out program.dl\n"


def _manifest_files(artifact_dir: Path, filenames: list[str]) -> list[dict[str, int | str]]:
    return [
        {
            "name": name,
            "size_bytes": (artifact_dir / name).stat().st_size,
        }
        for name in filenames
    ]


def write_souffle_bundle(
    *,
    db: Session,
    run_id: int,
    export_id: int,
    created_at: datetime | str | None = None,
) -> SouffleWriteResult:
    artifact_dir = get_artifact_root() / "exports" / str(export_id) / SOUFFLE_FORMAT
    if artifact_dir.exists():
        raise FileExistsError(f"Artifact path already exists: {artifact_dir}")
    artifact_dir.mkdir(parents=True, exist_ok=False)

    facts_path = artifact_dir / "triple.facts"
    program_path = artifact_dir / "program.dl"
    readme_path = artifact_dir / "README.txt"
    manifest_path = artifact_dir / "manifest.json"

    digest = hashlib.sha256()
    row_count = 0
    relation_uids: set[str] = set()

    rows = (
        db.execute(
            select(Expression)
            .where(Expression.translation_run_id == run_id)
            .order_by(Expression.sentence_id, Expression.relation_index, Expression.id)
        )
        .scalars()
        .all()
    )

    try:
        with facts_path.open("w", encoding="utf-8") as facts_file:
            for row in rows:
                subject = _sanitize_token(row.subject_uid)
                predicate = _sanitize_token(row.relation_uid)
                object_uid = _sanitize_token(row.object_uid)
                object_literal = _sanitize_token(row.object_literal)

                if not subject or not predicate:
                    continue

                if object_uid:
                    obj = object_uid
                elif object_literal:
                    obj = f"literal:{object_literal}"
                else:
                    continue

                line = f"{subject}\t{predicate}\t{obj}\n"
                line_bytes = line.encode("utf-8")
                facts_file.write(line)
                digest.update(line_bytes)
                row_count += 1
                relation_uids.add(predicate)

        program_path.write_text(_build_program_dl(), encoding="utf-8")
        readme_path.write_text(_build_readme(), encoding="utf-8")

        sha256 = digest.hexdigest()
        created_at_value: str | None
        if isinstance(created_at, datetime):
            created_at_value = created_at.isoformat()
        elif created_at is not None:
            created_at_value = str(created_at)
        else:
            created_at_value = None

        manifest_payload = {
            "export_id": export_id,
            "translation_run_id": run_id,
            "created_at": created_at_value,
            "schema_version": SOUFFLE_SCHEMA_VERSION,
            "row_count": row_count,
            "sha256": sha256,
            "files": [],
        }
        filenames = ["triple.facts", "program.dl", "manifest.json", "README.txt"]
        manifest_payload["files"] = _manifest_files(artifact_dir, ["triple.facts", "program.dl", "README.txt"])
        manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8")
        manifest_payload["files"] = _manifest_files(artifact_dir, filenames)
        manifest_path.write_text(json.dumps(manifest_payload, indent=2, sort_keys=True), encoding="utf-8")

        return SouffleWriteResult(
            artifact_dir=artifact_dir,
            row_count=row_count,
            sha256=sha256,
            files=manifest_payload["files"],
            relations=sorted(relation_uids),
        )
    except Exception:
        shutil.rmtree(artifact_dir, ignore_errors=True)
        raise


def artifact_storage_path(export_id: int) -> str:
    return f"exports/{export_id}/{SOUFFLE_FORMAT}"


def artifact_dir_from_storage_path(storage_path: str) -> Path:
    return get_artifact_root() / Path(storage_path)


def load_manifest(storage_path: str) -> dict | None:
    manifest_path = artifact_dir_from_storage_path(storage_path) / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def create_zip_from_artifact(storage_path: str, target_zip: Path) -> None:
    artifact_dir = artifact_dir_from_storage_path(storage_path)
    shutil.make_archive(str(target_zip.with_suffix("")), "zip", root_dir=artifact_dir)


def upsert_artifact_manifest_metadata(artifact: ExportArtifact, write_result: SouffleWriteResult) -> None:
    artifact.sha256 = write_result.sha256
    artifact.row_count = write_result.row_count
    artifact.schema_version = SOUFFLE_SCHEMA_VERSION
    artifact.meta_json = {
        "files": write_result.files,
        "relations": write_result.relations,
    }
