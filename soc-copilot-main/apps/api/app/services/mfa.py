"""MFA with TOTP (Práctica 2 — mejora 8.2, obligatoria para todos).

* TOTP per RFC 6238 (HMAC-SHA1, 6 digits, 30 s) implemented with the
  standard library — compatible with Google Authenticator, Microsoft
  Authenticator, Authy, FreeOTP, 1Password, Bitwarden…
* The shared secret is stored **encrypted** with Fernet
  (``APP_ENCRYPTION_KEY``, same mechanism as BYO Gemini keys).
* Anti-replay: the last accepted time-step is stored; a code can only be
  used once and never for an older step.
* 10 single-use recovery codes, stored as SHA-256 hashes.
* QR code rendered as a compact SVG with ReportLab's QR encoder (already a
  dependency for the PDF reports) — the secret never leaves the server in
  an image URL / third-party QR service.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

TOTP_DIGITS = 6
TOTP_PERIOD = 30
TOTP_WINDOW = 1  # accept codes from the previous/next 30 s step (clock drift)
RECOVERY_CODES = 10


# ─── TOTP core ──────────────────────────────────────────────────────────


def generate_secret() -> str:
    """160-bit random secret, base32 without padding (RFC 4226 §4)."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _b32decode(secret: str) -> bytes:
    s = secret.strip().replace(" ", "").upper()
    s += "=" * (-len(s) % 8)
    return base64.b32decode(s)


def hotp(secret: str, counter: int, digits: int = TOTP_DIGITS) -> str:
    key = _b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def current_step(now: float | None = None) -> int:
    return int((time.time() if now is None else now) // TOTP_PERIOD)


def totp(secret: str, now: float | None = None) -> str:
    return hotp(secret, current_step(now))


def verify_totp(
    secret: str,
    code: str,
    *,
    last_used_step: int | None = None,
    now: float | None = None,
    window: int = TOTP_WINDOW,
) -> int | None:
    """Return the matched time-step, or ``None`` if invalid/replayed."""
    code = (code or "").strip().replace(" ", "")
    if len(code) != TOTP_DIGITS or not code.isdigit():
        return None
    step = current_step(now)
    for candidate in range(step - window, step + window + 1):
        if last_used_step is not None and candidate <= last_used_step:
            continue  # replay or older code
        if hmac.compare_digest(hotp(secret, candidate), code):
            return candidate
    return None


def provisioning_uri(secret: str, account: str, issuer: str) -> str:
    label = f"{quote(issuer)}:{quote(account)}"
    return (
        f"otpauth://totp/{label}?secret={secret}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD}"
    )


# ─── Recovery codes ─────────────────────────────────────────────────────

_RC_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"  # no 0/o/1/l/i


def _normalize_rc(code: str) -> str:
    return "".join(ch for ch in (code or "").lower() if ch.isalnum())


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(_normalize_rc(code).encode()).hexdigest()


def generate_recovery_codes(n: int = RECOVERY_CODES) -> list[str]:
    """``xxxxx-xxxxx`` codes (~49 bits each)."""
    out = []
    for _ in range(n):
        raw = "".join(secrets.choice(_RC_ALPHABET) for _ in range(10))
        out.append(f"{raw[:5]}-{raw[5:]}")
    return out


def consume_recovery_code(hashes: list[str] | None, code: str) -> list[str] | None:
    """Return the remaining hashes if ``code`` matched, else ``None``."""
    if not hashes or not code:
        return None
    target = hash_recovery_code(code)
    for h in hashes:
        if hmac.compare_digest(h, target):
            remaining = list(hashes)
            remaining.remove(h)
            return remaining
    return None


# ─── QR (SVG) ───────────────────────────────────────────────────────────


def qr_svg(data: str, quiet_zone: int = 4) -> str:
    """Compact SVG (one path, run-length rows) of a QR code for ``data``."""
    from reportlab.graphics.barcode import qrencoder

    qr = qrencoder.QRCode(None, qrencoder.QRErrorCorrectLevel.M)
    qr.addData(data)
    qr.make()
    n = qr.getModuleCount()
    size = n + 2 * quiet_zone
    parts: list[str] = []
    for r in range(n):
        c = 0
        while c < n:
            if qr.isDark(r, c):
                start = c
                while c < n and qr.isDark(r, c):
                    c += 1
                w = c - start
                parts.append(f"M{start + quiet_zone} {r + quiet_zone}h{w}v1h-{w}z")
            else:
                c += 1
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" '
        f'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/>'
        f'<path fill="#000" d="{"".join(parts)}"/></svg>'
    )


def qr_data_uri(data: str) -> str:
    svg = qr_svg(data).encode("utf-8")
    return "data:image/svg+xml;base64," + base64.b64encode(svg).decode("ascii")
