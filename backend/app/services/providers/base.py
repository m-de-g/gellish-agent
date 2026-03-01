from __future__ import annotations

from dataclasses import dataclass
from abc import ABC, abstractmethod


@dataclass
class ProviderUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class ProviderResult:
    ir: dict
    usage: ProviderUsage | None = None


class ProviderError(Exception):
    def __init__(self, *, kind: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.status_code = status_code


class IRProvider(ABC):
    @abstractmethod
    def generate_ir(self, sentence_text: str, context: dict) -> dict | ProviderResult:
        raise NotImplementedError
