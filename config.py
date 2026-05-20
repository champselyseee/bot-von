from __future__ import annotations
import os
from dataclasses import dataclass


@dataclass
class Config:
    bot_token: str
    vpn_api_url: str
    vpn_api_key: str
    vpn_domain: str
    vpn_sub_port: int
    yookassa_shop_id: str
    yookassa_secret_key: str
    price_2w: int
    price_1m: int
    db_path: str
    port: int
    base_url: str       # https://xxx.up.railway.app
    admin_ids: list[int]

    # Pre-computed routing profile b64 for connect.html
    ROUTE_B64: str = (
        "eyJOYW1lIjoiQ2FtaWxsZSBWUE4iLCJHbG9iYWxQcm94eSI6ZmFsc2UsIlJvdXRlT3JkZXIiOiJibG9j"
        "ay1wcm94eS1kaXJlY3QiLCJEb21haW5TdHJhdGVneSI6IklQSWZOb25NYXRjaCIsIkZha2VETlMiOmZh"
        "bHNlLCJVc2VDaHVua0ZpbGVzIjp0cnVlLCJSZW1vdGVETlNUeXBlIjoiRG9IIiwiUmVtb3RlRE5TRG9t"
        "YWluIjoiaHR0cHM6Ly9jbG91ZGZsYXJlLWRucy5jb20vZG5zLXF1ZXJ5IiwiUmVtb3RlRE5TSVAiOiIx"
        "LjEuMS4xIiwiRG9tZXN0aWNETlNUeXBlIjoiRG9IIiwiRG9tZXN0aWNETlNEb21haW4iOiJodHRwczov"
        "L2Rucy5nb29nbGUvZG5zLXF1ZXJ5IiwiRG9tZXN0aWNETlNJUCI6IjguOC44LjgiLCJHZW9pcHVybCI6"
        "Imh0dHBzOi8vZ2l0aHViLmNvbS9Mb3lhbHNvbGRpZXIvdjJyYXktcnVsZXMtZGF0L3JlbGVhc2VzL2xh"
        "dGVzdC9kb3dubG9hZC9nZW9pcC5kYXQiLCJHZW9zaXRldXJsIjoiaHR0cHM6Ly9naXRodWIuY29tL0xv"
        "eWFsc29sZGllci92MnJheS1ydWxlcy1kYXQvcmVsZWFzZXMvbGF0ZXN0L2Rvd25sb2FkL2dlb3NpdGUu"
        "ZGF0IiwiRGlyZWN0U2l0ZXMiOlsiZ2Vvc2l0ZTpydSJdLCJEaXJlY3RJcCI6WyJnZW9pcDpydSIsImdl"
        "b2lwOnByaXZhdGUiXSwiUHJveHlTaXRlcyI6W10sIlByb3h5SXAiOltdLCJCbG9ja1NpdGVzIjpbXSwi"
        "QmxvY2tJcCI6W119"
    )

    @property
    def sub_base_url(self) -> str:
        return f"https://{self.vpn_domain}:{self.vpn_sub_port}"

    def plan_price(self, plan: str) -> int:
        return self.price_2w if plan == "2w" else self.price_1m

    def plan_label(self, plan: str) -> str:
        return "2 недели" if plan == "2w" else "1 месяц"

    def plan_days(self, plan: str) -> int:
        return 14 if plan == "2w" else 30


def load_config() -> Config:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Railway sets RAILWAY_PUBLIC_DOMAIN (without scheme)
    raw = (
        os.environ.get("BASE_URL")
        or os.environ.get("RAILWAY_PUBLIC_DOMAIN")
        or os.environ.get("RAILWAY_STATIC_URL")
        or "http://localhost:8080"
    )
    base_url = raw if raw.startswith("http") else f"https://{raw}"

    admin_str = os.environ.get("ADMIN_IDS", "")
    admin_ids = [int(x.strip()) for x in admin_str.split(",") if x.strip().isdigit()]

    return Config(
        bot_token=os.environ["BOT_TOKEN"],
        vpn_api_url=os.environ.get("VPN_API_URL", "http://78.40.117.96:8765"),
        vpn_api_key=os.environ.get("VPN_API_KEY", ""),
        vpn_domain=os.environ.get("VPN_DOMAIN", "camavali.duckdns.org"),
        vpn_sub_port=int(os.environ.get("VPN_SUB_PORT", 2097)),
        yookassa_shop_id=os.environ.get("YOOMONEY_SHOP_ID", ""),
        yookassa_secret_key=os.environ.get("YOOMONEY_SECRET_KEY", ""),
        price_2w=int(os.environ.get("PRICE_2W", 149)),
        price_1m=int(os.environ.get("PRICE_1M", 249)),
        db_path=os.environ.get("DB_PATH", "bot.db"),
        port=int(os.environ.get("PORT", 8080)),
        base_url=base_url.rstrip("/"),
        admin_ids=admin_ids,
    )
