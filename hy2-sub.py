#!/usr/bin/env python3
import ssl, base64, json, os, urllib.request, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import urllib.error

CERT   = "/etc/letsencrypt/live/camavali.duckdns.org/fullchain.pem"
KEY    = "/etc/letsencrypt/live/camavali.duckdns.org/privkey.pem"
DOMAIN = "camavali.duckdns.org"  # primary domain (used for /sub/, /connect/ URLs)
PORT   = 2097

# ── Multi-server scaffold ─────────────────────────────────────────────────────
SERVERS = [
    {
        "domain":        "camavali.duckdns.org",
        "label":         "Швеция 🇸🇪",
        "xray_sub_base": "https://78.40.117.96:2096/sub",
        "xray_host":     "camavali.duckdns.org",
    },
]

XRAY_SUB_BASE = SERVERS[0]["xray_sub_base"]
XRAY_HOST     = SERVERS[0]["xray_host"]

# Hardcoded clients (manual users — never auto-deleted)
CLIENTS = {
    "37987054ae863595": ("tg_1279497366",  "vgXf5Li0Ctjp_gOfn92Gn8QRIIq-nTl2"),
    "2d53e18f6ece4d0a": ("tg_1039556024",  "P7MOspB1dCDgYw5gsX8sDKxKdxzQSCMH"),
    "1430b1956c355591": ("tg_6245920765",  "UU590hDPYofMsGiOYlEkVxSsKP6zvytm"),
    "08030653bcfbd76e": ("tg_1065389920",  "uDUYY-DB1MQBH-loDZb1EJTN-2lgcLOo"),
    "f50a7a094ef1689e": ("me",             "Wkypm1TjBJbqj3rDqrqRLJFJIwBucQx0"),
    "e030e58ad79dc269": ("friend1",        "0yLcRqdNJtqRUNNmRmajkcb_3hx6DBvp"),
    "d664db67be697a21": ("friend2",        "oMCNy37sW1LLM8MSYpbANgUCGqYyvE4m"),
    "ef0c23905c60fc48": ("frienddest",     "_uWWZ1BnDY4t6WL7HLpLKRI7GrWnYnOX"),
    "1d5187cf78244eee": ("me2",            "n9rlf9TOeYzFLx9D30PZWwGCIurdDOci"),
}

# ── Dynamic clients (bot-provisioned users) ───────────────────────────────────
# Persisted at CLIENTS_FILE; managed via POST /client/add and /client/remove
CLIENTS_FILE = "/etc/hy2-sub/clients.json"
API_KEY      = os.environ.get("HY2_SUB_API_KEY", "sCCoceVhFc-oWFUTX-Tsjy1M2quAQaGVems6GXbvFgo")

_dyn_clients: dict = {}
_dyn_lock = threading.Lock()


def _load_dynamic():
    global _dyn_clients
    if not os.path.exists(CLIENTS_FILE):
        return
    try:
        with open(CLIENTS_FILE) as f:
            data = json.load(f)
        with _dyn_lock:
            _dyn_clients = {k: tuple(v) for k, v in data.items()}
        print(f"[info] loaded {len(_dyn_clients)} dynamic clients", flush=True)
    except Exception as e:
        print(f"[warn] load {CLIENTS_FILE}: {e}", flush=True)


def _save_dynamic():
    try:
        os.makedirs(os.path.dirname(CLIENTS_FILE), exist_ok=True)
        with _dyn_lock:
            data = {k: list(v) for k, v in _dyn_clients.items()}
        tmp = CLIENTS_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, CLIENTS_FILE)
    except Exception as e:
        print(f"[warn] save {CLIENTS_FILE}: {e}", flush=True)


def _get_client(sub_id):
    """Return (email, password) for sub_id, checking hardcoded then dynamic."""
    if sub_id in CLIENTS:
        return CLIENTS[sub_id]
    with _dyn_lock:
        return _dyn_clients.get(sub_id)


ROUTE_B64 = "eyJOYW1lIjoiUlUgRGlyZWN0IiwiR2xvYmFsUHJveHkiOnRydWUsIlJvdXRlT3JkZXIiOiJibG9jay1wcm94eS1kaXJlY3QiLCJEb21haW5TdHJhdGVneSI6IklQSWZOb25NYXRjaCIsIkZha2VETlMiOmZhbHNlLCJVc2VDaHVua0ZpbGVzIjp0cnVlLCJSZW1vdGVETlNUeXBlIjoiRG9IIiwiUmVtb3RlRE5TRG9tYWluIjoiaHR0cHM6Ly9jbG91ZGZsYXJlLWRucy5jb20vZG5zLXF1ZXJ5IiwiUmVtb3RlRE5TSVAiOiIxLjEuMS4xIiwiRG9tZXN0aWNETlNUeXBlIjoiRG9IIiwiRG9tZXN0aWNETlNEb21haW4iOiJodHRwczovL2Rucy5nb29nbGUvZG5zLXF1ZXJ5IiwiRG9tZXN0aWNETlNJUCI6IjguOC44LjgiLCJHZW9pcHVybCI6Imh0dHBzOi8vZ2l0aHViLmNvbS9Mb3lhbHNvbGRpZXIvdjJyYXktcnVsZXMtZGF0L3JlbGVhc2VzL2xhdGVzdC9kb3dubG9hZC9nZW9pcC5kYXQiLCJHZW9zaXRldXJsIjoiaHR0cHM6Ly9naXRodWIuY29tL0xveWFsc29sZGllci92MnJheS1ydWxlcy1kYXQvcmVsZWFzZXMvbGF0ZXN0L2Rvd25sb2FkL2dlb3NpdGUuZGF0IiwiRGlyZWN0U2l0ZXMiOlsiZG9tYWluOnZrLmNvbSIsImRvbWFpbjp2ay5tZSIsImRvbWFpbjp1c2VyYXBpLmNvbSIsImRvbWFpbjp2a29udGFrdGUucnUiLCJkb21haW46eWFuZGV4LnJ1IiwiZG9tYWluOnlhbmRleC5jb20iLCJkb21haW46eWFuZGV4Lm5ldCIsImRvbWFpbjp5YS5ydSIsImRvbWFpbjptYWlsLnJ1IiwiZG9tYWluOm9rLnJ1IiwiZG9tYWluOm9kbm9rbGFzc25pa2kucnUiLCJkb21haW46c2Jlci5ydSIsImRvbWFpbjpzYmVyYmFuay5ydSIsImRvbWFpbjp0aW5rb2ZmLnJ1IiwiZG9tYWluOnJhaWZmZWlzZW4ucnUiLCJkb21haW46Z29zdXNsdWdpLnJ1IiwiZG9tYWluOm1vcy5ydSIsImRvbWFpbjpuYWxvZy5nb3YucnUiLCJkb21haW46cmJjLnJ1IiwiZG9tYWluOnJpYS5ydSIsImRvbWFpbjpsZW50YS5ydSIsImRvbWFpbjprb21tZXJzYW50LnJ1IiwiZG9tYWluOjJnaXMucnUiLCJkb21haW46YXZpdG8ucnUiLCJkb21haW46b3pvbi5ydSIsImRvbWFpbjp3aWxkYmVycmllcy5ydSIsImRvbWFpbjpraW5vcG9pc2sucnUiLCJkb21haW46cnV0dWJlLnJ1IiwiZG9tYWluOmR6ZW4ucnUiLCJyZWdleHA6XFwucnUkIiwicmVnZXhwOlxcLtGA0YQkIiwicmVnZXhwOlxcLnN1JCJdLCJEaXJlY3RJcCI6WyIxMC4wLjAuMC84IiwiMTcyLjE2LjAuMC8xMiIsIjE5Mi4xNjguMC4wLzE2IiwiZ2VvaXA6cHJpdmF0ZSIsImdlb2lwOnJ1Il0sIlByb3h5U2l0ZXMiOltdLCJQcm94eUlwIjpbXSwiQmxvY2tTaXRlcyI6W10sIkJsb2NrSXAiOltdfQ=="

CRYPT_CACHE = {}

def get_crypt_link(sub_url):
    if sub_url in CRYPT_CACHE:
        return CRYPT_CACHE[sub_url]
    try:
        data = json.dumps({"url": sub_url}).encode("utf-8")
        req = urllib.request.Request(
            "https://crypto.happ.su/api-v2.php",
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            body = r.read().decode("utf-8")
        resp = json.loads(body)
        link = None
        if isinstance(resp, dict):
            link = resp.get("encrypted_link") or resp.get("link") or resp.get("url") or resp.get("result")
        elif isinstance(resp, str) and resp.startswith("happ://"):
            link = resp
        if link:
            CRYPT_CACHE[sub_url] = link
        return link
    except Exception:
        return None

SETUP_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Настройка VPN</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ font-family: -apple-system, sans-serif; background: #f5f5f7; min-height: 100vh; padding: 24px 16px; }}
.card {{ background: white; border-radius: 16px; padding: 20px; margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }}
h1 {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
.sub {{ color: #666; font-size: 14px; margin-bottom: 20px; }}
.step {{ display: flex; align-items: flex-start; gap: 12px; margin-bottom: 16px; }}
.num {{ background: #2563eb; color: white; width: 28px; height: 28px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center; font-weight: 700;
        font-size: 14px; flex-shrink: 0; margin-top: 2px; }}
.step-text h3 {{ font-size: 15px; font-weight: 600; margin-bottom: 4px; }}
.step-text p {{ font-size: 13px; color: #666; line-height: 1.4; }}
.btn {{ display: block; width: 100%; background: #2563eb; color: white; padding: 14px;
        border-radius: 12px; text-decoration: none; font-size: 16px; font-weight: 600;
        text-align: center; margin-top: 10px; }}
.btn.green {{ background: #16a34a; }}
.url-box {{ background: #f5f5f7; border-radius: 8px; padding: 10px 12px; font-size: 12px;
            word-break: break-all; color: #333; margin-top: 8px; font-family: monospace; }}
.copy-btn {{ display: block; width: 100%; background: #f0f0f0; color: #333; padding: 10px;
             border-radius: 8px; text-align: center; font-size: 14px; font-weight: 600;
             margin-top: 8px; border: none; cursor: pointer; }}
.copy-btn.copied {{ background: #dcfce7; color: #16a34a; }}
</style>
</head>
<body>
<div class="card">
  <h1>VPN Setup</h1>
  <p class="sub">Два шага — и готово</p>

  <div class="step">
    <div class="num">1</div>
    <div class="step-text">
      <h3>Правила маршрутизации</h3>
      <p>РУ-сайты идут напрямую, всё остальное через VPN</p>
    </div>
  </div>
  <a class="btn" href="happ://routing/onadd/{route_b64}">Добавить в Happ</a>

  <div class="step" style="margin-top:20px">
    <div class="num">2</div>
    <div class="step-text">
      <h3>Подписка на прокси</h3>
      <p>Нажми кнопку — подписка добавится автоматически</p>
    </div>
  </div>
  <a class="btn green" href="{crypt_link}">Добавить подписку в Happ</a>
  <div class="url-box" id="sub-url">{sub_url}</div>
  <button class="copy-btn" onclick="copyUrl()">Скопировать ссылку (для других приложений)</button>
</div>

<script>
function copyUrl() {{
  navigator.clipboard.writeText(document.getElementById('sub-url').innerText).then(function() {{
    var btn = document.querySelector('.copy-btn');
    btn.textContent = 'Скопировано!';
    btn.classList.add('copied');
    setTimeout(function() {{
      btn.textContent = 'Скопировать ссылку';
      btn.classList.remove('copied');
    }}, 2000);
  }});
}}
</script>
</body>
</html>"""

CONNECT_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Подключение VPN</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', Arial, sans-serif;
  background: #f5f5f7; min-height: 100vh; padding: 24px 16px 40px;
  display: flex; flex-direction: column; align-items: center;
}}
.logo-header {{ width: 100%; max-width: 420px; text-align: center; padding: 28px 0 24px; }}
.logo-header .brand {{ font-size: 26px; font-weight: 900; letter-spacing: -0.5px; color: #111111; line-height: 1; }}
.logo-header .brand span {{ color: #E8191A; }}
.logo-header .tagline {{ font-size: 12px; font-weight: 600; color: #666; letter-spacing: 2px; text-transform: uppercase; margin-top: 6px; }}
.safari-banner {{
  display: none; width: 100%; max-width: 420px;
  background: #fff5f5; border: 1px solid #E8191A; border-radius: 14px;
  padding: 14px 16px; margin-bottom: 16px; font-size: 13px; line-height: 1.55; color: #555;
}}
.safari-banner b {{ display: block; font-size: 14px; font-weight: 800; color: #111111; margin-bottom: 5px; }}
.card {{
  background: #ffffff; border-radius: 20px; padding: 24px 20px; margin-bottom: 16px;
  width: 100%; max-width: 420px; border: 1px solid #e5e5e5; box-shadow: 0 1px 4px rgba(0,0,0,.07);
}}
h1 {{ font-size: 20px; font-weight: 800; color: #111111; margin-bottom: 3px; letter-spacing: -0.3px; }}
.sub {{ color: #666; font-size: 13px; font-weight: 500; margin-bottom: 24px; }}
.step {{ display: flex; align-items: flex-start; gap: 14px; margin-bottom: 16px; }}
.num {{
  background: #E8191A; color: #FFFFFF; width: 28px; height: 28px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center; font-weight: 900; font-size: 13px;
  flex-shrink: 0; margin-top: 1px; box-shadow: 0 0 0 3px rgba(232, 25, 26, 0.18);
}}
.step-text h3 {{ font-size: 14px; font-weight: 700; color: #111111; margin-bottom: 3px; }}
.step-text p {{ font-size: 12px; color: #777; line-height: 1.45; }}
.divider {{ border: none; border-top: 1px solid #e5e5e5; margin: 20px 0; }}
.btn {{
  display: block; width: 100%; background: #E8191A; color: #FFFFFF; padding: 15px;
  border-radius: 14px; text-decoration: none; font-size: 15px; font-weight: 800;
  text-align: center; margin-top: 10px; letter-spacing: 0.1px;
  transition: background 0.15s; -webkit-tap-highlight-color: transparent;
}}
.btn:active {{ background: #c91415; }}
.btn.green {{ background: #E8191A; }}
.btn.green:active {{ background: #c91415; }}
.url-box {{
  background: #f5f5f7; border: 1px solid #e5e5e5; border-radius: 10px;
  padding: 10px 12px; font-size: 11px; word-break: break-all; color: #555;
  margin-top: 10px; font-family: 'Menlo', 'Courier New', monospace; line-height: 1.5;
}}
.copy-btn {{
  display: block; width: 100%; background: #f0f0f0; color: #555; padding: 11px;
  border-radius: 10px; text-align: center; font-size: 13px; font-weight: 700;
  margin-top: 8px; border: 1px solid #e5e5e5; cursor: pointer;
  -webkit-tap-highlight-color: transparent;
}}
.copy-btn:active {{ background: #e5e5e5; }}
.copy-btn.copied {{ background: #fff0f0; color: #E8191A; border-color: #E8191A; }}
.btn-row {{ display: flex; gap: 8px; margin-top: 10px; }}
.btn-row .btn {{
  margin-top: 0; flex: 1; font-size: 14px; padding: 13px 6px;
  background: #f0f0f0; color: #111111; border: 1px solid #e5e5e5; font-weight: 700;
}}
.btn-row .btn:active {{ background: #e5e5e5; }}
</style>
</head>
<body>

<div class="logo-header">
  <img src="data:image/png;base64,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" alt="Camille VPN" width="80" style="display:block;margin:0 auto 14px;">
  <div class="brand">Camille <span>VPN</span></div>
  <div class="tagline">Secure · Private · Fast</div>
</div>

<div class="safari-banner" id="safari-banner">
  <b>⚠️ Открой страницу в Safari</b>
  Ты открыл ссылку в браузере Telegram — кнопки «Добавить в Happ» отсюда не сработают.<br><br>
  Нажми <b>···</b> (три точки внизу экрана) → <b>Открыть в Safari</b>
</div>

<div class="card">
  <h1>Подключение VPN</h1>
  <p class="sub">Три шага — и готово</p>

  <div class="step">
    <div class="num">1</div>
    <div class="step-text">
      <h3>Скачай приложение Happ</h3>
      <p>Если уже установлено — пропусти этот шаг</p>
    </div>
  </div>
  <div class="btn-row">
    <a class="btn" href="https://apps.apple.com/us/app/happ-proxy-utility/id6504287215" target="_blank">App Store</a>
    <a class="btn" href="https://play.google.com/store/apps/details?id=com.happproxy&pcampaignid=web_share" target="_blank">Google Play</a>
  </div>

  <hr class="divider">

  <div class="step" style="margin-top:4px">
    <div class="num">2</div>
    <div class="step-text">
      <h3>Правила маршрутизации</h3>
      <p>РУ-сайты идут напрямую, всё остальное через VPN</p>
    </div>
  </div>
  <a class="btn" href="happ://routing/onadd/{route_b64}">Добавить правила в Happ</a>

  <hr class="divider">

  <div class="step" style="margin-top:4px">
    <div class="num">3</div>
    <div class="step-text">
      <h3>Подписка на прокси</h3>
      <p>Нажми кнопку — подписка добавится автоматически</p>
    </div>
  </div>
  <a class="btn green" href="{crypt_link}">Добавить подписку в Happ</a>
  <div class="url-box" id="sub-url">{sub_url}</div>
  <button class="copy-btn" onclick="copyUrl()">Скопировать ссылку (для других приложений)</button>
</div>

<script>
if (/Telegram/i.test(navigator.userAgent)) {{
  document.getElementById('safari-banner').style.display = 'block';
}}
function copyUrl() {{
  navigator.clipboard.writeText(document.getElementById('sub-url').innerText).then(function() {{
    var btn = document.querySelector('.copy-btn');
    btn.textContent = 'Скопировано!';
    btn.classList.add('copied');
    setTimeout(function() {{
      btn.textContent = 'Скопировать ссылку';
      btn.classList.remove('copied');
    }}, 2000);
  }});
}}
</script>
</body>
</html>"""

def fetch_vless(sub_id, srv=None):
    if srv is None:
        srv = SERVERS[0]
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        req = urllib.request.Request(
            srv["xray_sub_base"] + "/" + sub_id,
            headers={"Host": srv["xray_host"], "User-Agent": "HappSub/1.0"}
        )
        with urllib.request.urlopen(req, context=ctx, timeout=10) as r:
            body = r.read()
        return base64.b64decode(body).decode("utf-8").strip()
    except Exception:
        return ""

def make_singbox_config(user, pw, sub_id):
    return {
        "log": {"level": "warn"},
        "dns": {
            "servers": [
                {"tag": "dns-proxy", "address": "udp://1.1.1.1", "detour": "proxy"},
                {"tag": "dns-local", "address": "udp://77.88.8.8", "detour": "direct"}
            ],
            "rules": [{"geosite": ["ru"], "server": "dns-local"}],
            "final": "dns-proxy",
            "independent_cache": True
        },
        "inbounds": [{
            "type": "tun", "tag": "tun-in",
            "inet4_address": "172.19.0.1/30",
            "mtu": 9000, "auto_route": True, "strict_route": True,
            "stack": "system", "sniff": True
        }],
        "outbounds": [
            {"type": "hysteria2", "tag": "proxy", "server": DOMAIN, "server_port": 443,
             "password": user + ":" + pw,
             "obfs": {"type": "salamander", "password": "0cae7bc94e60fc06315f29d750d34ff6f2b97c867f62d6b7"},
             "tls": {"enabled": True, "server_name": DOMAIN}},
            {"type": "direct", "tag": "direct"},
            {"type": "block",  "tag": "block"},
            {"type": "dns",    "tag": "dns-out"}
        ],
        "route": {
            "rules": [
                {"protocol": "dns", "outbound": "dns-out"},
                {"geosite": ["ru"], "outbound": "direct"},
                {"geoip":   ["ru"], "outbound": "direct"},
                {"ip_cidr": ["10.0.0.0/8","172.16.0.0/12","192.168.0.0/16","127.0.0.0/8"], "outbound": "direct"}
            ],
            "auto_detect_interface": True,
            "final": "proxy"
        }
    }

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        import time
        print(f"[{time.strftime('%H:%M:%S')}] {self.client_address[0]} {fmt % args}", flush=True)

    def do_GET(self):
        _raw = self.path.split("?")[0]
        path = _raw.strip("/")
        parts = path.split("/")

        # /setup/<subId>
        if parts[0] == "setup" and len(parts) == 2 and _get_client(parts[1]):
            sub_id = parts[1]
            import time as _t
            sub_url = "https://" + DOMAIN + ":2097/sub/" + sub_id + "?v=" + str(int(_t.time()) // 3600)
            crypt_link = get_crypt_link(sub_url) or sub_url
            html = SETUP_HTML.format(route_b64=ROUTE_B64, sub_url=sub_url, crypt_link=crypt_link)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # /route
        if path == "route":
            html = SETUP_HTML.format(
                route_b64=ROUTE_B64,
                sub_url="https://" + DOMAIN + ":2097/sub/",
                crypt_link="https://" + DOMAIN + ":2097/sub/"
            )
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if len(parts) != 2 or not _get_client(parts[1]):
            self.send_response(404); self.end_headers(); return

        mode, sub_id = parts[0], parts[1]
        user, pw = _get_client(sub_id)

        if mode == "connect":
            import time as _t
            sub_url = "https://" + DOMAIN + ":2097/sub/" + sub_id + "?v=" + str(int(_t.time()) // 3600)
            crypt_link = get_crypt_link(sub_url)
            if not crypt_link:
                self.send_response(302)
                self.send_header("Location", "https://" + DOMAIN + ":2097/setup/" + sub_id)
                self.end_headers()
                return
            html = CONNECT_HTML.format(route_b64=ROUTE_B64, crypt_link=crypt_link, sub_url=sub_url)
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif mode == "json":
            cfg  = make_singbox_config(user, pw, sub_id)
            body = json.dumps(cfg, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif mode == "sub":
            lines = []
            for srv in SERVERS:
                d = srv["domain"]
                lbl = srv["label"]
                lines.append(
                    "hysteria2://" + user + ":" + pw + "@" + d + ":443"
                    "?sni=" + d + "&insecure=0&obfs=salamander&obfs-password=0cae7bc94e60fc06315f29d750d34ff6f2b97c867f62d6b7"
                    "#Camille VPN | " + lbl + " | 🚀 Основной"
                )
                vless_raw = fetch_vless(sub_id, srv)
                if vless_raw:
                    lines.append(
                        vless_raw.split("#")[0] + "#Camille VPN | " + lbl + " | 🔒 Резервный"
                    )
            combined = chr(10).join(lines) + chr(10)
            body = base64.b64encode(combined.encode("utf-8"))
            self.send_response(200)
            self.send_header("profile-title", "Camille VPN")
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        else:
            self.send_response(404); self.end_headers()

    def do_POST(self):
        path = self.path.strip("/").split("?")[0]

        if self.headers.get("X-API-Key", "") != API_KEY:
            self.send_response(403); self.end_headers(); return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception:
            self.send_response(400); self.end_headers(); return

        if path == "client/add":
            sub_id   = str(body.get("sub_id",   "")).strip()
            email    = str(body.get("email",    "")).strip()
            password = str(body.get("password", "")).strip()
            if not sub_id or not email or not password:
                resp = b'{"ok":false,"error":"missing fields"}'
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(resp)))
                self.end_headers()
                self.wfile.write(resp)
                return
            with _dyn_lock:
                _dyn_clients[sub_id] = (email, password)
            _save_dynamic()
            print(f"[info] registered client {email} sub_id={sub_id}", flush=True)
            resp = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        elif path == "client/remove":
            sub_id = str(body.get("sub_id", "")).strip()
            if sub_id:
                with _dyn_lock:
                    _dyn_clients.pop(sub_id, None)
                _save_dynamic()
                print(f"[info] removed sub_id={sub_id}", flush=True)
            resp = b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(resp)))
            self.end_headers()
            self.wfile.write(resp)

        else:
            self.send_response(404); self.end_headers()


class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def _warm_cache():
    import time as _t
    with _dyn_lock:
        all_ids = list(CLIENTS.keys()) + list(_dyn_clients.keys())
    for sub_id in all_ids:
        sub_url = "https://" + DOMAIN + ":2097/sub/" + sub_id + "?v=" + str(int(_t.time()) // 3600)
        get_crypt_link(sub_url)

if __name__ == "__main__":
    _load_dynamic()
    threading.Thread(target=_warm_cache, daemon=True).start()
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    print("Sub proxy running on :" + str(PORT))
    srv.serve_forever()
