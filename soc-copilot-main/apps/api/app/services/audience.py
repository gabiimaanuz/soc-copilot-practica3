"""Audience adaptation — turn the user's SOC seniority into a short block
appended to system prompts so chat/explain/recommend match the analyst's
level (L1 junior, L2 senior, INSTRUCTOR teacher).

The string is appended (not interpolated) so it can't accidentally
collide with the immutable security rules that live in the system
prompt body.
"""
from __future__ import annotations

from app.models import UserLevel

_LEVEL_GUIDANCE: dict[UserLevel, str] = {
    UserLevel.L1: (
        "Audiencia: analista junior (L1). Explica paso a paso, define "
        "siglas la primera vez que aparezcan, sugiere el siguiente "
        "comando o consulta concreta a ejecutar y recuerda los criterios "
        "para escalar. Prioriza claridad sobre brevedad."
    ),
    UserLevel.L2: (
        "Audiencia: analista senior (L2). Sé conciso y técnico: omite "
        "definiciones básicas, no repitas teoría conocida y ve directo al "
        "veredicto, los IoCs relevantes y la acción recomendada. Asume "
        "fluidez con MITRE ATT&CK y herramientas SOC habituales."
    ),
    UserLevel.INSTRUCTOR: (
        "Audiencia: instructor SOC. Da detalle completo sin filtros: "
        "incluye razonamiento alternativo, casuística de falsos "
        "positivos, referencias cruzadas a técnicas relacionadas y "
        "ejemplos pedagógicos. Adecuado para revisar respuestas con "
        "alumnos."
    ),
}


def audience_block(user=None) -> str:
    """Return the audience guidance line for ``user`` (or empty if no user).

    Safe to call with ``None`` — used in tests and admin/system flows
    where there is no authenticated analyst.
    """
    if user is None:
        return ""
    level = getattr(user, "level", None)
    if level is None:
        return ""
    return _LEVEL_GUIDANCE.get(level, "")


def with_audience(system_prompt: str, user=None) -> str:
    """Append the audience block to a base system prompt, if applicable."""
    block = audience_block(user)
    if not block:
        return system_prompt
    return f"{system_prompt}\n\n{block}"
