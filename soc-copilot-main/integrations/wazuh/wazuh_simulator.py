#!/usr/bin/env python3
"""Simulador de alertas Wazuh para demos y pruebas (sin Wazuh real).

Envía alertas con el MISMO formato JSON que produce Wazuh (alerts.json)
al webhook de SOC Copilot, exactamente como lo haría integratord.

Uso:
    python integrations/wazuh/wazuh_simulator.py \
        --url http://localhost:8080/api/integrations/wazuh/webhook \
        --token "$WAZUH_WEBHOOK_TOKEN" --count 10 --interval 2

    # Repetir la última tanda para comprobar la deduplicación:
    python integrations/wazuh/wazuh_simulator.py ... --seed 42 --count 5
    python integrations/wazuh/wazuh_simulator.py ... --seed 42 --count 5

Solo usa la librería estándar.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

AGENTS = [
    {"id": "001", "name": "web-01", "ip": "10.0.0.5"},
    {"id": "002", "name": "db-01", "ip": "10.0.0.12"},
    {"id": "003", "name": "dc-01", "ip": "10.0.1.15"},
    {"id": "004", "name": "laptop-ana", "ip": "192.168.1.50"},
]
ATTACKERS = ["91.234.56.78", "203.0.113.45", "185.220.101.7", "45.155.205.233"]

# Plantillas basadas en reglas reales del ruleset de Wazuh.
TEMPLATES = [
    {
        "rule": {
            "id": "5712", "level": 10,
            "description": "sshd: brute force trying to get access to the system. Non existent user.",
            "groups": ["syslog", "sshd", "authentication_failures"],
            "mitre": {"id": ["T1110"], "tactic": ["Credential Access"], "technique": ["Brute Force"]},
            "firedtimes": 8,
        },
        "decoder": {"name": "sshd", "parent": "sshd"},
        "location": "/var/log/auth.log",
        "full_log": "{ts_sys} {agent} sshd[2211]: Failed password for invalid user admin from {src} port 52144 ssh2",
        "data": {"srcip": "{src}", "srcuser": "admin"},
    },
    {
        "rule": {
            "id": "31103", "level": 7,
            "description": "SQL injection attempt.",
            "groups": ["web", "accesslog", "attack", "sql_injection"],
            "mitre": {"id": ["T1190"], "tactic": ["Initial Access"], "technique": ["Exploit Public-Facing Application"]},
        },
        "decoder": {"name": "web-accesslog"},
        "location": "/var/log/nginx/access.log",
        "full_log": "{src} - - [{ts_web}] \"GET /products.php?id=1'+UNION+SELECT+username,password+FROM+users-- HTTP/1.1\" 200 512 \"-\" \"sqlmap/1.7\"",
        "data": {"srcip": "{src}", "url": "/products.php?id=1'+UNION+SELECT", "id": "200"},
    },
    {
        "rule": {
            "id": "550", "level": 7,
            "description": "Integrity checksum changed.",
            "groups": ["ossec", "syscheck", "syscheck_entry_modified"],
            "mitre": {"id": ["T1565.001"], "tactic": ["Impact"], "technique": ["Stored Data Manipulation"]},
        },
        "decoder": {"name": "syscheck_integrity_changed"},
        "location": "syscheck",
        "full_log": "File '/etc/passwd' modified\nMode: realtime\nChanged attributes: size,mtime,md5,sha1,sha256",
        "syscheck": {"path": "/etc/passwd", "event": "modified", "mode": "realtime"},
    },
    {
        "rule": {
            "id": "92213", "level": 12,
            "description": "Executable file dropped in folder commonly used by malware",
            "groups": ["sysmon", "sysmon_eid11_detections", "windows"],
            "mitre": {"id": ["T1105"], "tactic": ["Command and Control"], "technique": ["Ingress Tool Transfer"]},
        },
        "decoder": {"name": "windows_eventchannel"},
        "location": "EventChannel",
        "data": {"win": {"eventdata": {
            "image": "C:\\\\Windows\\\\System32\\\\WindowsPowerShell\\\\v1.0\\\\powershell.exe",
            "targetFilename": "C:\\\\Users\\\\Public\\\\upd.exe",
        }, "system": {"eventID": "11", "computer": "{agent}"}}},
    },
    {
        "rule": {
            "id": "100200", "level": 14,
            "description": "Possible ransomware activity: mass file encryption detected",
            "groups": ["local", "ransomware"],
            "mitre": {"id": ["T1486"], "tactic": ["Impact"], "technique": ["Data Encrypted for Impact"]},
        },
        "decoder": {"name": "windows_eventchannel"},
        "location": "EventChannel",
        "full_log": "Over 300 files renamed to *.locked in 60s by process C:\\Users\\Public\\upd.exe",
    },
    {
        # Por debajo del umbral por defecto (7) → debe ignorarse.
        "rule": {
            "id": "60122", "level": 5,
            "description": "Logon Failure - Unknown user or bad password",
            "groups": ["windows", "authentication_failed"],
            "mitre": {"id": ["T1078"], "tactic": ["Defense Evasion"], "technique": ["Valid Accounts"]},
        },
        "decoder": {"name": "windows_eventchannel"},
        "location": "EventChannel",
    },
]


def _fill(obj, ctx):
    if isinstance(obj, str):
        return obj.format(**ctx)
    if isinstance(obj, list):
        return [_fill(x, ctx) for x in obj]
    if isinstance(obj, dict):
        return {k: _fill(v, ctx) for k, v in obj.items()}
    return obj


def make_alert(rng: random.Random) -> dict:
    tpl = rng.choice(TEMPLATES)
    agent = rng.choice(AGENTS)
    now = datetime.now(UTC)
    epoch = now.timestamp()
    ctx = {
        "src": rng.choice(ATTACKERS),
        "agent": agent["name"],
        "ts_sys": now.strftime("%b %d %H:%M:%S"),
        "ts_web": now.strftime("%d/%b/%Y:%H:%M:%S +0000"),
    }
    alert = _fill(json.loads(json.dumps(tpl)), ctx)
    alert.update(
        {
            "timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}+0000",
            # Wazuh ids look like "<epoch>.<offset>"
            "id": f"{int(epoch)}.{rng.randint(100000, 999999)}",
            "agent": agent,
            "manager": {"name": "wazuh-manager"},
        }
    )
    return alert


def send(url: str, token: str, payload) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read() or b"{}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://localhost:8080/api/integrations/wazuh/webhook")
    ap.add_argument("--token", default=os.environ.get("WAZUH_WEBHOOK_TOKEN", ""))
    ap.add_argument("--count", type=int, default=5)
    ap.add_argument("--interval", type=float, default=1.0, help="segundos entre envíos")
    ap.add_argument("--batch", action="store_true", help="enviar todas en una sola petición")
    ap.add_argument("--seed", type=int, default=None, help="semilla para repetir alertas")
    ap.add_argument("--dry-run", action="store_true", help="imprimir JSON sin enviar")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    alerts = [make_alert(rng) for _ in range(args.count)]
    if args.seed is not None:
        # Ids deterministas para probar la deduplicación.
        for i, a in enumerate(alerts):
            a["id"] = f"sim-{args.seed}-{i}"

    if args.dry_run:
        print(json.dumps(alerts, indent=2, ensure_ascii=False))
        return 0
    if not args.token:
        print("Falta --token o WAZUH_WEBHOOK_TOKEN", file=sys.stderr)
        return 2

    try:
        if args.batch:
            print(send(args.url, args.token, alerts))
        else:
            for a in alerts:
                r = send(args.url, args.token, a)
                print(f"[{a['rule']['level']:>2}] {a['rule']['description'][:60]:<60} → {r}")
                time.sleep(args.interval)
    except urllib.error.HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode(errors='replace')}", file=sys.stderr)
        return 1
    except urllib.error.URLError as exc:
        print(f"No se pudo conectar: {exc.reason}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
