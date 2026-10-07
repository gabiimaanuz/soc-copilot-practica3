#!/var/ossec/framework/python/bin/python3
"""Wazuh → SOC Copilot integration (push mode).

Install on the Wazuh MANAGER:

    cp custom-soccopilot.py /var/ossec/integrations/
    chown root:wazuh /var/ossec/integrations/custom-soccopilot.py
    chmod 750 /var/ossec/integrations/custom-soccopilot.py

and add the <integration> block from ossec-integration.xml to
/var/ossec/etc/ossec.conf, then `systemctl restart wazuh-manager`.

Wazuh integratord calls this script once per matching alert with:
    argv[1] = path to a temp file containing the alert JSON
    argv[2] = <api_key>   (our WAZUH_WEBHOOK_TOKEN)
    argv[3] = <hook_url>  (https://<soc-copilot>/api/integrations/wazuh/webhook)

Only the Python standard library is used, so it runs on Wazuh's bundled
interpreter without installing anything.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

LOG_FILE = "/var/ossec/logs/integrations.log"
TIMEOUT_S = 10
RETRIES = 3

# Optional: path to a CA bundle if SOC Copilot uses a private CA.
CA_FILE = os.environ.get("SOCCOPILOT_CA_FILE", "")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y/%m/%d %H:%M:%S')} custom-soccopilot: {msg}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line)
    except OSError:
        sys.stderr.write(line)


def read_alert(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        content = fh.read().strip()
    # integratord writes one JSON object; tolerate several lines just in case.
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return json.loads(content.splitlines()[-1])


def post(url: str, token: str, alert: dict) -> int:
    data = json.dumps(alert).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "wazuh-integratord/soccopilot",
        },
    )
    ctx = ssl.create_default_context(cafile=CA_FILE or None)
    with urllib.request.urlopen(req, timeout=TIMEOUT_S, context=ctx) as resp:
        return resp.status


def main(argv: list[str]) -> int:
    if len(argv) < 4:
        log("usage: custom-soccopilot.py <alert_file> <api_key> <hook_url>")
        return 1
    alert_file, token, hook_url = argv[1], argv[2], argv[3]
    try:
        alert = read_alert(alert_file)
    except (OSError, ValueError) as exc:
        log(f"cannot read alert file {alert_file}: {exc}")
        return 1

    for attempt in range(1, RETRIES + 1):
        try:
            status = post(hook_url, token, alert)
            if attempt > 1:
                log(f"alert {alert.get('id')} delivered after {attempt} attempts")
            return 0 if status < 300 else 1
        except urllib.error.HTTPError as exc:
            # 4xx (bad token, payload) won't fix itself — don't retry.
            log(f"alert {alert.get('id')} rejected: HTTP {exc.code}")
            if exc.code < 500 and exc.code != 429:
                return 1
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log(f"attempt {attempt} failed for alert {alert.get('id')}: {exc}")
        time.sleep(2 ** attempt)
    log(f"giving up on alert {alert.get('id')}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
