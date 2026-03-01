import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set. Put it in .env at repo root.")


def get_artifact_root() -> Path:
    configured = os.environ.get("ARTIFACT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    repo_root = Path(__file__).resolve().parents[3]
    return (repo_root / "artifacts").resolve()
