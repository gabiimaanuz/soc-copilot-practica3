#!/usr/bin/env bash
# ────────────────────────────────────────────────────────────────────────────
# SOC Copilot — Hetzner host hardening (Ubuntu/Debian).
#
# Run ONCE on a fresh VPS as root (or with sudo). Idempotent: safe to re-run.
#
#   curl -fsSL https://your-repo/raw/main/scripts/harden_server.sh | sudo bash
#   # or:
#   sudo bash /opt/soc-copilot/scripts/harden_server.sh
#
# What it does:
#   • Creates a non-root user `soc` with sudo + docker group.
#   • Hardens SSH (no root, no password, custom port).
#   • Installs UFW firewall (deny incoming except SSH/HTTP/HTTPS).
#   • Installs fail2ban for SSH brute-force protection.
#   • Enables unattended-upgrades for automatic security patches.
#   • Configures kernel sysctl hardening.
#   • Sets up basic auditd logging (useful for the SOC demo).
#
# Configurable via env vars:
#   SSH_PORT (default 2222)
#   NEW_USER (default soc)
#   ADMIN_PUBKEY  (REQUIRED — your laptop's id_ed25519.pub contents)
# ────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SSH_PORT="${SSH_PORT:-2222}"
NEW_USER="${NEW_USER:-soc}"
ADMIN_PUBKEY="${ADMIN_PUBKEY:-}"

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: run as root (use sudo)." >&2
  exit 1
fi

if [[ -z "$ADMIN_PUBKEY" ]]; then
  echo "ERROR: ADMIN_PUBKEY env var is required." >&2
  echo "  Example:  ADMIN_PUBKEY=\"ssh-ed25519 AAAA... you@host\" sudo -E bash $0" >&2
  exit 1
fi

echo "==> [1/8] apt update + base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y --no-install-recommends \
  ufw fail2ban unattended-upgrades apt-listchanges \
  ca-certificates curl gnupg sudo auditd

echo "==> [2/8] create user '${NEW_USER}' with sudo + docker"
if ! id "${NEW_USER}" &>/dev/null; then
  adduser --disabled-password --gecos "" "${NEW_USER}"
fi
usermod -aG sudo "${NEW_USER}"
getent group docker >/dev/null || groupadd docker
usermod -aG docker "${NEW_USER}"

# Passwordless sudo for deploys (the user still needs SSH key to log in).
echo "${NEW_USER} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/90-${NEW_USER}"
chmod 0440 "/etc/sudoers.d/90-${NEW_USER}"

# Install the admin SSH key.
install -d -m 700 -o "${NEW_USER}" -g "${NEW_USER}" "/home/${NEW_USER}/.ssh"
echo "${ADMIN_PUBKEY}" > "/home/${NEW_USER}/.ssh/authorized_keys"
chown "${NEW_USER}:${NEW_USER}" "/home/${NEW_USER}/.ssh/authorized_keys"
chmod 600 "/home/${NEW_USER}/.ssh/authorized_keys"

echo "==> [3/8] harden sshd (port ${SSH_PORT}, no root, no password)"
SSHD_DROPIN="/etc/ssh/sshd_config.d/99-soc-hardening.conf"
cat > "${SSHD_DROPIN}" <<EOF
# Managed by harden_server.sh
Port ${SSH_PORT}
PermitRootLogin no
PasswordAuthentication no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
UsePAM yes
PubkeyAuthentication yes
PermitEmptyPasswords no
X11Forwarding no
AllowAgentForwarding no
AllowTcpForwarding no
MaxAuthTries 3
LoginGraceTime 20
ClientAliveInterval 300
ClientAliveCountMax 2
AllowUsers ${NEW_USER}
EOF
# Validate before reload to avoid locking ourselves out.
sshd -t -f /etc/ssh/sshd_config
systemctl reload ssh || systemctl reload sshd

echo "==> [4/8] UFW firewall"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow "${SSH_PORT}/tcp" comment 'SSH'
ufw allow 80/tcp  comment 'HTTP (Caddy ACME)'
ufw allow 443/tcp comment 'HTTPS'
ufw allow 443/udp comment 'HTTP/3 (QUIC)'
ufw --force enable

echo "==> [5/8] fail2ban (SSH jail)"
cat > /etc/fail2ban/jail.d/soc.local <<EOF
[DEFAULT]
bantime  = 1h
findtime = 10m
maxretry = 5
backend  = systemd

[sshd]
enabled  = true
port     = ${SSH_PORT}
EOF
systemctl enable --now fail2ban
systemctl restart fail2ban

echo "==> [6/8] unattended-upgrades (security only, auto-reboot 04:00)"
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'EOF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT::Periodic::AutocleanInterval "7";
EOF
cat > /etc/apt/apt.conf.d/50unattended-upgrades.local <<'EOF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "04:00";
Unattended-Upgrade::Remove-Unused-Dependencies "true";
EOF
systemctl enable --now unattended-upgrades

echo "==> [7/8] kernel sysctl hardening"
cat > /etc/sysctl.d/99-soc-hardening.conf <<'EOF'
# Network hardening
net.ipv4.conf.all.rp_filter = 1
net.ipv4.conf.default.rp_filter = 1
net.ipv4.icmp_echo_ignore_broadcasts = 1
net.ipv4.icmp_ignore_bogus_error_responses = 1
net.ipv4.conf.all.accept_source_route = 0
net.ipv4.conf.all.accept_redirects = 0
net.ipv4.conf.all.secure_redirects = 0
net.ipv4.conf.all.send_redirects = 0
net.ipv4.conf.all.log_martians = 1
net.ipv4.tcp_syncookies = 1
net.ipv6.conf.all.accept_redirects = 0
net.ipv6.conf.all.accept_source_route = 0
# Filesystem
fs.protected_hardlinks = 1
fs.protected_symlinks = 1
fs.protected_fifos = 2
fs.protected_regular = 2
# Kernel
kernel.dmesg_restrict = 1
kernel.kptr_restrict = 2
kernel.randomize_va_space = 2
EOF
sysctl --system >/dev/null

echo "==> [8/8] auditd (basic SOC-relevant rules)"
cat > /etc/audit/rules.d/soc.rules <<'EOF'
# Watch sudoers + ssh config for tampering
-w /etc/sudoers -p wa -k sudoers
-w /etc/sudoers.d/ -p wa -k sudoers
-w /etc/ssh/sshd_config -p wa -k sshd_config
-w /etc/ssh/sshd_config.d/ -p wa -k sshd_config
# Watch passwd/shadow
-w /etc/passwd -p wa -k identity
-w /etc/shadow -p wa -k identity
# Docker state
-w /var/lib/docker -p wa -k docker
EOF
augenrules --load || true
systemctl enable --now auditd

cat <<EOF

────────────────────────────────────────────────────────────────────────────
 HARDENING COMPLETE
────────────────────────────────────────────────────────────────────────────
  SSH:        port ${SSH_PORT}, key-only, user '${NEW_USER}'
  Firewall:   UFW active (${SSH_PORT}/tcp, 80, 443)
  Brute force: fail2ban watching sshd
  Patches:    unattended-upgrades enabled (auto-reboot 04:00)
  Audit:      auditd logging sudoers/ssh/passwd/docker

  TEST A NEW SSH SESSION BEFORE CLOSING THIS ONE:
    ssh -p ${SSH_PORT} ${NEW_USER}@<server-ip>

  Next: clone the repo into /opt/soc-copilot, populate .env, run deploy.sh.
────────────────────────────────────────────────────────────────────────────
EOF
