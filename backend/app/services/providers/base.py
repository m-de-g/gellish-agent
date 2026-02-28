from __future__ import annotations

from abc import ABC, abstractmethod


class IRProvider(ABC):
    @abstractmethod
    def generate_ir(self, sentence_text: str, context: dict) -> dict:
        raise NotImplementedError
