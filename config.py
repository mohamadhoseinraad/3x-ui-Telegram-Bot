"""
Configuration settings for the VPN bot
Supports multiple XUI servers
"""
import os
import random
import re
import json
from pathlib import Path

def _load_dotenv(dotenv_path: str | Path = ".env") -> None:
    """Simple .env loader: reads KEY=VALUE lines into os.environ if not set."""
    p = Path(dotenv_path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if (val.startswith("\"") and val.endswith("\"")) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
        # Do not overwrite existing environment variables
        os.environ.setdefault(key, val)


# Load .env if present in the project root
_load_dotenv()

# Admin configuration
# Set `ADMIN_IDS` as a comma-separated list in `ADMIN_IDS` env var, e.g. "123,456"
_admin_ids = os.getenv("ADMIN_IDS", "6865193414")
ADMIN_IDS = [int(x.strip()) for x in _admin_ids.split(",") if x.strip()]

# Bot configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_ID = os.getenv("BOT_ID", "")

# ============================================================
# MULTI-SERVER CONFIGURATION
# ============================================================
# Option 1: Legacy single server (backward compatible)
# Option 2: Multiple servers via SERVERS_JSON env var
#
# SERVERS_JSON format:
# [
#   {
#     "id": "server1",
#     "name": "Germany",
#     "url": "https://panel1.example.com",
#     "username": "admin",
#     "password": "pass1",
#     "inbound_id": 1,
#     "host": "de.example.com",
#     "port": 443,
#     "sni": "",
#     "vless_text": "",
#     "sub_port": 0,
#     "sub_path": "sub"
#   },
#   ...
# ]
# ============================================================

# Legacy single-server settings (kept for backward compatibility)
XUI_URL = os.getenv("XUI_URL", "")
XUI_USERNAME = os.getenv("XUI_USERNAME", "admin")
XUI_PASSWORD = os.getenv("XUI_PASSWORD", "")
INBOUND_ID = int(os.getenv("INBOUND_ID", os.getenv("INBOUND", "1")))

IPDOMAIN = os.getenv("IPDOMAIN", "")
VLESS_TEXT = os.getenv("VLESS_TEXT", "")
DOMAIN = os.getenv("DOMAIN", "")
PORT = int(os.getenv("PORT", os.getenv("SERVER_PORT", "443")))
HOST = os.getenv("HOST", "")
SNI = os.getenv("SNI", "")
SUB_PORT = int(os.getenv("SUB_PORT", "0"))
SUB_PATH = os.getenv("SUB_PATH", "sub")

# Default server ID when only one server is configured
DEFAULT_SERVER_ID = os.getenv("DEFAULT_SERVER_ID", "default")


def _load_servers_from_env():
    """
    Load server configurations from environment.
    Returns a list of server dicts.
    Priority:
      1. SERVERS_JSON env var (JSON array)
      2. Legacy single server from individual env vars
    """
    servers_json = os.getenv("SERVERS_JSON", "").strip()
    if servers_json:
        try:
            servers = json.loads(servers_json)
            if isinstance(servers, list) and servers:
                # Validate and normalize each server entry
                normalized = []
                for idx, srv in enumerate(servers):
                    if not isinstance(srv, dict):
                        continue
                    sid = str(srv.get("id") or f"server{idx + 1}").strip()
                    normalized.append({
                        "id": sid,
                        "name": str(srv.get("name") or sid),
                        "url": str(srv.get("url") or "").rstrip("/"),
                        "username": str(srv.get("username") or "admin"),
                        "password": str(srv.get("password") or ""),
                        "inbound_id": int(srv.get("inbound_id") or srv.get("inbound") or 1),
                        "host": str(srv.get("host") or srv.get("ipdomain") or ""),
                        "port": int(srv.get("port") or srv.get("server_port") or 443),
                        "sni": str(srv.get("sni") or ""),
                        "vless_text": str(srv.get("vless_text") or ""),
                        "sub_port": int(srv.get("sub_port") or 0),
                        "sub_path": str(srv.get("sub_path") or "sub"),
                        "is_active": bool(srv.get("is_active", True)),
                    })
                if normalized:
                    return normalized
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            print(f"[config] Failed to parse SERVERS_JSON: {exc}")

    # Fall back to legacy single server
    if XUI_URL:
        return [{
            "id": DEFAULT_SERVER_ID,
            "name": os.getenv("SERVER_NAME", "Default Server"),
            "url": XUI_URL.rstrip("/"),
            "username": XUI_USERNAME,
            "password": XUI_PASSWORD,
            "inbound_id": INBOUND_ID,
            "host": HOST or IPDOMAIN or DOMAIN,
            "port": PORT,
            "sni": SNI,
            "vless_text": VLESS_TEXT,
            "sub_port": SUB_PORT,
            "sub_path": SUB_PATH,
            "is_active": True,
        }]

    return []


# Loaded at import time (used as seed for DB if DB is empty)
ENV_SERVERS = _load_servers_from_env()

# Database configuration
DB_FILE = os.getenv("DB_FILE", "xui_bot_.db")

# Payment message and feature flags
_payment_msg_raw = os.getenv("PAYMENT_MSG", "for example your bank card number or payment link")
payment_msg = _payment_msg_raw
_payment_msg_options = [msg.strip() for msg in re.split(r"[;,\n]+", _payment_msg_raw) if msg.strip()]

def get_payment_msg(cards):
    """Return a randomly selected payment message from configured values."""
    return random.choice(cards)['card_number']

ALLOW_BUY = os.getenv("ALLOW_BUY", "False").lower() in ("1", "true", "yes", "y")
USE_ONE_MONTH_MODE = os.getenv("USE_ONE_MONTH_MODE", "False").lower() in ("1", "true", "yes", "y")