#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# Installs the systemd service+timer for backup_postgres.sh and runs it once
# to validate. Run on the Hetzner host as a user with sudo.
#
#   bash /opt/soc-copilot/scripts/install_backup_timer.sh
#
# Pre-reqs (the script installs them if missing): age, rclone (only if you
# plan to use offsite — safe to keep installed even if unused).
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

REPO_DIR="/opt/soc-copilot"
BACKUP_SCRIPT="${REPO_DIR}/scripts/backup_postgres.sh"

if [[ ! -x "${BACKUP_SCRIPT}" ]]; then
  sudo chmod +x "${BACKUP_SCRIPT}"
fi

echo "==> install age + rclone (offsite optional)"
sudo apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends age rclone

echo "==> systemd unit + timer"
sudo tee /etc/systemd/system/soc-copilot-backup.service >/dev/null <<EOF
[Unit]
Description=SOC Copilot - encrypted Postgres backup
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/env bash ${BACKUP_SCRIPT}
Nice=10
IOSchedulingClass=best-effort
IOSchedulingPriority=7
EOF

sudo tee /etc/systemd/system/soc-copilot-backup.timer >/dev/null <<'EOF'
[Unit]
Description=SOC Copilot - daily backup at 03:30

[Timer]
OnCalendar=*-*-* 03:30:00
Persistent=true
RandomizedDelaySec=5m
Unit=soc-copilot-backup.service

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now soc-copilot-backup.timer

echo "==> timer status"
sudo systemctl list-timers soc-copilot-backup.timer --no-pager

cat <<'EOF'

────────────────────────────────────────────────────────────────────────────
 BACKUP TIMER INSTALLED — runs daily at 03:30 (with up to 5min jitter)
────────────────────────────────────────────────────────────────────────────

  Force a test run now:
    sudo systemctl start soc-copilot-backup.service
    sudo journalctl -u soc-copilot-backup.service -n 50 --no-pager
    ls -lh /var/backups/soc-copilot/daily/

  Restore drill (CRITICAL — do this once before you need it):
    See: docs/ops/restore-postgres.md

────────────────────────────────────────────────────────────────────────────
EOF
