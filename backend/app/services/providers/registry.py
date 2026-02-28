from __future__ import annotations

from typing import Any, Callable

from .base import IRProvider
from .openai_provider import OpenAIProvider
from .stub import StubProvider

ProviderFactory = Callable[[dict[str, Any]], tuple[IRProvider, str]]


def _stub_factory(_: dict[str, Any]) -> tuple[IRProvider, str]:
    return StubProvider(), "stub"


def _openai_factory(options: dict[str, Any]) -> tuple[IRProvider, str]:
    provider = OpenAIProvider(
        model=options.get("model"),
        temperature=options.get("temperature"),
        seed=options.get("seed"),
    )
    return provider, provider.model


_default_provider_factories: dict[str, ProviderFactory] = {
    "stub": _stub_factory,
    "openai": _openai_factory,
}
_provider_factories: dict[str, ProviderFactory] = dict(_default_provider_factories)


def get_provider(name: str, options: dict[str, Any] | None = None) -> tuple[IRProvider, str, str]:
    factory = _provider_factories.get(name)
    if factory is None:
        raise ValueError(f"Unknown provider: {name}")
    provider, model = factory(options or {})
    return provider, name, model


def register_provider(name: str, factory: ProviderFactory) -> None:
    _provider_factories[name] = factory


def unregister_provider(name: str) -> None:
    _provider_factories.pop(name, None)


def reset_provider_registry() -> None:
    _provider_factories.clear()
    _provider_factories.update(_default_provider_factories)
