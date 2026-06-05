"""
Configuration settings for the VPN bot
"""
import os
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
XUI_URL = os.getenv("XUI_URL", "")
XUI_USERNAME = os.getenv("XUI_USERNAME", "admin")
XUI_PASSWORD = os.getenv("XUI_PASSWORD", "")
INBOUND_ID = int(os.getenv("INBOUND_ID", os.getenv("INBOUND", "1")))

# Server configuration
IPDOMAIN = os.getenv("IPDOMAIN", "")
VLESS_TEXT = os.getenv("VLESS_TEXT","")
DOMAIN = os.getenv("DOMAIN", "")
PORT = int(os.getenv("PORT", os.getenv("SERVER_PORT", "443")))
HOST = os.getenv("HOST", "")
SNI = os.getenv("SNI", "")
SUB_PORT = int(os.getenv("SUB_PORT", "0"))
SUB_PATH = os.getenv("SUB_PATH", "sub")

# Database configuration
DB_FILE = os.getenv("DB_FILE", "xui_bot_.db")

# Payment message and feature flags
payment_msg = os.getenv("PAYMENT_MSG", "for example your bank card number or payment link")
ALLOW_BUY = os.getenv("ALLOW_BUY", "False").lower() in ("1", "true", "yes", "y")
