"""OWASP Top 10 (2025) — curated entries with descriptions condensed
from the official project. Used as part of the RAG knowledge base.
"""
from __future__ import annotations

OWASP_TOP_10_2025 = [
    {
        "id": "A01:2025",
        "name": "Broken Access Control",
        "description": (
            "Restrictions on what authenticated users are allowed to do are "
            "not enforced. Remains #1 in 2025 and now absorbs Server-Side "
            "Request Forgery (SSRF), previously A10:2021. Common failures: "
            "violation of least privilege, bypassing access checks via URL "
            "tampering or parameter manipulation, elevation of privilege "
            "(acting as another user or as admin), CORS misconfiguration "
            "that allows API access from unauthorized origins, IDOR "
            "(Insecure Direct Object References), missing function-level "
            "access control, force browsing to authenticated pages, and "
            "SSRF where the app fetches user-supplied URLs without "
            "validation (internal metadata services, port scanning, "
            "DNS rebinding). Enforce access control on the server side, "
            "deny by default, log access control failures, rate-limit API "
            "and controller access, invalidate session/JWT tokens on "
            "logout, validate and allow-list URL schemas/ports/destinations."
        ),
        "tags": [
            "access-control",
            "idor",
            "privilege-escalation",
            "authz",
            "ssrf",
        ],
    },
    {
        "id": "A02:2025",
        "name": "Security Misconfiguration",
        "description": (
            "Moves up from #5 (2021) to #2 in 2025, reflecting the growing "
            "complexity of cloud, container, and IaC environments. The "
            "application or stack is missing security hardening, has "
            "unnecessary features enabled (services, ports, accounts), "
            "default accounts with default passwords, verbose error "
            "messages that reveal stack traces, disabled security features, "
            "software out of date, cloud services with overly permissive "
            "IAM policies or public buckets, missing security headers "
            "(CSP, HSTS, X-Content-Type-Options). Mitigations: hardened "
            "build process repeatable for any environment, minimal "
            "platform without unnecessary features, review configurations "
            "in IaC (Terraform, Helm) with policy-as-code, segmented "
            "architecture, automated configuration scanning (CSPM, KSPM)."
        ),
        "tags": [
            "config",
            "hardening",
            "headers",
            "default-credentials",
            "cloud",
            "iac",
        ],
    },
    {
        "id": "A03:2025",
        "name": "Software Supply Chain Failures",
        "description": (
            "NEW and expanded category in 2025 that replaces and broadens "
            "A06:2021 'Vulnerable and Outdated Components'. Covers "
            "breakdowns or compromises in the process of building, "
            "distributing, or updating software: malicious or vulnerable "
            "third-party dependencies (npm, PyPI, Maven typosquatting), "
            "compromised build systems and CI/CD pipelines, lack of SBOM, "
            "unsigned artifacts, dependency confusion, malicious "
            "maintainer takeovers, compromised container base images. "
            "Mitigations: maintain SBOMs (CycloneDX, SPDX), pin and verify "
            "dependencies, sign artifacts (Sigstore/cosign), use SLSA "
            "framework, isolate CI/CD with least privilege, scan with "
            "Trivy/Snyk/Dependabot, only consume components from official "
            "sources over secure links, subscribe to advisories."
        ),
        "tags": [
            "supply-chain",
            "sbom",
            "dependencies",
            "ci-cd",
            "cve",
            "slsa",
        ],
    },
    {
        "id": "A04:2025",
        "name": "Cryptographic Failures",
        "description": (
            "Failures related to cryptography that lead to exposure of "
            "sensitive data. Key issues: data transmitted in clear text "
            "(HTTP, SMTP, FTP), use of old or weak algorithms (MD5, SHA1, "
            "DES, RC4), default or weak keys, missing encryption at rest, "
            "no key rotation, improper certificate validation, weak random "
            "number generation. Mitigations: classify data, encrypt in "
            "transit (TLS 1.2+, preferably 1.3) and at rest, use strong "
            "adaptive password hashing (Argon2id, bcrypt, scrypt, PBKDF2), "
            "authenticated encryption (AES-GCM/ChaCha20-Poly1305), proper "
            "key management (HSM, KMS), disable caching for sensitive "
            "responses, and start planning for post-quantum cryptography."
        ),
        "tags": [
            "crypto",
            "tls",
            "hashing",
            "encryption",
            "secrets",
            "post-quantum",
        ],
    },
    {
        "id": "A05:2025",
        "name": "Injection",
        "description": (
            "An application is vulnerable when user data is not validated, "
            "filtered, or sanitized; dynamic queries or non-parameterized "
            "calls reach an interpreter directly; or hostile data is "
            "concatenated. Includes SQL injection, NoSQL injection, OS "
            "command injection, ORM injection, LDAP injection, EL/OGNL "
            "injection, XSS, and increasingly prompt injection against "
            "LLM-backed features. Prevent with safe APIs that avoid the "
            "interpreter (parameterized queries, prepared statements, ORM "
            "with bind variables), positive server-side input validation, "
            "context-aware output escaping, LIMIT and other SQL controls "
            "to prevent mass disclosure, SAST/DAST in CI, and strict "
            "system prompts plus output filtering for LLM tool use."
        ),
        "tags": [
            "injection",
            "sqli",
            "xss",
            "nosql",
            "command-injection",
            "prompt-injection",
        ],
    },
    {
        "id": "A06:2025",
        "name": "Insecure Design",
        "description": (
            "Risks related to design and architectural flaws that cannot "
            "be patched away by a perfect implementation if the design "
            "itself is wrong. Examples: missing or ineffective control "
            "design (no rate limiting on login, no MFA where needed), "
            "business logic flaws, lack of segmentation, plaintext "
            "password storage, credential stuffing windows, abusable "
            "workflows. Mitigations: establish a secure development "
            "lifecycle with AppSec partnership, threat modeling (STRIDE, "
            "PASTA, attack trees), libraries of secure design patterns, "
            "segregate tier layers (network, container, identity), limit "
            "resource consumption per user/tenant, abuse-case testing."
        ),
        "tags": [
            "design",
            "threat-modeling",
            "secure-sdlc",
            "business-logic",
        ],
    },
    {
        "id": "A07:2025",
        "name": "Authentication Failures",
        "description": (
            "Renamed from 'Identification and Authentication Failures' in "
            "2021. Confirming user identity, authentication, and session "
            "management are critical. Failures include permitting "
            "credential stuffing, brute force or other automated attacks, "
            "weak default or well-known passwords (admin/admin), weak "
            "credential recovery, plaintext or weakly hashed passwords, "
            "missing or ineffective MFA, session ID exposure in URLs, no "
            "session invalidation, weak OAuth/OIDC flows. Mitigations: "
            "implement phishing-resistant MFA (WebAuthn/passkeys) where "
            "possible, do not ship default credentials, weak-password "
            "checks, align policy with NIST SP 800-63B, server-side "
            "secure session manager that rotates the session ID after "
            "login, anomaly detection on auth endpoints."
        ),
        "tags": [
            "auth",
            "session",
            "mfa",
            "passkeys",
            "credential-stuffing",
            "password",
        ],
    },
    {
        "id": "A08:2025",
        "name": "Software or Data Integrity Failures",
        "description": (
            "Code, infrastructure, and data that do not protect against "
            "integrity violations at the artifact or runtime level (lower "
            "level than supply-chain). Includes apps relying on plugins, "
            "libraries, or modules without verification; insecure "
            "deserialization; auto-update without integrity verification; "
            "unsigned serialized data sent to untrusted clients; "
            "tampering with model weights or training data in ML/AI "
            "pipelines. Mitigations: digital signatures or similar "
            "mechanisms to verify software and data origin, integrity "
            "checks on serialized data, verified update channels, "
            "segregation and access control on CI/CD, hash/sign model "
            "artifacts and datasets used by AI features."
        ),
        "tags": [
            "integrity",
            "deserialization",
            "signatures",
            "ci-cd",
            "ml-integrity",
        ],
    },
    {
        "id": "A09:2025",
        "name": "Security Logging & Alerting Failures",
        "description": (
            "Renamed in 2025 to emphasize alerting, not just logging. "
            "Logging and monitoring, coupled with incident response, are "
            "essential. Failures: auditable events (logins, failed "
            "logins, high-value transactions, admin actions) not logged; "
            "warnings and errors with no or unclear messages; logs not "
            "monitored for suspicious activity; logs stored only locally; "
            "missing alerting thresholds and escalation; pentests and "
            "DAST scans do not trigger alerts; inability to detect or "
            "alert on active attacks in real or near real time. "
            "Mitigations: log all auth, access-control, and input "
            "validation failures with sufficient user context; ship logs "
            "to a centralized SIEM with retention for forensics; encode "
            "log data to prevent log-injection; define alert thresholds "
            "and runbooks; adopt an incident response and recovery plan."
        ),
        "tags": [
            "logging",
            "alerting",
            "monitoring",
            "siem",
            "incident-response",
            "audit",
        ],
    },
    {
        "id": "A10:2025",
        "name": "Mishandling of Exceptional Conditions",
        "description": (
            "NEW category for 2025. Covers ~24 CWEs around improper "
            "error handling, logical errors, fail-open behavior, and "
            "other issues that arise from abnormal conditions: "
            "unhandled exceptions revealing stack traces or internal "
            "state, fail-open authorization (granting access when an "
            "auth check throws), missing checks on return values, "
            "race conditions and TOCTOU bugs, partial failures that "
            "leave the system in an inconsistent state, retries that "
            "amplify errors. Mitigations: fail closed/safe by default, "
            "centralized error handling that does not leak internals, "
            "explicit checks on all return values and exceptions, "
            "transactional or compensating logic for partial failures, "
            "fuzzing and chaos testing to surface exceptional paths, "
            "code review focused on error and edge-case handling."
        ),
        "tags": [
            "error-handling",
            "fail-safe",
            "race-condition",
            "toctou",
            "resilience",
        ],
    },
]

# Backwards-compatible alias so existing imports keep working during the
# 2021 -> 2025 migration. Prefer OWASP_TOP_10_2025 in new code.
OWASP_TOP_10_2021 = OWASP_TOP_10_2025
