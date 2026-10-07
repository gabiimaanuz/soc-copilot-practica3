"""Input hardening helpers for unauthenticated endpoints.

Centralises normalisation and blocklists used by /auth/register and
/auth/check-email so the same rules can't drift between schemas and the
router. Everything here is dependency-free and side-effect-free.
"""
from __future__ import annotations

import time
import unicodedata

# Conservative starter list — covers the dominant disposable email
# providers used by junior-SOC drill submissions. Extend via env if you
# need more aggressive coverage; this is intentionally short to keep
# false positives near zero.
_DISPOSABLE_DOMAINS = frozenset(
    {
        "mailinator.com",
        "10minutemail.com",
        "10minutemail.net",
        "guerrillamail.com",
        "guerrillamail.info",
        "guerrillamail.biz",
        "guerrillamail.de",
        "yopmail.com",
        "trashmail.com",
        "tempmail.com",
        "temp-mail.org",
        "tempail.com",
        "throwawaymail.com",
        "fakeinbox.com",
        "sharklasers.com",
        "maildrop.cc",
        "getairmail.com",
        "mintemail.com",
        "dispostable.com",
    }
)

# Bidi-control / zero-width / formatting codepoints we strip from
# free-text fields. Stops audit-log injection via embedded CR/LF and
# RLO/LRO homograph display tricks on the admin user list.
_FORMAT_CONTROLS = frozenset(
    {
        0x200B, 0x200C, 0x200D, 0x200E, 0x200F,  # ZWSP, ZWNJ, ZWJ, LRM, RLM
        0x202A, 0x202B, 0x202C, 0x202D, 0x202E,  # LRE/RLE/PDF/LRO/RLO
        0x2066, 0x2067, 0x2068, 0x2069,           # bidi isolates
        0xFEFF,                                   # BOM / ZWNBSP
    }
)


def _strip_unsafe(s: str) -> str:
    return "".join(
        ch for ch in s
        if ord(ch) >= 0x20  # drop C0 controls (CR/LF/NUL/BEL/etc.)
        and ord(ch) != 0x7F  # drop DEL
        and ord(ch) not in _FORMAT_CONTROLS
    )


def normalize_email(email: str) -> str:
    """Lowercase + trim. Returns "" if input is unusable.

    Pydantic's EmailStr already normalises the local-part case in some
    versions but not consistently, and the domain part should always be
    case-folded since DNS is case-insensitive. We do both here so the
    DB uniqueness check can't be bypassed with ``Foo@x.com`` vs
    ``foo@x.com``.
    """
    if not email:
        return ""
    return email.strip().lower()


def sanitize_name(name: str) -> str:
    """NFC-normalise and strip control / bidi / zero-width characters.

    Keeps Unicode letters and common punctuation intact (so "José",
    "O'Brien", "李雷" all survive) but kills the characters attackers
    use to smuggle log-injection payloads or render lookalike strings.
    """
    if not name:
        return ""
    cleaned = unicodedata.normalize("NFC", name)
    cleaned = _strip_unsafe(cleaned)
    return cleaned.strip()


def is_disposable_email(email: str) -> bool:
    """True if the domain matches a known disposable-mail provider."""
    if "@" not in email:
        return False
    domain = email.rsplit("@", 1)[1].lower().strip()
    return domain in _DISPOSABLE_DOMAINS


def equalize_timing(started_at: float, min_seconds: float = 0.15) -> None:
    """Block until at least ``min_seconds`` have elapsed since started_at.

    Used to flatten response-time differences on email-enumeration
    endpoints. The slack only kicks in when the real path was faster
    than the floor — we never slow down a path that was already slow,
    so this can't be used to amplify a DoS.
    """
    elapsed = time.monotonic() - started_at
    remaining = min_seconds - elapsed
    if remaining > 0:
        time.sleep(remaining)
