"""Práctica 2 · respuestas ES/EN con detección automática del idioma."""
from __future__ import annotations

import pytest
from starlette.requests import Request

from app.schemas.alerts import ChatMessage
from app.services import chat as chat_module
from app.services import explainer
from app.services.language import (
    detect_language,
    preferred_from_request,
    resolve_language,
    with_language,
)
from app.services.llm import LLMAdapter


def _req(accept_language: str | None) -> Request:
    headers = []
    if accept_language is not None:
        headers.append((b"accept-language", accept_language.encode()))
    return Request({"type": "http", "headers": headers})


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("¿Qué es un ataque de fuerza bruta y cómo lo detecto?", "es"),
        ("¿Es un falso positivo?", "es"),
        ("What is a brute force attack and how do I detect it?", "en"),
        ("Should I block this IP?", "en"),
        ("Comment détecter une attaque par force brute sur le serveur ?", "fr"),
        ("hola", None),
        ("T1110 sshd 4625", None),
        ("", None),
        (None, None),
    ],
)
def test_detect_language(text, expected):
    assert detect_language(text) == expected


def test_accept_language_parsing():
    assert preferred_from_request(_req("en-US,en;q=0.9")) == "en"
    assert preferred_from_request(_req("de-DE,fr;q=0.8")) == "fr"
    assert preferred_from_request(_req("de-DE")) is None
    assert preferred_from_request(_req(None)) is None


def test_resolution_order():
    # Detection of the analyst's text wins over everything.
    assert resolve_language("es", _req("es"), "Should I block this IP?") == "en"
    # Then the explicit body field.
    assert resolve_language("en", _req("es"), "ok") == "en"
    # "auto" falls through to the UI header.
    assert resolve_language("auto", _req("fr"), None) == "fr"
    # Default.
    assert resolve_language(None, None, None) == "es"


def test_with_language_appends_instruction_last():
    out = with_language("BASE", "en")
    assert out.startswith("BASE") and out.rstrip().endswith("unchanged.")
    assert "OUTPUT LANGUAGE" in out
    assert "IDIOMA DE SALIDA" in with_language("BASE", None)


class _Capture(LLMAdapter):
    system: str | None = None

    def generate_json(self, prompt, *, schema, system=None, temperature=0.2, model=None):
        _Capture.system = system
        return {"summary": "s", "risk_level": "low", "mitre_techniques": [], "reasoning": "r"}

    def generate_text(self, prompt, *, system=None, temperature=0.2, model=None):
        _Capture.system = system
        return "reply"

    def embed(self, texts):
        return [[0.0] for _ in texts]


class _NoKB:
    def retrieve(self, query, k=5):
        return []


def test_explainer_uses_requested_language():
    explainer.explain("log", llm=_Capture(), language="en")
    assert "OUTPUT LANGUAGE" in _Capture.system


def test_chat_autodetects_and_reports_language():
    r = chat_module.chat(
        [ChatMessage(role="user", content="What should I check first in this alert?")],
        llm=_Capture(),
        retriever=_NoKB(),
    )
    assert r.language == "en"
    assert "OUTPUT LANGUAGE" in _Capture.system
    assert "Responde en español" not in _Capture.system
