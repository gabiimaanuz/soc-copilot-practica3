#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# Install systemd service + timer for healthcheck.sh (runs every 5 min).
#
#   bash /opt/soc-copilot/scripts/install_healthcheck_timer.sh
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="/opt/soc-copilot"
SCRIPT="${REPO_DIR}/scripts/healthcheck.sh"

sudo chmod +x "${SCRIPT}"

sudo tee /etc/systemd/system/soc-copilot-healthcheck.service >/dev/null <<EOF
[Unit]
Description=SOC Copilot - production healthcheck
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/env bash ${SCRIPT}
Nice=15
EOF

sudo tee /etc/systemd/system/soc-copilot-healthcheck.timer >/dev/null <<'EOF'
[Unit]
Description=SOC Copilot - healthcheck every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
AccuracySec=30s
Unit=soc-copilot-healthcheck.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now soc-copilot-healthcheck.timer

echo "==> timer installed"
sudo systemctl list-timers soc-copilot-healthcheck.timer --no-pager

cat <<'EOF'

────────────────────────────────────────────────────────────────────────────
 HEALTHCHECK TIMER INSTALLED — runs every 5 minutes
────────────────────────────────────────────────────────────────────────────

  Force a run now:
    sudo systemctl start soc-copilot-healthcheck.service
    sudo journalctl -u soc-copilot-healthcheck.service -n 30 --no-pager

  See all healthcheck events in journal:
    sudo journalctl -t soc-copilot-healthcheck -n 50 --no-pager

  Optional: enable email alerts by adding to /opt/soc-copilot/.env:
    HEALTHCHECK_NOTIFY_EMAIL=you@example.com
  (re-uses your existing SMTP_* config)

────────────────────────────────────────────────────────────────────────────
EOF
