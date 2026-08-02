from __future__ import annotations

from providers.base import SearchProvider
from providers.brave import MockBraveProvider


KNOWN_PROVIDERS = ("exa", "tavily", "brave", "brave_news", "mock", "brave_mock")


def get_default_provider(
    *,
    brave_enabled: bool = False,
    brave_api_key: str = "",
    exa_api_key: str = "",
    tavily_api_key: str = "",
) -> SearchProvider:
    """Prefer Exa → Tavily → mock (Brave live deferred)."""
    _ = (brave_enabled, brave_api_key)
    if exa_api_key:
        from providers.exa import ExaSearchProvider

        return ExaSearchProvider(exa_api_key)
    if tavily_api_key:
        from providers.tavily import TavilySearchProvider

        return TavilySearchProvider(tavily_api_key)
    return MockBraveProvider()


def get_provider(
    name: str,
    *,
    brave_enabled: bool = False,
    brave_api_key: str = "",
    exa_api_key: str = "",
    tavily_api_key: str = "",
) -> SearchProvider:
    """Resolve a named provider. Missing Key → clear ValueError (except mock)."""
    key = (name or "").strip().lower()
    if key in ("mock", "brave_mock"):
        return MockBraveProvider()
    if key == "exa":
        from providers.exa import ExaSearchProvider

        return ExaSearchProvider(exa_api_key)
    if key == "tavily":
        from providers.tavily import TavilySearchProvider

        return TavilySearchProvider(tavily_api_key)
    if key in ("brave", "brave_news"):
        raise ValueError(
            "Brave live search is not available yet; use provider=exa|tavily|mock"
        )
    raise ValueError(f"unknown provider={name!r}; choose one of {KNOWN_PROVIDERS}")


def get_available_providers(
    *,
    brave_enabled: bool = False,
    brave_api_key: str = "",
    exa_api_key: str = "",
    tavily_api_key: str = "",
) -> list[SearchProvider]:
    """Return providers that have valid keys; mock only if none configured."""
    providers: list[SearchProvider] = []
    if exa_api_key:
        from providers.exa import ExaSearchProvider

        providers.append(ExaSearchProvider(exa_api_key))
    if tavily_api_key:
        from providers.tavily import TavilySearchProvider

        providers.append(TavilySearchProvider(tavily_api_key))
    # Brave live is not implemented yet — do not list it as available.
    _ = (brave_enabled, brave_api_key)
    if not providers:
        providers.append(MockBraveProvider())
    return providers


def available_provider_names(
    *,
    brave_enabled: bool = False,
    brave_api_key: str = "",
    exa_api_key: str = "",
    tavily_api_key: str = "",
) -> list[str]:
    return [
        p.name
        for p in get_available_providers(
            brave_enabled=brave_enabled,
            brave_api_key=brave_api_key,
            exa_api_key=exa_api_key,
            tavily_api_key=tavily_api_key,
        )
    ]
