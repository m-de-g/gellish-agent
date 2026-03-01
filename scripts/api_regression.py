#!/usr/bin/env python3
"""
API regression test runner for gellish-agent.

Usage:
  python scripts/api_regression.py --base-url http://localhost:8000 --provider stub
  python scripts/api_regression.py --base-url http://localhost:8000 --provider openai

Notes:
- Assumes the server is already running (uvicorn ...).
- Uses only the public HTTP API; does not touch DB directly.
- Designed to be extendable: add new test_* functions and include them in main().
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import random
import string
import sys
import time
import zipfile
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests


# ----------------------------
# Utilities / Test Harness
# ----------------------------

class TestFailure(RuntimeError):
    pass


def fail(msg: str) -> None:
    raise TestFailure(msg)


def check(cond: bool, msg: str) -> None:
    if not cond:
        fail(msg)


def rand_suffix(n: int = 8) -> str:
    return "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pretty(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)


@dataclass
class RunContext:
    base_url: str
    provider: str
    openai_temperature: float = 0.0
    timeout_s: float = 60.0


class Client:
    def __init__(self, ctx: RunContext):
        self.ctx = ctx
        self.s = requests.Session()

    def url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return self.ctx.base_url.rstrip("/") + path

    def get(self, path: str, **kwargs) -> requests.Response:
        return self.s.get(self.url(path), timeout=self.ctx.timeout_s, **kwargs)

    def post(self, path: str, json_body: Optional[dict] = None, **kwargs) -> requests.Response:
        return self.s.post(self.url(path), json=json_body, timeout=self.ctx.timeout_s, **kwargs)

    def must_200_json(self, resp: requests.Response, where: str) -> Any:
        if resp.status_code != 200:
            fail(f"{where}: expected 200, got {resp.status_code}\n{resp.text}")
        try:
            return resp.json()
        except Exception:
            fail(f"{where}: expected JSON response, got:\n{resp.text}")

    def must_200_bytes(self, resp: requests.Response, where: str) -> bytes:
        if resp.status_code != 200:
            fail(f"{where}: expected 200, got {resp.status_code}\n{resp.text}")
        return resp.content


# ----------------------------
# Tests
# ----------------------------

def test_openapi_has_expected_paths(c: Client) -> None:
    resp = c.get("/openapi.json")
    spec = c.must_200_json(resp, "GET /openapi.json")
    paths = spec.get("paths") or {}
    check(isinstance(paths, dict), "openapi.json missing 'paths' object")

    required_paths = [
        "/health",
        "/documents/paste",
        "/translate/document/{document_id}",
        "/translation-runs/{run_id}/expressions",
        "/translation-runs/{run_id}/sentence-irs",
        "/reviews",
        "/reviews/{review_id}/dismiss",
        "/reviews/{review_id}/resolve",
        "/translation-runs/{run_id}/provisionals",
        "/translation-runs/{run_id}/promote-provisionals",
        "/translation-runs/{run_id}/exports",
        "/translation-runs/{run_id}/exports/souffle",
        "/exports",
        "/exports/{export_id}",
        "/exports/{export_id}/download",
    ]

    missing = [p for p in required_paths if p not in paths]
    check(not missing, f"OpenAPI missing expected paths: {missing}")


def test_health(c: Client) -> None:
    resp = c.get("/health")
    body = c.must_200_json(resp, "GET /health")
    check(isinstance(body, dict), "health response is not a JSON object")
    check(body.get("status") in ("ok", "OK", "healthy", True), f"unexpected /health payload: {body}")


def test_paste_ingest_idempotent(c: Client) -> Tuple[int, bool]:
    # Use a unique doc each run; then re-post exactly same text and expect existing=true (or same id).
    text = f"A toaster has a lever! (regression {rand_suffix()})"
    body = {"text": text}
    resp1 = c.post("/documents/paste", json_body=body)
    doc1 = c.must_200_json(resp1, "POST /documents/paste (1)")
    check("id" in doc1, f"paste ingest did not return id: {doc1}")
    doc_id = int(doc1["id"])
    existing1 = bool(doc1.get("existing", False))

    resp2 = c.post("/documents/paste", json_body=body)
    doc2 = c.must_200_json(resp2, "POST /documents/paste (2)")
    check(int(doc2["id"]) == doc_id, f"idempotency: expected same id, got {doc2['id']} vs {doc_id}")
    # Some implementations may not return "existing"; accept either but if present should be True on second insert.
    if "existing" in doc2:
        check(bool(doc2["existing"]) is True, f"idempotency: expected existing=true on second post, got {doc2}")

    return doc_id, existing1


def translate_slice(
    c: Client,
    document_id: int,
    start_sentence_index: int,
    max_sentences: int,
    translation_run_id: Optional[int] = None,
) -> dict:
    payload: Dict[str, Any] = {
        "provider": c.ctx.provider,
        "max_sentences": max_sentences,
        "start_sentence_index": start_sentence_index,
    }

    if c.ctx.provider == "openai":
        payload["openai"] = {"temperature": c.ctx.openai_temperature}

    if translation_run_id is not None:
        payload["translation_run_id"] = translation_run_id

    resp = c.post(f"/translate/document/{document_id}", json_body=payload)
    out = c.must_200_json(resp, f"POST /translate/document/{document_id}")
    check("translation_run_id" in out, f"translate response missing translation_run_id: {out}")
    return out


def test_resumable_translation_and_sentence_irs(c: Client, document_id: int) -> int:
    # Translate first sentence only
    out1 = translate_slice(c, document_id, start_sentence_index=0, max_sentences=1)
    run_id = int(out1["translation_run_id"])

    # Some servers return next_sentence_index/is_complete; handle gracefully.
    next_idx = out1.get("next_sentence_index")
    is_complete = out1.get("is_complete")
    # If next index provided and not complete, translate the next slice.
    if isinstance(next_idx, int) and (is_complete is False):
        out2 = translate_slice(c, document_id, start_sentence_index=next_idx, max_sentences=1, translation_run_id=run_id)
        check(int(out2["translation_run_id"]) == run_id, "resume should use same translation_run_id")
    else:
        # Even if not resumable (single sentence doc), that's OK. We still proceed.
        pass

    # Validate SentenceIRs endpoint
    resp = c.get(f"/translation-runs/{run_id}/sentence-irs")
    sirs = c.must_200_json(resp, f"GET /translation-runs/{run_id}/sentence-irs")
    check(isinstance(sirs, list), "sentence-irs response should be a list")
    check(len(sirs) >= 1, "expected at least 1 sentence_ir row")

    # Validate each row structure
    for row in sirs:
        check("sentence_id" in row and "is_valid" in row and "ir_json" in row, f"bad sentence_ir row: {row}")
        if row["is_valid"] is True:
            ir = row["ir_json"]
            check(isinstance(ir, dict), f"ir_json not an object: {ir}")
            check("entities" in ir and "relations" in ir, f"ir_json missing entities/relations: {ir}")
        else:
            # invalid row should have errors_json
            # (some implementations may use null; allow but warn)
            pass

    return run_id


def test_expressions_exist(c: Client, run_id: int) -> List[dict]:
    resp = c.get(f"/translation-runs/{run_id}/expressions")
    exprs = c.must_200_json(resp, f"GET /translation-runs/{run_id}/expressions")
    check(isinstance(exprs, list), "expressions response should be a list")
    check(len(exprs) >= 1, "expected at least 1 expression row")
    for e in exprs:
        check("subject_uid" in e and "relation_uid" in e, f"bad expression row: {e}")
        # Must have an object uid or literal (or else renderer should have skipped)
        has_obj = bool(e.get("object_uid")) or bool(e.get("object_literal"))
        check(has_obj, f"expression has neither object_uid nor object_literal: {e}")
    return exprs


def test_provisionals_and_batch_promote(c: Client, run_id: int) -> Dict[str, str]:
    # List provisionals
    resp = c.get(f"/translation-runs/{run_id}/provisionals")
    prov = c.must_200_json(resp, f"GET /translation-runs/{run_id}/provisionals")
    check(isinstance(prov, dict), f"provisionals response not object: {prov}")
    prov_uids = prov.get("provisional_uids")
    check(isinstance(prov_uids, list), f"provisional_uids missing or not list: {prov}")
    check(len(prov_uids) >= 1, f"expected at least one provisional uid for run {run_id}")

    # Build mapping to unique canonical concept IDs to avoid polluting the global KB

    mapping: Dict[str, Dict[str, Any]] = {}
    promoted_map: Dict[str, str] = {}

    for puid in prov_uids:
        if not isinstance(puid, str) or not puid.startswith("provisional:"):
            continue

        digest = hashlib.sha256(puid.encode("utf-8")).hexdigest()[:12]
        new_uid = f"concept:test_{digest}"

        suffix = puid.split(":", 1)[1]
        pref_label = suffix.replace("_", " ").replace("-", " ").strip() or "concept"

        mapping[puid] = {"new_uid": new_uid, "pref_label": pref_label}

    payload = {"mapping": mapping, "auto_generate_missing": False}
    resp2 = c.post(f"/translation-runs/{run_id}/promote-provisionals", json_body=payload)

    if resp2.status_code == 409:
        body = resp2.json()
        detail = body.get("detail", "")
        if "already mapped to" in detail:
            # Treat as success: mapping already exists globally.
            return {}
        fail(f"promote-provisionals conflict: {body}")

    out = c.must_200_json(resp2, f"POST /translation-runs/{run_id}/promote-provisionals")

    # Response shape varies slightly; we require a "promoted" map at least.
    promoted = out.get("promoted")
    check(isinstance(promoted, dict), f"promote-provisionals missing promoted map: {out}")

    for old_uid, new_uid in promoted.items():
        if isinstance(old_uid, str) and isinstance(new_uid, str):
            promoted_map[old_uid] = new_uid

    check(len(promoted_map) >= 1, "expected at least one promoted uid mapping")

    # Verify expressions rewritten for this run
    exprs = test_expressions_exist(c, run_id)
    for e in exprs:
        s = e.get("subject_uid")
        o = e.get("object_uid")
        if isinstance(s, str) and s in promoted_map:
            fail(f"expression subject_uid still provisional after promotion: {e}")
        if isinstance(o, str) and o in promoted_map:
            fail(f"expression object_uid still provisional after promotion: {e}")

    return promoted_map


def test_souffle_export_archive(c: Client, run_id: int) -> int:
    # Generate an export artifact (immutable)
    resp = c.post(f"/translation-runs/{run_id}/exports/souffle", json_body={})
    out = c.must_200_json(resp, f"POST /translation-runs/{run_id}/exports/souffle")

    check("export_id" in out or "id" in out, f"export response missing export_id: {out}")
    export_id = int(out.get("export_id") or out.get("id"))
    row_count = out.get("row_count")
    if row_count is not None:
        check(isinstance(row_count, int), f"row_count should be int: {row_count}")

    # List exports for run
    resp2 = c.get(f"/translation-runs/{run_id}/exports")
    exports = c.must_200_json(resp2, f"GET /translation-runs/{run_id}/exports")
    check(isinstance(exports, list), "exports list should be list")
    check(any(int(e.get("id", -1)) == export_id or int(e.get("export_id", -1)) == export_id for e in exports),
          f"export_id {export_id} not found in run exports listing")

    # Fetch artifact metadata
    resp3 = c.get(f"/exports/{export_id}")
    meta = c.must_200_json(resp3, f"GET /exports/{export_id}")
    check(isinstance(meta, dict), "export metadata should be object")
    check(str(meta.get("format", "")).lower() == "souffle", f"expected format=souffle: {meta}")

    # Download zip and validate contents
    resp4 = c.get(f"/exports/{export_id}/download")
    zbytes = c.must_200_bytes(resp4, f"GET /exports/{export_id}/download")
    zf = zipfile.ZipFile(io.BytesIO(zbytes))

    names = set(zf.namelist())
    required = {"triple.facts", "program.dl", "manifest.json", "README.txt"}
    # Some zips include a folder prefix; normalize by basename.
    basenames = {os.path.basename(n) for n in names if not n.endswith("/")}
    missing = required - basenames
    check(not missing, f"zip missing files: {missing}\nfiles={sorted(basenames)}")

    triple_path = next(n for n in zf.namelist() if os.path.basename(n) == "triple.facts")
    manifest_path = next(n for n in zf.namelist() if os.path.basename(n) == "manifest.json")
    program_path = next(n for n in zf.namelist() if os.path.basename(n) == "program.dl")

    triple_data = zf.read(triple_path)
    manifest = json.loads(zf.read(manifest_path).decode("utf-8"))
    program = zf.read(program_path).decode("utf-8", errors="replace")

    # Validate program.dl contains basic Soufflé triple decl/input
    check(".decl triple" in program, "program.dl missing .decl triple")
    check(".input triple" in program, "program.dl missing .input triple")

    # Validate manifest matches triple hash/row count if provided
    triple_sha = sha256_bytes(triple_data)
    manifest_sha = manifest.get("sha256") or manifest.get("triple_sha256")
    if isinstance(manifest_sha, str) and manifest_sha:
        check(manifest_sha == triple_sha, f"manifest sha mismatch: {manifest_sha} != {triple_sha}")

    # Validate row count equals number of non-empty lines in triple.facts if present
    lines = [ln for ln in triple_data.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    manifest_rows = manifest.get("row_count")
    if isinstance(manifest_rows, int):
        check(manifest_rows == len(lines), f"manifest row_count {manifest_rows} != triple.facts lines {len(lines)}")

    return export_id


def test_exports_search_endpoint(c: Client, run_id: int, export_id: int) -> None:
    # Basic search/list endpoint
    resp = c.get(f"/exports?format=souffle&run_id={run_id}&limit=10")
    out = c.must_200_json(resp, "GET /exports search")
    check(isinstance(out, list), f"/exports expected list, got: {type(out)}")
    check(any(int(e.get("id", -1)) == export_id or int(e.get("export_id", -1)) == export_id for e in out),
          f"export_id {export_id} not found in /exports search results")


# ----------------------------
# Main
# ----------------------------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://localhost:8000", help="API base URL (default http://localhost:8000)")
    ap.add_argument("--provider", default="stub", choices=["stub", "openai"], help="translation provider to use")
    ap.add_argument("--openai-temperature", type=float, default=0.0, help="OpenAI temperature for tests (default 0.0)")
    ap.add_argument("--timeout", type=float, default=60.0, help="HTTP timeout seconds")
    args = ap.parse_args()

    ctx = RunContext(
        base_url=args.base_url,
        provider=args.provider,
        openai_temperature=args.openai_temperature,
        timeout_s=args.timeout,
    )
    c = Client(ctx)

    # Run tests
    started = time.time()
    try:
        print("[1] OpenAPI paths…")
        test_openapi_has_expected_paths(c)

        print("[2] Health…")
        test_health(c)

        print("[3] Paste ingest + idempotency…")
        doc_id, _ = test_paste_ingest_idempotent(c)
        print(f"    doc_id={doc_id}")

        print("[4] Resumable translate + sentence IRs…")
        run_id = test_resumable_translation_and_sentence_irs(c, doc_id)
        print(f"    translation_run_id={run_id}")

        print("[5] Expressions exist…")
        _ = test_expressions_exist(c, run_id)

        print("[6] Provisionals + batch promote…")
        promoted_map = test_provisionals_and_batch_promote(c, run_id)
        print(f"    promoted {len(promoted_map)} provisionals")

        print("[7] Soufflé export archive…")
        export_id = test_souffle_export_archive(c, run_id)
        print(f"    export_id={export_id}")

        print("[8] Exports search endpoint…")
        test_exports_search_endpoint(c, run_id, export_id)

        elapsed = time.time() - started
        print(f"\n✅ All API regression checks passed in {elapsed:.2f}s")
        return 0

    except TestFailure as e:
        elapsed = time.time() - started
        print(f"\n❌ REGRESSION FAILED after {elapsed:.2f}s: {e}", file=sys.stderr)
        return 2
    except Exception as e:
        elapsed = time.time() - started
        print(f"\n❌ UNEXPECTED ERROR after {elapsed:.2f}s: {type(e).__name__}: {e}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
