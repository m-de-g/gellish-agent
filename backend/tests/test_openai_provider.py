from __future__ import annotations

from types import SimpleNamespace

from app.services.providers.openai_provider import DEFAULT_OPENAI_TEMPERATURE, OpenAIProvider


def test_openai_provider_system_prompt_requires_ir_shape():
    class ProbeProvider(OpenAIProvider):
        def __init__(self):
            super().__init__(api_key="test-key")
            self.system_prompt = ""
            self.user_prompt = ""

        def _generate_with_schema(self, system_prompt: str, user_prompt: str) -> dict:
            self.system_prompt = system_prompt
            self.user_prompt = user_prompt
            return {
                "sentence_id": "doc1:s0",
                "text": "Alpha has value 1.",
                "entities": [],
                "relations": [],
            }

        def _generate_with_json_text(self, system_prompt: str, user_prompt: str) -> dict:
            raise AssertionError("Fallback path should not be used in this test")

    provider = ProbeProvider()
    provider.generate_ir("Alpha has value 1.", {"document_id": 1, "sentence_id": "doc1:s0"})

    assert "Top-level keys must be exactly: sentence_id, text, entities, relations." in provider.system_prompt
    assert "Required top-level keys entities and relations must always be present as arrays." in provider.system_prompt
    assert "Do not include any other top-level keys." in provider.system_prompt
    assert '"entities": []' in provider.system_prompt
    assert '"relations": []' in provider.system_prompt
    assert "- Emit entities as a list under the top-level key entities." in provider.system_prompt
    assert "- Emit relations as a list under the top-level key relations." in provider.system_prompt
    assert "- Do not use placeholder UIDs like provisional:subject or provisional:object." in provider.system_prompt
    assert "- Every relation must include a non-null subject_uid." in provider.system_prompt
    assert (
        "- Every relation must include exactly one of object_uid or object_literal (object_uid XOR object_literal)."
        in provider.system_prompt
    )
    assert (
        "- For pattern 'X has Y', emit entities for X and Y with meaningful provisional UIDs derived from surface labels."
        in provider.system_prompt
    )
    assert (
        "- Example for 'A toaster has a lever.': entities should include provisional:toaster and provisional:lever, and relations should include rel:has_part with subject_uid=provisional:toaster and object_uid=provisional:lever."
        in provider.system_prompt
    )


def test_openai_provider_retry_prompt_includes_validation_errors_and_fix_instruction():
    provider = OpenAIProvider(api_key="test-key")

    user_prompt = provider._build_user_prompt(
        "Alpha has value 1.",
        {
            "document_id": 1,
            "sentence_id": "doc1:s0",
            "retry_attempt": 1,
            "validation_errors": ["entities: is required", "relations: is required"],
        },
    )

    assert "Previous output failed schema validation." in user_prompt
    assert "- entities: is required" in user_prompt
    assert "- relations: is required" in user_prompt
    assert "Return ONLY corrected JSON with required keys entities and relations." in user_prompt


def test_openai_provider_uses_low_default_temperature_in_schema_request():
    class FakeResponses:
        def __init__(self):
            self.last_payload = None

        def create(self, **payload):
            self.last_payload = payload
            return SimpleNamespace(
                output_parsed={
                    "sentence_id": "doc1:s0",
                    "text": "Alpha has value 1.",
                    "entities": [],
                    "relations": [],
                }
            )

    fake_responses = FakeResponses()
    fake_client = SimpleNamespace(responses=fake_responses)
    provider = OpenAIProvider(api_key="test-key")
    provider._client = fake_client

    provider._generate_with_schema("sys", "user")

    assert fake_responses.last_payload is not None
    assert fake_responses.last_payload["temperature"] == DEFAULT_OPENAI_TEMPERATURE
