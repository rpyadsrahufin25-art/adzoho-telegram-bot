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

# ── Admin Passcodes ──────────────────────────────────────────────────────
# Tier 1: Super Admin (Owner - full control, settings, passwords, export, broadcast)
SUPER_ADMIN_PASSWORD: str = os.getenv("SUPER_ADMIN_PASSWORD", "ADZOHO_SUPER_2026")

# Tier 2: Normal Admin (Team / Staff - stats, leads, search, follow-ups)
NORMAL_ADMIN_PASSWORD: str = os.getenv("NORMAL_ADMIN_PASSWORD", "ADZOHO_ADMIN_2026")

# ── Support ──────────────────────────────────────────────────────────────
TELEGRAM_SUPPORT_USERNAME: str = os.getenv("TELEGRAM_SUPPORT_USERNAME", "Adzoho")

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
