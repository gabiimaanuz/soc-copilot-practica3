"""Defence-in-depth Origin / Referer check for state-changing auth POSTs.

SameSite=Lax on the session cookie already blocks classic CSRF, and the
CORS middleware refuses credentialed XHR from non-allowlisted origins.
This check covers the remaining gaps:

* Same-site POSTs from a compromised sibling subdomain.
* Forged Origin headers from a non-browser tool (curl/scripts) — those
  carry no Origin/Referer, so we let them through (the rate-limit
  bucket + bcrypt cost are the real defence against scripted abuse).

So the policy is: if an Origin/Referer header IS present, it MUST match
the configured allowlist. If absent (non-browser caller), we don't
block — that path is already gated by /auth's strict rate limit.
"""
from __future__ import annotations

from urllib.parse import urlparse

from fastapi import HTTPException, Request, status

from app.config import get_settings


def enforce_same_origin(request: Request) -> None:
    settings = get_settings()
    allowed = {o.rstrip("/") for o in settings.cors_origins_list}
    if not allowed:
        return

    origin = request.headers.get("origin")
    referer = request.headers.get("referer")

    if origin:
        if origin.rstrip("/") not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="origin not allowed",
            )
        return

    if referer:
        parsed = urlparse(referer)
        # Reduce the referer down to <scheme>://<netloc> for comparison;
        # the path is irrelevant for origin policy.
        base = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
        if base not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="referer not allowed",
            )
