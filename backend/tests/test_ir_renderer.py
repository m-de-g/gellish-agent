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
