"""
ADZOHO Bot — Configuration
Loads settings from environment variables / .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── Core ─────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
DATABASE_PATH: str = os.getenv("DATABASE_PATH", "adzoho_bot.db")
LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

# ── Admin ────────────────────────────────────────────────────────────────
# Telegram user-id of the bot owner. Optional if ADMIN_PASSWORD is set.
SUPER_ADMIN_ID: int = int(os.getenv("SUPER_ADMIN_ID", "0"))

# Secret password/passcode to unlock admin access from Telegram
ADMIN_PASSWORD: str = os.getenv("ADMIN_PASSWORD", "ADZOHO2026")

# Additional admin IDs (comma-separated in .env, e.g. "123,456,789")
_extra = os.getenv("ADMIN_IDS", "")
ADMIN_IDS: list[int] = (
    [int(x.strip()) for x in _extra.split(",") if x.strip().isdigit()]
    if _extra else []
)

# ── WhatsApp ─────────────────────────────────────────────────────────────
WHATSAPP_DEFAULT: str = os.getenv(
    "WHATSAPP_LINK", "https://wa.me/YOUR_PHONE_NUMBER"
)

# ── Follow-up schedule (stage → days after join) ────────────────────────
FOLLOWUP_DAYS: dict[int, int] = {
    1: 2,    # Day 2
    2: 7,    # Day 7
    3: 15,   # Day 15
    4: 30,   # Day 30
    5: 90,   # Day 90
}

# ── Lead statuses ────────────────────────────────────────────────────────
STATUSES = ("New", "Contacted", "Interested", "Converted", "Not Interested")
ACTIVE_STATUSES = ("New", "Contacted", "Interested")
TERMINAL_STATUSES = ("Converted", "Not Interested", "Opted Out")
