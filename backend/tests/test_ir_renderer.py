from app.services.ir_renderer import render_ir_to_expressions


def test_render_ir_to_expressions_is_deterministic():
    ir = {
        "relations": [
            {
                "subject_uid": "provisional:subject:1",
                "relation_uid": "rel:has_value",
                "object_literal": "Alpha",
                "qualifiers": {"unit": "text"},
                "confidence": 1.0,
            }
        ]
    }
    provenance = {
        "document_id": 10,
        "sentence_id": 20,
        "translation_run_id": 30,
        "sentence_text": "Alpha",
    }

    rendered_1 = render_ir_to_expressions(ir, provenance)
    rendered_2 = render_ir_to_expressions(ir, provenance)

    assert rendered_1 == rendered_2
    assert rendered_1[0].relation_index == 0
    assert rendered_1[0].provenance_json["document_id"] == 10
    assert rendered_1[0].provenance_json["sentence_id"] == 20
    assert rendered_1[0].provenance_json["translation_run_id"] == 30
    assert rendered_1[0].provenance_json["sentence_text"] == "Alpha"


def test_render_ir_to_expressions_maps_entity_ids_to_provisional_uids():
    ir = {
        "entities": [
            {"entity_id": "entity:toaster", "entity_type": "object", "confidence": 1.0},
            {"entity_id": "entity:lever", "entity_type": "object", "confidence": 1.0},
        ],
        "relations": [
            {
                "relation_uid": "rel:has_part",
                "source_entity_id": "entity:toaster",
                "target_entity_id": "entity:lever",
                "confidence": 1.0,
            }
        ],
    }
    provenance = {
        "document_id": 10,
        "sentence_id": 20,
        "translation_run_id": 30,
        "sentence_text": "A toaster has a lever.",
    }

    rendered = render_ir_to_expressions(ir, provenance)

    assert len(rendered) == 1
    assert rendered[0].subject_uid == "provisional:toaster"
    assert rendered[0].relation_uid == "rel:has_part"
    assert rendered[0].object_uid == "provisional:lever"
    assert rendered[0].object_literal is None
