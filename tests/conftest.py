"""Shared test setup.

The tests (and the committed prediction caches they score) were written against the
Gemini provider. Since 2026-11-17 .env names LLM_PROVIDER=claude-code for real runs; a
setting in .env must not decide what a test exercises, so the provider is pinned here.
A test that needs another provider sets it itself (monkeypatch.setenv overrides this).
"""
import pytest


@pytest.fixture(autouse=True)
def _pin_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", "ollama")
