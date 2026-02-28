from __future__ import annotations

from typing import Protocol


class IRProvider(Protocol):
    def generate_ir(self, sentence_text: str, context: dict) -> dict:
        ...
