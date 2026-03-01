import io
import zipfile
from pathlib import Path

from sqlalchemy import select

from app.api.routes.documents import DocumentPasteIn, paste_document
from app.api.routes.translate import (
    TranslateRequest,
    create_translation_run_souffle_export,
    download_export_artifact,
    get_export_artifact,
    list_exports,
    list_translation_run_exports,
    preview_export_artifact_file,
    translate_document,
)
from app.db import session as db_session
from app.models.core import ExportArtifact


def test_souffle_export_artifact_archive_endpoints(db_engine, tmp_path, monkeypatch):
    artifact_root = tmp_path / "artifacts"
    monkeypatch.setenv("ARTIFACT_ROOT", str(artifact_root))

    with db_session.SessionLocal() as db:
        doc = paste_document(DocumentPasteIn(text="Alpha has value 1. Beta has value 2."), db)
        summary = translate_document(doc.id, TranslateRequest(provider="stub"), db)
        run_id = summary.translation_run_id

        create_payload = create_translation_run_souffle_export(run_id, db)
        assert create_payload.export_id > 0
        assert create_payload.run_id == run_id
        assert create_payload.download_url == f"/exports/{create_payload.export_id}/download"

        run_exports_payload = list_translation_run_exports(run_id, db)
        assert len(run_exports_payload) == 1
        assert run_exports_payload[0].export_id == create_payload.export_id

        search_payload = list_exports(
            format_="souffle",
            kind="facts_bundle",
            run_id=run_id,
            limit=10,
            offset=0,
            db=db,
        )
        assert len(search_payload) == 1
        assert search_payload[0].export_id == create_payload.export_id

        detail_payload = get_export_artifact(create_payload.export_id, db)
        assert detail_payload.meta_json is not None
        assert "manifest" in detail_payload.meta_json

        preview_payload = preview_export_artifact_file(
            create_payload.export_id,
            file="triple.facts",
            lines=50,
            db=db,
        )
        assert preview_payload.file == "triple.facts"
        assert len(preview_payload.lines) >= 1

        download_response = download_export_artifact(create_payload.export_id, db)
        assert "application/zip" in download_response.media_type

        zip_file = zipfile.ZipFile(io.BytesIO(download_response.body))
        names = {Path(name).name for name in zip_file.namelist()}
        assert {"triple.facts", "program.dl", "manifest.json", "README.txt"}.issubset(names)

    export_id = int(create_payload.export_id)
    with db_session.SessionLocal() as db:
        artifact = db.execute(select(ExportArtifact).where(ExportArtifact.id == export_id)).scalar_one_or_none()
        assert artifact is not None
        assert artifact.translation_run_id == run_id
        assert artifact.format == "souffle"
        assert artifact.kind == "facts_bundle"
        assert artifact.row_count == create_payload.row_count

    artifact_dir = artifact_root / "exports" / str(export_id) / "souffle"
    facts_path = artifact_dir / "triple.facts"
    program_path = artifact_dir / "program.dl"
    manifest_path = artifact_dir / "manifest.json"
    readme_path = artifact_dir / "README.txt"

    assert facts_path.exists()
    assert program_path.exists()
    assert manifest_path.exists()
    assert readme_path.exists()

    facts_lines = [line for line in facts_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(facts_lines) == create_payload.row_count
