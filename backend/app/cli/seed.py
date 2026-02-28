from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal
from app.models.core import Concept, RelationType, Term


def _norm_label(label: str) -> str:
    return " ".join(label.strip().lower().split())


def load_yaml(path: str) -> dict[str, Any]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"YAML pack must be a mapping/object, got: {type(data)}")
    return data


def upsert_relation_types(db: Session, relations: list[dict[str, Any]]) -> int:
    n = 0
    for r in relations:
        uid = r["uid"]
        pref_label = r.get("pref_label") or uid
        definition = r.get("definition")
        status = r.get("status", "active")

        existing = db.get(RelationType, uid)
        if existing:
            changed = False
            if existing.pref_label != pref_label:
                existing.pref_label = pref_label
                changed = True
            if existing.definition != definition:
                existing.definition = definition
                changed = True
            if existing.status != status:
                existing.status = status
                changed = True
            if changed:
                n += 1
        else:
            db.add(
                RelationType(
                    uid=uid,
                    pref_label=pref_label,
                    definition=definition,
                    status=status,
                )
            )
            n += 1
    return n


def upsert_concepts(db: Session, concepts: list[dict[str, Any]]) -> int:
    n = 0
    for c in concepts:
        uid = c["uid"]
        pref_label = c.get("pref_label") or uid
        definition = c.get("definition")
        status = c.get("status", "active")

        existing = db.get(Concept, uid)
        if existing:
            changed = False
            if existing.pref_label != pref_label:
                existing.pref_label = pref_label
                changed = True
            if existing.definition != definition:
                existing.definition = definition
                changed = True
            if existing.status != status:
                existing.status = status
                changed = True
            if changed:
                n += 1
        else:
            db.add(
                Concept(
                    uid=uid,
                    pref_label=pref_label,
                    definition=definition,
                    status=status,
                )
            )
            n += 1
    return n


def upsert_terms(db: Session, terms: list[dict[str, Any]]) -> int:
    """
    Inserts terms idempotently using (concept_uid, lang, label_norm) uniqueness.
    Updates is_preferred/label if present.
    """
    n = 0
    for t in terms:
        concept_uid = t["concept_uid"]
        lang = t.get("lang", "en")
        label = t["label"]
        label_norm = _norm_label(label)
        is_preferred = bool(t.get("is_preferred", False))

        existing = db.execute(
            select(Term).where(
                Term.concept_uid == concept_uid,
                Term.lang == lang,
                Term.label_norm == label_norm,
            )
        ).scalar_one_or_none()

        if existing:
            changed = False
            if existing.label != label:
                existing.label = label
                changed = True
            if existing.is_preferred != is_preferred:
                existing.is_preferred = is_preferred
                changed = True
            if changed:
                n += 1
        else:
            db.add(
                Term(
                    concept_uid=concept_uid,
                    lang=lang,
                    label=label,
                    label_norm=label_norm,
                    is_preferred=is_preferred,
                )
            )
            n += 1
    return n


def seed_from_pack(db: Session, pack: dict[str, Any]) -> dict[str, int]:
    relations = pack.get("relations") or []
    concepts = pack.get("concepts") or []
    terms = pack.get("terms") or []

    if not isinstance(relations, list) or not isinstance(concepts, list) or not isinstance(terms, list):
        raise ValueError("Pack keys 'relations', 'concepts', 'terms' must be lists if present.")

    out = {"relations_upserted": 0, "concepts_upserted": 0, "terms_upserted": 0}

    out["relations_upserted"] = upsert_relation_types(db, relations)
    out["concepts_upserted"] = upsert_concepts(db, concepts)
    out["terms_upserted"] = upsert_terms(db, terms)

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed Gellish dictionary tables from a YAML starter pack.")
    parser.add_argument("--pack", required=True, help="Path to starter pack YAML, e.g. starter_packs/basic.yaml")
    args = parser.parse_args()

    pack = load_yaml(args.pack)

    db = SessionLocal()
    try:
        stats = seed_from_pack(db, pack)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    print("Seed complete:", stats)


if __name__ == "__main__":
    main()
