import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

PROJECT_DIR = Path(__file__).resolve().parent.parent

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
GOOGLE_SHEETS_ID = os.environ.get("GOOGLE_SHEETS_ID", "")
GOOGLE_CREDS_PATH = os.environ.get("GOOGLE_CREDS_PATH", str(PROJECT_DIR / "google_credentials.json"))


def require(name: str) -> str:
    v = globals().get(name, "")
    if not v:
        raise RuntimeError(f"Falta variable de entorno: {name}")
    return v
TIMEZONE = os.environ.get("TIMEZONE", "America/Mexico_City")

MORNING_HOUR = int(os.environ.get("MORNING_HOUR", 6))
CHECKIN_HOUR = int(os.environ.get("CHECKIN_HOUR", 21))
CHECKIN_MINUTE = int(os.environ.get("CHECKIN_MINUTE", 30))
WEEKLY_DAY = int(os.environ.get("WEEKLY_DAY", 6))
WEEKLY_HOUR = int(os.environ.get("WEEKLY_HOUR", 20))
