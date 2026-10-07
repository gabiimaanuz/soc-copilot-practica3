#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# SOC Copilot — production healthcheck.
#
# Runs every 5 minutes via a systemd timer. Checks:
#   • All compose services are "Up"
#   • /api/health returns 200
#   • The web frontend returns 200
#   • The TLS certificate has > 14 days left
#
# On any failure: logs to journald (queryable later), and (if SMTP is
# configured and HEALTHCHECK_NOTIFY_EMAIL is set) sends one email.
# State-machine: notifies on transition OK→FAIL and FAIL→OK, NOT on every
# tick during a sustained outage (anti-spam). The state file lives at
# /var/lib/soc-copilot-healthcheck/state.
#
# Optional .env vars (all default to off):
#   HEALTHCHECK_NOTIFY_EMAIL   target inbox for alerts
#   HEALTHCHECK_TLS_WARN_DAYS  default 14
# Re-uses existing SMTP_* config to send mail.
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="/opt/soc-copilot"
ENV_FILE="${REPO_DIR}/.env"
COMPOSE_FILE="${REPO_DIR}/infra/docker-compose.prod.yml"
STATE_DIR="/var/lib/soc-copilot-healthcheck"
STATE_FILE="${STATE_DIR}/state"

read_env() {
  local key="$1"
  local val
  val="$(grep -E "^${key}=" "${ENV_FILE}" 2>/dev/null | tail -n1 | cut -d= -f2- || true)"
  val="${val%\"}"; val="${val#\"}"
  val="${val%\'}"; val="${val#\'}"
  printf '%s' "${val}"
}

PUBLIC_DOMAIN="$(read_env PUBLIC_DOMAIN)"
NOTIFY_EMAIL="$(read_env HEALTHCHECK_NOTIFY_EMAIL)"
TLS_WARN_DAYS="$(read_env HEALTHCHECK_TLS_WARN_DAYS)"
TLS_WARN_DAYS="${TLS_WARN_DAYS:-14}"

SMTP_HOST="$(read_env SMTP_HOST)"
SMTP_PORT="$(read_env SMTP_PORT)"
SMTP_USER="$(read_env SMTP_USER)"
SMTP_PASSWORD="$(read_env SMTP_PASSWORD)"
SMTP_FROM="$(read_env SMTP_FROM)"

mkdir -p "${STATE_DIR}"
[ -f "${STATE_FILE}" ] || echo "OK" > "${STATE_FILE}"
PREV_STATE="$(cat "${STATE_FILE}")"

failures=()

# ── 1) Container health ────────────────────────────────────────────────
expected=(postgres chroma api web caddy)
for svc in "${expected[@]}"; do
  status="$(docker compose -f "${COMPOSE_FILE}" ps --format '{{.Service}} {{.State}}' 2>/dev/null \
            | awk -v s="$svc" '$1==s {print $2}')"
  if [[ "${status}" != "running" ]]; then
    failures+=("container '${svc}' state='${status:-missing}'")
  fi
done

# ── 2) API health endpoint ─────────────────────────────────────────────
if [[ -n "${PUBLIC_DOMAIN}" ]]; then
  api_code="$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 8 \
              "https://${PUBLIC_DOMAIN}/api/health" || echo "000")"
  if [[ "${api_code}" != "200" ]]; then
    failures+=("/api/health HTTP ${api_code}")
  fi

  # ── 3) Frontend ──────────────────────────────────────────────────────
  web_code="$(curl -fsS -o /dev/null -w '%{http_code}' --max-time 8 \
              "https://${PUBLIC_DOMAIN}/" || echo "000")"
  if [[ "${web_code}" != "200" ]]; then
    failures+=("frontend HTTP ${web_code}")
  fi

  # ── 4) TLS expiry ────────────────────────────────────────────────────
  expiry_line="$(echo | openssl s_client -servername "${PUBLIC_DOMAIN}" \
                 -connect "${PUBLIC_DOMAIN}:443" 2>/dev/null \
                 | openssl x509 -noout -enddate 2>/dev/null || true)"
  if [[ -n "${expiry_line}" ]]; then
    expiry_ts="$(date -d "${expiry_line#notAfter=}" +%s 2>/dev/null || echo 0)"
    now_ts="$(date +%s)"
    days_left=$(( (expiry_ts - now_ts) / 86400 ))
    if (( days_left < TLS_WARN_DAYS )); then
      failures+=("TLS cert expires in ${days_left} days")
    fi
  else
    failures+=("TLS cert unreadable")
  fi
fi

# ── State machine + notification ───────────────────────────────────────
if [[ ${#failures[@]} -eq 0 ]]; then
  CURR_STATE="OK"
  logger -t soc-copilot-healthcheck "healthcheck.ok"
  echo "OK"
else
  CURR_STATE="FAIL"
  msg="$(printf '%s\n' "${failures[@]}")"
  logger -t soc-copilot-healthcheck "healthcheck.fail: ${msg//$'\n'/ | }"
  echo "FAIL:" >&2
  printf '  - %s\n' "${failures[@]}" >&2
fi

send_email() {
  local subject="$1"
  local body="$2"
  if [[ -z "${NOTIFY_EMAIL}" || -z "${SMTP_HOST}" || -z "${SMTP_FROM}" ]]; then
    return 0
  fi
  python3 - "${SMTP_HOST}" "${SMTP_PORT:-587}" "${SMTP_USER}" \
            "${SMTP_PASSWORD}" "${SMTP_FROM}" "${NOTIFY_EMAIL}" \
            "${subject}" "${body}" <<'PY'
import smtplib, ssl, sys
from email.message import EmailMessage
host, port, user, pwd, sender, to, subject, body = sys.argv[1:]
msg = EmailMessage()
msg["Subject"] = subject
msg["From"] = sender
msg["To"] = to
msg.set_content(body)
ctx = ssl.create_default_context()
with smtplib.SMTP(host, int(port), timeout=10) as s:
    s.ehlo(); s.starttls(context=ctx); s.ehlo()
    if user and pwd:
        s.login(user, pwd)
    s.send_message(msg)
PY
}

if [[ "${PREV_STATE}" != "${CURR_STATE}" ]]; then
  if [[ "${CURR_STATE}" == "FAIL" ]]; then
    send_email "[SOC Copilot] ALERT — healthcheck failing" \
      "Server: ${PUBLIC_DOMAIN}
Time:   $(date -Iseconds)

Failures:
$(printf '  - %s\n' "${failures[@]}")

Investigate:
  ssh -p 2222 soc@<server>
  docker compose -f ${COMPOSE_FILE} ps
  docker compose -f ${COMPOSE_FILE} logs --tail=60 api caddy"
  else
    send_email "[SOC Copilot] RECOVERED — healthcheck back to OK" \
      "Server ${PUBLIC_DOMAIN} is healthy again at $(date -Iseconds)."
  fi
fi

echo "${CURR_STATE}" > "${STATE_FILE}"

# Exit non-zero on failure so `systemctl status` shows red.
[[ "${CURR_STATE}" == "OK" ]] || exit 1
