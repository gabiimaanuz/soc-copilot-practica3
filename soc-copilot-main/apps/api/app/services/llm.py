"""LLM adapter — keep call sites provider-agnostic.

Currently wires Gemini via google-genai. Swappable to Claude/OpenAI/Ollama
by adding a sibling adapter and selecting via settings.

Phase 5 — Bring-your-own-key
============================
Each user can store their own Gemini API key (encrypted). When they have
one we instantiate a per-user adapter and route their calls through it.
Otherwise we fall back to the SHARED server key, throttled by a daily
per-user quota so a single user can't burn the whole project's quota.
``get_llm(user, db)`` is the new entry point. The old ``get_llm()`` with
no args still works for code paths that don't have a user (KB ingestion
scripts, tests).
"""
from __future__ import annotations

import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from google import genai
from google.genai import types
from sqlalchemy.orm import Session

from app.config import get_settings
from app.services.secrets import DecryptionError, decrypt

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """Base error for LLM provider failures."""


class LLMProviderError(LLMError):
    """The provider rejected the request (network, quota, auth)."""


class LLMResponseError(LLMError):
    """The provider replied but the payload could not be parsed/validated."""


class LLMQuotaExceeded(LLMError):
    """The per-user quota on the SHARED server key is exhausted."""


class LLMAdapter(ABC):
    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        system: str | None = None,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> dict[str, Any]: ...

    @abstractmethod
    def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> str: ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class GeminiAdapter(LLMAdapter):
    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        key = api_key or settings.gemini_api_key
        if not key or key in {"replace_me", "REPLACE_ME_WITH_FRESH_KEY"}:
            raise LLMProviderError("GEMINI_API_KEY is not configured")
        self._client = genai.Client(api_key=key)
        self._default_chat_model = settings.gemini_chat_model
        self._embed_model = settings.gemini_embed_model
        self._allowlist = set(settings.chat_models_list)

    def _resolve_chat_model(self, requested: str | None) -> str:
        if not requested:
            return self._default_chat_model
        if requested not in self._allowlist:
            # Soft-fail: log and fall back to default; routers validate
            # against the allowlist before reaching here, so this branch is
            # only ever hit if internal callers pass an unknown model.
            logger.warning(
                "requested model %r not in allowlist, using default %r",
                requested,
                self._default_chat_model,
            )
            return self._default_chat_model
        return requested

    def generate_json(
        self,
        prompt: str,
        *,
        schema: dict[str, Any],
        system: str | None = None,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> dict[str, Any]:
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=schema,
            system_instruction=system,
            temperature=temperature,
        )
        try:
            response = self._client.models.generate_content(
                model=self._resolve_chat_model(model),
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            logger.exception("Gemini provider call failed")
            raise LLMProviderError(str(exc)) from exc

        text = getattr(response, "text", None)
        if not text:
            logger.error("Gemini returned empty payload: %r", response)
            raise LLMResponseError("empty reply")
        try:
            return json.loads(text)
        except (TypeError, ValueError) as exc:
            logger.exception("Gemini returned non-JSON payload: %r", text)
            raise LLMResponseError("non-json reply") from exc

    def generate_text(
        self,
        prompt: str,
        *,
        system: str | None = None,
        temperature: float = 0.2,
        model: str | None = None,
    ) -> str:
        config = types.GenerateContentConfig(
            system_instruction=system, temperature=temperature
        )
        try:
            response = self._client.models.generate_content(
                model=self._resolve_chat_model(model),
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            logger.exception("Gemini provider call failed (text)")
            raise LLMProviderError(str(exc)) from exc
        if not response.text:
            raise LLMResponseError("empty reply")
        return response.text

    def embed(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self._client.models.embed_content(
                model=self._embed_model, contents=texts
            )
        except Exception as exc:
            logger.exception("Gemini embed call failed")
            raise LLMProviderError(str(exc)) from exc
        return [e.values for e in response.embeddings]


# ── Server-key singleton (used as fallback when user has no BYO key) ────
_singleton: LLMAdapter | None = None


def get_llm() -> LLMAdapter:
    """Server-key adapter (no quota tracking).

    Kept for non-user contexts: KB ingestion scripts, tests with the
    dependency override, and the smoke suite.
    """
    global _singleton
    if _singleton is None:
        _singleton = GeminiAdapter()
    return _singleton


def reset_singleton() -> None:
    """Test helper — drop the cached adapter."""
    global _singleton
    _singleton = None


# ── Per-user adapter selection (BYO key + server-key quota) ─────────────


def _today_utc():
    return datetime.now(UTC).date()


def _enforce_server_quota(user, db: Session) -> None:
    """Track and enforce daily call budget for the SHARED server key.

    Counter rolls forward at the next UTC day. Increments happen only
    AFTER we decide to consume a call; rejecting before increment keeps
    the count meaningful even when downstream raises.
    """
    settings = get_settings()
    today = _today_utc()
    if user.server_llm_quota_date != today:
        user.server_llm_quota_date = today
        user.server_llm_calls_today = 0
    if user.server_llm_calls_today >= settings.server_llm_daily_quota:
        logger.warning(
            "llm.quota_exceeded",
            extra={
                "user_id": user.id,
                "calls_today": user.server_llm_calls_today,
                "limit": settings.server_llm_daily_quota,
            },
        )
        # 429 surfaces nicely in the frontend.
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "Daily AI call quota exhausted on the shared server key. "
                "Configure your own Gemini API key in Settings to keep going."
            ),
        )
    user.server_llm_calls_today += 1
    db.commit()


class _TimingAdapter(LLMAdapter):
    """Wrap an adapter to emit structured ``llm.call`` events with latency."""

    def __init__(self, inner: LLMAdapter, *, user_id: int | None, byo: bool) -> None:
        self._inner = inner
        self._user_id = user_id
        self._byo = byo

    def _emit(self, model: str | None, success: bool, started: float) -> None:
        logger.info(
            "llm.call",
            extra={
                "user_id": self._user_id,
                "model": model,
                "byo": self._byo,
                "latency_ms": int((time.monotonic() - started) * 1000),
                "success": success,
            },
        )

    def generate_json(self, prompt, *, schema, system=None, temperature=0.2, model=None):
        started = time.monotonic()
        try:
            result = self._inner.generate_json(
                prompt, schema=schema, system=system, temperature=temperature, model=model
            )
        except Exception:
            self._emit(model, False, started)
            raise
        self._emit(model, True, started)
        return result

    def generate_text(self, prompt, *, system=None, temperature=0.2, model=None):
        started = time.monotonic()
        try:
            result = self._inner.generate_text(
                prompt, system=system, temperature=temperature, model=model
            )
        except Exception:
            self._emit(model, False, started)
            raise
        self._emit(model, True, started)
        return result

    def embed(self, texts):
        return self._inner.embed(texts)


def get_llm_for_user(user, db: Session) -> LLMAdapter:
    """Return an adapter appropriate for ``user``.

    - If they configured their own key: decrypt and use a per-call
      adapter (no quota tracking, their own Google quota applies).
    - Otherwise: use the shared server adapter, but increment + enforce
      the daily per-user budget first.

    The ``user`` argument is the SQLAlchemy ``User`` row; we mutate it
    when bumping the quota counter and commit through ``db``.
    """
    user_id = user.id if user is not None else None
    if user is not None and user.gemini_api_key_ciphertext:
        try:
            api_key = decrypt(user.gemini_api_key_ciphertext)
        except DecryptionError:
            # Likely APP_ENCRYPTION_KEY rotated. Fall back to the server
            # key rather than blocking the user — log loudly so an admin
            # can prompt them to re-enter their key.
            logger.error(
                "llm.byo_decrypt_failed",
                extra={"user_id": user.id},
            )
        else:
            return _TimingAdapter(
                GeminiAdapter(api_key=api_key), user_id=user_id, byo=True
            )

    if user is not None:
        _enforce_server_quota(user, db)
    return _TimingAdapter(get_llm(), user_id=user_id, byo=False)
