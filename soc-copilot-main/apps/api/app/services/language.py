"""Response language selection (Práctica 2 — roadmap #6, ES/EN).

How the output language of the LLM is chosen, in order:

1. **Detected** language of the analyst's own text (chat question) when the
   detector is confident — so someone typing in English gets English even
   with the UI in Spanish.
2. **Explicit** ``language`` field in the request body (``es``/``en``/``fr``).
3. **UI language** sent by the frontend in ``Accept-Language`` (the
   frontend overrides the browser default with the locale chosen in the
   top bar; on first visit that locale is auto-detected from the browser).
4. ``DEFAULT_LANGUAGE`` (Spanish).

Logs are NOT used for detection: they are almost always English/technical
regardless of the analyst's language.

The detector is a dependency-free stop-word scorer. It is deliberately
conservative: short or ambiguous text returns ``None`` and the request
falls back to the UI language.
"""
from __future__ import annotations

import re

from fastapi import Request

SUPPORTED = ("es", "en", "fr")
DEFAULT_LANGUAGE = "es"

_STOPWORDS: dict[str, frozenset[str]] = {
    "es": frozenset(
        """de la que el en y a los se del las por un para con no una su al lo
        como más pero sus le ya o este sí porque esta entre cuando muy sin sobre
        también me hasta hay donde quien desde todo nos durante todos uno les ni
        contra otros ese eso ante ellos e esto mí antes algunos qué unos yo otro
        otras otra él cuál cómo dónde por qué es son está están hacer debo puedo
        tengo ataque alerta explica explícame dime""".split()
    ),
    "en": frozenset(
        """the of and to in is you that it he was for on are as with his they at
        be this have from or one had by word but not what all were we when your
        can said there use an each which she do how their if will up other about
        out many then them these so some her would make like him into time has
        look two more write go see no way could people my than first been call
        who its now find long down day did get come made may part should does
        why where attack alert explain tell me""".split()
    ),
    "fr": frozenset(
        """le la les de des du un une et est en que qui dans pour pas sur au aux
        avec ce cette ces il elle ils nous vous je tu ne se son sa ses mais ou
        donc car comment pourquoi quoi quel quelle est-ce être avoir fait faire
        attaque alerte explique""".split()
    ),
}
_ACCENT_HINTS = {
    "es": re.compile(r"[ñ¿¡áíóú]"),
    "fr": re.compile(r"[èêàçùœâîôû]"),
}
_WORD_RE = re.compile(r"[a-záéíóúñüçèêàùœâîôûë'-]+", re.IGNORECASE)


def detect_language(text: str | None, *, min_words: int = 3) -> str | None:
    """Return ``es``/``en``/``fr`` if confident, else ``None``."""
    if not text:
        return None
    words = _WORD_RE.findall(text.lower())
    if len(words) < min_words:
        return None
    scores = {lang: sum(1 for w in words if w in sw) for lang, sw in _STOPWORDS.items()}
    for lang, rx in _ACCENT_HINTS.items():
        scores[lang] += 2 * len(rx.findall(text.lower()))
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (best, top), (_, second) = ranked[0], ranked[1]
    # Need at least 2 hits and a clear margin over the runner-up.
    if top < 2 or top < second * 1.5 or top == second:
        return None
    return best


def _normalize(code: str | None) -> str | None:
    if not code:
        return None
    primary = code.strip().lower().replace("_", "-").split("-")[0]
    return primary if primary in SUPPORTED else None


def preferred_from_request(request: Request | None) -> str | None:
    """First supported language in the Accept-Language header."""
    if request is None:
        return None
    header = request.headers.get("accept-language", "")
    for part in header.split(","):
        lang = _normalize(part.split(";")[0])
        if lang:
            return lang
    return None


def resolve_language(
    explicit: str | None = None,
    request: Request | None = None,
    text: str | None = None,
) -> str:
    detected = detect_language(text)
    if detected:
        return detected
    if explicit and explicit != "auto":
        lang = _normalize(explicit)
        if lang:
            return lang
    return preferred_from_request(request) or DEFAULT_LANGUAGE


_INSTRUCTIONS = {
    "es": (
        "IDIOMA DE SALIDA: responde SIEMPRE en español en todos los campos de "
        "texto. Mantén sin traducir los IDs MITRE/OWASP, comandos, rutas, "
        "nombres de campos JSON y valores de enumeraciones."
    ),
    "en": (
        "OUTPUT LANGUAGE: always answer in English in every text field, even "
        "though these instructions are written in Spanish. Keep MITRE/OWASP "
        "IDs, commands, paths, JSON field names and enum values unchanged."
    ),
    "fr": (
        "LANGUE DE SORTIE : réponds TOUJOURS en français dans tous les champs "
        "de texte, même si ces instructions sont en espagnol. Ne traduis pas "
        "les IDs MITRE/OWASP, commandes, chemins, noms de champs JSON ni "
        "valeurs d'énumération."
    ),
}


def with_language(system_prompt: str, language: str | None) -> str:
    """Append the output-language block (last, so it wins over the body)."""
    lang = _normalize(language) or DEFAULT_LANGUAGE
    return f"{system_prompt}\n\n{_INSTRUCTIONS[lang]}"
