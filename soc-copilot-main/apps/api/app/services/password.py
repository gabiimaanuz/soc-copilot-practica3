"""Server-side password strength rules.

The frontend runs zxcvbn for the live strength meter, but we DON'T trust
that — the same rules are enforced here before hashing. zxcvbn-style
scoring (0-4) is approximated from character classes + length so the
server can return a structured failure the UI can render the same way
as the live meter, without depending on the JS heuristics.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MIN_LENGTH = 10
MAX_LENGTH = 128

_LOWER = re.compile(r"[a-z]")
_UPPER = re.compile(r"[A-Z]")
_DIGIT = re.compile(r"\d")
_SYMBOL = re.compile(r"[^A-Za-z0-9]")

# Tiny block-list of passwords we still see in junior SOC labs.
_COMMON = frozenset(
    {
        "password",
        "password1",
        "password123",
        "qwerty",
        "qwerty123",
        "12345678",
        "123456789",
        "1234567890",
        "letmein",
        "admin",
        "admin123",
        "soc",
        "soccopilot",
        "blueteam",
    }
)


@dataclass
class StrengthResult:
    ok: bool
    score: int  # 0-4, zxcvbn-compatible scale
    failed: list[str]  # human-readable Spanish messages

    def first_error(self) -> str:
        return self.failed[0] if self.failed else "contraseña inválida"


def check_password(password: str, *, email: str | None = None) -> StrengthResult:
    failed: list[str] = []
    if len(password) < MIN_LENGTH:
        failed.append(f"Debe tener al menos {MIN_LENGTH} caracteres.")
    if len(password) > MAX_LENGTH:
        failed.append(f"No puede superar los {MAX_LENGTH} caracteres.")
    if not _LOWER.search(password):
        failed.append("Debe incluir una minúscula.")
    if not _UPPER.search(password):
        failed.append("Debe incluir una mayúscula.")
    if not _DIGIT.search(password):
        failed.append("Debe incluir un dígito.")
    if not _SYMBOL.search(password):
        failed.append("Debe incluir un símbolo.")
    if password.lower() in _COMMON:
        failed.append("Contraseña demasiado común.")
    if email:
        local = email.split("@", 1)[0].lower()
        if local and len(local) >= 4 and local in password.lower():
            failed.append("No puede contener tu email.")

    # Rough zxcvbn-compatible score from the rules above + length bonus.
    classes = sum(
        bool(rx.search(password)) for rx in (_LOWER, _UPPER, _DIGIT, _SYMBOL)
    )
    if len(password) < 8:
        score = 0
    elif len(password) < 10:
        score = 1
    elif classes <= 2:
        score = 2
    elif classes == 3:
        score = 3
    else:
        score = 4
    if failed:
        score = min(score, 2)

    return StrengthResult(ok=not failed, score=score, failed=failed)


REQUIREMENTS_ES = [
    "Al menos 10 caracteres",
    "Incluye mayúscula",
    "Incluye minúscula",
    "Incluye dígito",
    "Incluye símbolo",
]
