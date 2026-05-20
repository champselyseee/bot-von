#!/usr/bin/env python3
"""
VPN Management API
Listens on 0.0.0.0:8765
Protected by X-API-Key header

Endpoints:
  POST /client/add    – add a new Hysteria2 + VLESS client
  POST /client/update – update expiry for an existing client

Client data is stored in THREE places (kept in sync):
  1. /etc/hysteria2/config.yaml          – auth.userpass dict
  2. /usr/local/bin/hy2-sub.py           – CLIENTS dict
  3. /usr/local/bin/setup-server.py      – CLIENTS dict
  4. /etc/x-ui/x-ui.db                  – inbound 10 clients JSON (VLESS + expiry)
"""

import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer


# ── paths ────────────────────────────────────────────────────────────────────
HY2_CONFIG   = "/etc/hysteria2/config.yaml"
HY2_SUB_PY   = "/usr/local/bin/hy2-sub.py"
SETUP_PY     = "/usr/local/bin/setup-server.py"
XUI_DB       = "/etc/x-ui/x-ui.db"
XUI_INBOUND  = 10          # inbound id for VLESS
CONFIG_FILE  = "/etc/vpn-api/config.json"

# ── config ───────────────────────────────────────────────────────────────────
def load_config():
    with open(CONFIG_FILE) as f:
        return json.load(f)

API_KEY = load_config()["api_key"]

# ── YAML helpers ─────────────────────────────────────────────────────────────
def _read_hy2_raw():
    with open(HY2_CONFIG) as f:
        return f.read()

def _write_hy2_raw(text):
    tmp = HY2_CONFIG + ".tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, HY2_CONFIG)

def add_hy2_userpass_entry(email, password):
    src = _read_hy2_raw()
    if "type: userpass" not in src:
        raise ValueError("Unexpected auth type in Hysteria2 config")
    if re.search(r'^\s+' + re.escape(email) + r'\s*:', src, re.MULTILINE):
        raise ValueError(f"Client '{email}' already exists in Hysteria2 config")
    new_src = re.sub(r'(userpass:\n)', r'\1    ' + email + ': ' + password + '\n', src, count=1)
    if new_src == src:
        raise ValueError("Could not find 'userpass:' section in Hysteria2 config")
    _write_hy2_raw(new_src)

# ── Python-source CLIENTS dict helpers ───────────────────────────────────────
# hy2-sub.py  format:  "sub_id": ("email", "password"),
# setup-server.py format: "sub_id": "email",

def _read_file(path):
    with open(path) as f:
        return f.read()

def _write_file(path, content):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.replace(tmp, path)

# Extract the raw content between CLIENTS = { ... }
_CLIENTS_RE = re.compile(
    r'(CLIENTS\s*=\s*\{)(.*?)(\n\})',
    re.DOTALL
)

def _parse_hy2sub_clients(src):
    """Return dict {sub_id: (email, password)} from hy2-sub.py source."""
    m = _CLIENTS_RE.search(src)
    if not m:
        raise ValueError("CLIENTS dict not found in hy2-sub.py")
    body = m.group(2)
    # each line: "sub_id": ("email", "password"),
    clients = {}
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("#"):
            continue
        km = re.match(r'"([^"]+)"\s*:\s*\("([^"]+)"\s*,\s*"([^"]+)"\)', line)
        if km:
            clients[km.group(1)] = (km.group(2), km.group(3))
    return clients

def _parse_setup_clients(src):
    """Return dict {sub_id: email} from setup-server.py source."""
    m = _CLIENTS_RE.search(src)
    if not m:
        raise ValueError("CLIENTS dict not found in setup-server.py")
    body = m.group(2)
    clients = {}
    for line in body.splitlines():
        line = line.strip().rstrip(",")
        if not line or line.startswith("#"):
            continue
        km = re.match(r'"([^"]+)"\s*:\s*"([^"]+)"', line)
        if km:
            clients[km.group(1)] = km.group(2)
    return clients

def _render_hy2sub_clients(clients):
    """Render {sub_id: (email, pw)} → CLIENTS block body lines."""
    lines = []
    for sub_id, (email, pw) in clients.items():
        lines.append(f'    "{sub_id}": ("{email}",        "{pw}"),')
    return "\n".join(lines)

def _render_setup_clients(clients):
    """Render {sub_id: email} → CLIENTS block body lines."""
    lines = []
    for sub_id, email in clients.items():
        lines.append(f'    "{sub_id}": "{email}",')
    return "\n".join(lines)

def update_hy2sub_clients(clients):
    src = _read_file(HY2_SUB_PY)
    new_body = _render_hy2sub_clients(clients)
    new_src = _CLIENTS_RE.sub(
        lambda m: m.group(1) + "\n" + new_body + "\n" + m.group(3),
        src
    )
    _write_file(HY2_SUB_PY, new_src)

def update_setup_clients(clients):
    src = _read_file(SETUP_PY)
    new_body = _render_setup_clients(clients)
    new_src = _CLIENTS_RE.sub(
        lambda m: m.group(1) + "\n" + new_body + "\n" + m.group(3),
        src
    )
    _write_file(SETUP_PY, new_src)

# ── x-ui DB helpers ───────────────────────────────────────────────────────────
def xui_get_settings():
    con = sqlite3.connect(XUI_DB)
    cur = con.execute("SELECT settings FROM inbounds WHERE id=?", (XUI_INBOUND,))
    row = cur.fetchone()
    con.close()
    if row is None:
        raise ValueError(f"Inbound {XUI_INBOUND} not found in x-ui.db")
    return json.loads(row[0])

def xui_set_settings(settings):
    con = sqlite3.connect(XUI_DB)
    con.execute(
        "UPDATE inbounds SET settings=? WHERE id=?",
        (json.dumps(settings, ensure_ascii=False), XUI_INBOUND)
    )
    con.commit()
    con.close()


# ── service reload ──────────────────────────────────────────────────────────
def reload_service(name):
    subprocess.run(["systemctl", "restart", name], check=True)

# ── business logic ────────────────────────────────────────────────────────────
def client_add(email, password, sub_id, expires_ms):
    """Add a client to all four storage locations."""
    now_ms = int(time.time() * 1000)

    # 1. Hysteria2 config.yaml
    add_hy2_userpass_entry(email, password)

    # 2. hy2-sub.py CLIENTS
    src = _read_file(HY2_SUB_PY)
    clients_sub = _parse_hy2sub_clients(src)
    if sub_id in clients_sub:
        raise ValueError(f"sub_id '{sub_id}' already exists in hy2-sub.py")
    clients_sub[sub_id] = (email, password)
    update_hy2sub_clients(clients_sub)

    # 3. setup-server.py CLIENTS
    src2 = _read_file(SETUP_PY)
    clients_setup = _parse_setup_clients(src2)
    clients_setup[sub_id] = email
    update_setup_clients(clients_setup)

    # 4. x-ui.db – add VLESS client
    settings = xui_get_settings()
    for c in settings["clients"]:
        if c["email"] == email:
            raise ValueError(f"Client '{email}' already exists in x-ui.db")
    new_client = {
        "id": str(uuid.uuid4()),
        "email": email,
        "flow": "xtls-rprx-vision",
        "limitIp": 0,
        "totalGB": 0,
        "expiryTime": expires_ms,
        "enable": True,
        "tgId": 0,
        "subId": sub_id,
        "comment": "",
        "reset": 0,
        "created_at": now_ms,
        "updated_at": now_ms,
    }
    settings["clients"].append(new_client)
    xui_set_settings(settings)

    # Reload services
    reload_service("hysteria2")
    reload_service("hy2-sub")
    reload_service("setup-server")
    reload_service("x-ui")  # restart xray so new VLESS UUID is picked up

    return {"ok": True, "email": email, "sub_id": sub_id}


def client_update(email, expires_ms):
    """Update expiry for an existing client in x-ui.db."""
    now_ms = int(time.time() * 1000)
    settings = xui_get_settings()
    found = False
    for c in settings["clients"]:
        if c["email"] == email:
            c["expiryTime"] = expires_ms
            c["updated_at"] = now_ms
            found = True
            break
    if not found:
        raise ValueError(f"Client '{email}' not found in x-ui.db")
    xui_set_settings(settings)
    return {"ok": True, "email": email, "expires_ms": expires_ms}


# ── HTTP handler ──────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{ts}] {fmt % args}", flush=True)

    def _send_json(self, code, data):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _check_auth(self):
        key = self.headers.get("X-API-Key", "")
        return key == API_KEY

    def _read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length))

    def do_POST(self):
        if not self._check_auth():
            self._send_json(401, {"ok": False, "error": "Unauthorized"})
            return

        path = self.path.rstrip("/")
        try:
            body = self._read_body()

            if path == "/client/add":
                email      = body["email"]
                password   = body["password"]
                sub_id     = body["sub_id"]
                expires_ms = int(body.get("expires_ms", 0))
                result = client_add(email, password, sub_id, expires_ms)
                self._send_json(200, result)

            elif path == "/client/update":
                email      = body["email"]
                expires_ms = int(body["expires_ms"])
                result = client_update(email, expires_ms)
                self._send_json(200, result)

            else:
                self._send_json(404, {"ok": False, "error": "Not found"})

        except KeyError as e:
            self._send_json(400, {"ok": False, "error": f"Missing field: {e}"})
        except ValueError as e:
            self._send_json(409, {"ok": False, "error": str(e)})
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr, flush=True)
            self._send_json(500, {"ok": False, "error": str(e)})

    def do_GET(self):
        if self.path == "/health":
            self._send_json(200, {"ok": True, "ts": int(time.time())})
        else:
            self._send_json(404, {"ok": False, "error": "Not found"})


if __name__ == "__main__":
    srv = HTTPServer(("0.0.0.0", 8765), Handler)
    print(f"VPN API running on 0.0.0.0:8765", flush=True)
    srv.serve_forever()
