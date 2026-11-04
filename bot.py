#!/usr/bin/env python3
"""
ADZOHO — Telegram Lead Generation Bot
Main entry-point: handlers, admin panel, follow-up scheduler.
"""

from __future__ import annotations

import html
import io
import logging
import math
import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

from telegram import (
    Bot,
    ChatJoinRequest,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ChatJoinRequestHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)

import config
from database import Database
from templates import DEFAULT_TEMPLATES, STAGE_TEMPLATE_MAP, TEMPLATE_LABELS

# ═════════════════════════════════════════════════════════════════════════
# Logging
# ═════════════════════════════════════════════════════════════════════════
logging.basicConfig(
    format="%(asctime)s | %(name)-18s | %(levelname)-7s | %(message)s",
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
)
logger = logging.getLogger("adzoho")

# ═════════════════════════════════════════════════════════════════════════
# Conversation states (for admin text input flows)
# ═════════════════════════════════════════════════════════════════════════
(
    STATE_EDIT_TEMPLATE,
    STATE_BROADCAST,
    STATE_SET_WHATSAPP,
    STATE_ADD_ADMIN,
    STATE_ADD_NOTE,
    STATE_SEARCH,
    STATE_AUTH_PASSWORD,
    STATE_SET_PASSWORD,
) = range(8)

# ═════════════════════════════════════════════════════════════════════════
# Globals (set during startup)
# ═════════════════════════════════════════════════════════════════════════
db: Database = Database(config.DATABASE_PATH)

PER_PAGE = 8  # leads per page in admin list


# ═════════════════════════════════════════════════════════════════════════
# Health Server (Enables 100% FREE deployment on Render Web Services)
# ═════════════════════════════════════════════════════════════════════════

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(b"OK - ADZOHO Telegram Bot is running!")

    def log_message(self, format, *args):
        pass  # Suppress HTTP access noise in logs


def start_health_server() -> None:
    port_str = os.getenv("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("Health server listening on port %d (Render Free Web Service active)", port)
    except Exception as e:
        logger.warning("Could not start health server on port %s: %s", port_str, e)


async def _self_ping(context: ContextTypes.DEFAULT_TYPE) -> None:
    url = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PING_URL")
    if url:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(url)
                logger.debug("Self-ping to %s returned %d", url, resp.status_code)
        except Exception as e:
            logger.debug("Self-ping failed: %s", e)


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════

def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _whatsapp_link() -> str:
    link = await db.get_setting("whatsapp_link")
    return link or config.WHATSAPP_DEFAULT


async def _whatsapp_button() -> InlineKeyboardMarkup:
    """Return an inline keyboard with a single WhatsApp contact button."""
    wa = await _whatsapp_link()
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("💬 Chat on WhatsApp", url=wa)]]
    )


async def _render(template_key: str, first_name: str) -> str | None:
    """Fetch a template from DB, fill placeholders, return text."""
    text = await db.get_template(template_key)
    if not text:
        return None
    wa = await _whatsapp_link()
    return text.format(
        first_name=html.escape(first_name or "there"),
        whatsapp_link=wa,
        bot_name="ADZOHO",
    )


async def _is_admin(user_id: int) -> bool:
    """Check if user is the owner, a configured admin, or a DB admin."""
    if user_id == config.SUPER_ADMIN_ID:
        return True
    if user_id in config.ADMIN_IDS:
        return True
    return await db.is_admin(user_id)


def _lead_display_name(lead: dict) -> str:
    parts = []
    if lead.get("first_name"):
        parts.append(lead["first_name"])
    if lead.get("last_name"):
        parts.append(lead["last_name"])
    name = " ".join(parts) or "Unknown"
    if lead.get("username"):
        name += f" (@{lead['username']})"
    return name


def _status_emoji(status: str) -> str:
    return {
        "New": "🆕",
        "Contacted": "📞",
        "Interested": "🔥",
        "Converted": "✅",
        "Not Interested": "❌",
        "Opted Out": "🚫",
    }.get(status, "❓")


# ═════════════════════════════════════════════════════════════════════════
# SEED default templates + settings on first run
# ═════════════════════════════════════════════════════════════════════════

async def _seed_defaults() -> None:
    for key, text in DEFAULT_TEMPLATES.items():
        existing = await db.get_template(key)
        if existing is None:
            await db.set_template(key, text)
            logger.info("Seeded template: %s", key)

    if await db.get_setting("whatsapp_link") is None:
        await db.set_setting("whatsapp_link", config.WHATSAPP_DEFAULT)

    # Seed follow-up day settings
    for stage, days in config.FOLLOWUP_DAYS.items():
        key = f"followup_days_{stage}"
        if await db.get_setting(key) is None:
            await db.set_setting(key, str(days))

    # Register super admin (REQUIRED from .env)
    if config.SUPER_ADMIN_ID:
        await db.add_admin(config.SUPER_ADMIN_ID, None, is_super=True)

    # Register any extra admins from .env
    for aid in config.ADMIN_IDS:
        await db.add_admin(aid, None, is_super=False)


# ═════════════════════════════════════════════════════════════════════════
# FOLLOW-UP SCHEDULER
# ═════════════════════════════════════════════════════════════════════════

async def _get_followup_days(stage: int) -> int:
    """Get the configured number of days for a given follow-up stage."""
    val = await db.get_setting(f"followup_days_{stage}")
    if val:
        return int(val)
    return config.FOLLOWUP_DAYS.get(stage, 0)


async def schedule_followups(
    user_id: int, application: Application
) -> None:
    """Schedule ALL future follow-ups for a newly joined lead."""
    lead = await db.get_lead(user_id)
    if not lead:
        return

    join_dt = datetime.fromisoformat(lead["join_date"])
    current_stage = lead["followup_stage"]

    for stage in sorted(STAGE_TEMPLATE_MAP.keys()):
        if stage <= current_stage:
            continue  # already done

        days = await _get_followup_days(stage)
        run_at = join_dt + timedelta(days=days)
        if run_at <= _now():
            run_at = _now() + timedelta(seconds=10)

        job_name = f"followup_{user_id}_{stage}"
        # Remove old job if it exists
        existing = application.job_queue.get_jobs_by_name(job_name)
        for j in existing:
            j.schedule_removal()

        application.job_queue.run_once(
            _execute_followup,
            when=run_at,
            name=job_name,
            data={"user_id": user_id, "stage": stage},
        )
        logger.info(
            "Scheduled followup stage %d for user %d at %s",
            stage, user_id, run_at.isoformat(),
        )

    # Store next followup info
    next_stage = current_stage + 1
    if next_stage in STAGE_TEMPLATE_MAP:
        days = await _get_followup_days(next_stage)
        next_dt = join_dt + timedelta(days=days)
        await db.update_lead_followup(
            user_id, current_stage, next_dt.isoformat()
        )


async def cancel_followups(user_id: int, application: Application) -> None:
    """Cancel all pending follow-ups for a user."""
    for stage in STAGE_TEMPLATE_MAP:
        job_name = f"followup_{user_id}_{stage}"
        jobs = application.job_queue.get_jobs_by_name(job_name)
        for j in jobs:
            j.schedule_removal()
    await db.update_lead_followup(user_id, stage=0, next_date=None)
    logger.info("Cancelled all followups for user %d", user_id)


async def _execute_followup(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Job callback: send a single follow-up message."""
    data = context.job.data
    user_id = data["user_id"]
    stage = data["stage"]

    lead = await db.get_lead(user_id)
    if not lead:
        return

    # Guard: skip if lead is no longer active
    if lead["opted_out"] or lead["status"] in config.TERMINAL_STATUSES:
        logger.info(
            "Skipping followup stage %d for user %d (status=%s)",
            stage, user_id, lead["status"],
        )
        return

    template_key = STAGE_TEMPLATE_MAP.get(stage)
    if not template_key:
        return

    # Duplicate guard
    if await db.was_message_sent(user_id, template_key):
        logger.info(
            "Duplicate guard: %s already sent to %d", template_key, user_id
        )
        return

    text = await _render(template_key, lead["first_name"])
    if not text:
        return

    try:
        wa_kb = await _whatsapp_button()
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wa_kb,
            disable_web_page_preview=False,
        )
        await db.log_message(user_id, template_key, stage)
        await db.update_lead_last_message(user_id)

        # Update followup stage and schedule next
        next_stage = stage + 1
        if next_stage in STAGE_TEMPLATE_MAP:
            join_dt = datetime.fromisoformat(lead["join_date"])
            days = await _get_followup_days(next_stage)
            next_dt = join_dt + timedelta(days=days)
            await db.update_lead_followup(user_id, stage, next_dt.isoformat())
        else:
            # Final follow-up done
            await db.update_lead_followup(user_id, stage, None)

        # Auto-update status to Contacted if still New
        if lead["status"] == "New":
            await db.update_lead_status(user_id, "Contacted")

        logger.info(
            "Sent followup stage %d (%s) to user %d",
            stage, template_key, user_id,
        )
    except Exception as e:
        logger.error(
            "Failed to send followup stage %d to user %d: %s",
            stage, user_id, e,
        )


async def _reload_pending_followups(application: Application) -> None:
    """On startup, reload all pending follow-ups from the database."""
    leads = await db.get_leads_with_pending_followups()
    count = 0
    for lead in leads:
        await schedule_followups(lead["user_id"], application)
        count += 1
    logger.info("Reloaded follow-ups for %d leads", count)


# ═════════════════════════════════════════════════════════════════════════
# HANDLER: Join Request (auto-approve + welcome)
# ═════════════════════════════════════════════════════════════════════════

async def handle_join_request(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Auto-approve the channel join request, send welcome, schedule follow-ups."""
    request: ChatJoinRequest = update.chat_join_request
    user = request.from_user

    # 1) Approve
    try:
        await request.approve()
        logger.info(
            "Approved join request: %d (%s) for chat %d",
            user.id, user.username, request.chat.id,
        )
    except Exception as e:
        logger.error("Failed to approve join request: %s", e)
        return

    # 2) Register lead
    is_new = await db.add_lead(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
        source_chat_id=request.chat.id,
    )

    if not is_new:
        logger.info("Returning lead %d, skipping welcome.", user.id)
        return

    # 3) Send welcome DM
    text = await _render("welcome", user.first_name)
    if text:
        try:
            wa_kb = await _whatsapp_button()
            await context.bot.send_message(
                chat_id=user.id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=wa_kb,
            )
            await db.log_message(user.id, "welcome")
            await db.update_lead_last_message(user.id)
            logger.info("Sent welcome to %d", user.id)
        except Exception as e:
            logger.error("Could not DM user %d: %s", user.id, e)

    # 4) Schedule follow-ups
    await schedule_followups(user.id, context.application)


# ═════════════════════════════════════════════════════════════════════════
# HANDLER: /start
# ═════════════════════════════════════════════════════════════════════════

async def handle_start(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user

    # Register as lead if new (direct /start)
    await db.add_lead(
        user_id=user.id,
        username=user.username,
        first_name=user.first_name,
        last_name=user.last_name,
    )

    wa = await _whatsapp_link()
    wa_kb = await _whatsapp_button()
    text = (
        f"👋 Hi *{html.escape(user.first_name or 'there')}!*\n\n"
        "Welcome to *ADZOHO* — your growth partner in digital advertising.\n\n"
        "Need digital marketing services?\n"
        "Tap the button below to discuss your requirements with our team.\n\n"
        "Type /help for available commands."
    )
    await update.message.reply_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=wa_kb
    )


# ═════════════════════════════════════════════════════════════════════════
# HANDLER: /help
# ═════════════════════════════════════════════════════════════════════════

async def handle_help(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user = update.effective_user
    text = (
        "📖 *ADZOHO Bot Commands*\n\n"
        "/start — Start the bot\n"
        "/help — Show this help\n"
        "/stop — Opt out of messages\n"
        "/whatsapp — Get our WhatsApp link\n"
    )
    # Only show admin commands to actual admins
    if await _is_admin(user.id):
        text += (
            "\n🔐 *Admin Commands:*\n"
            "/admin — Open admin dashboard\n"
        )
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)


# ═════════════════════════════════════════════════════════════════════════
# HANDLER: /stop (opt out)
# ═════════════════════════════════════════════════════════════════════════

async def handle_stop(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    user_id = update.effective_user.id
    lead = await db.get_lead(user_id)
    if lead:
        await db.mark_opted_out(user_id)
        await cancel_followups(user_id, context.application)
    await update.message.reply_text(
        "✅ You've been opted out. You won't receive any more messages.\n"
        "If you change your mind, just /start again!"
    )


# ═════════════════════════════════════════════════════════════════════════
# HANDLER: /whatsapp
# ═════════════════════════════════════════════════════════════════════════

async def handle_whatsapp(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    wa_kb = await _whatsapp_button()
    await update.message.reply_text(
        "📲 *Chat with ADZOHO on WhatsApp:*\n\nTap the button below to connect with us!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=wa_kb,
    )


# ═════════════════════════════════════════════════════════════════════════
# ADMIN DASHBOARD
# ═════════════════════════════════════════════════════════════════════════

async def _admin_guard(update: Update) -> bool:
    """Strictly verify admin identity. Non-admins get a prompt to authenticate."""
    user_id = (
        update.effective_user.id if update.effective_user else None
    )
    is_adm = await _is_admin(user_id) if user_id else False
    if not user_id or not is_adm:
        if update.callback_query:
            await update.callback_query.answer(
                "⛔ Access denied. Type /admin and enter passcode.", show_alert=True
            )
        elif update.effective_message:
            await update.effective_message.reply_text(
                "🔐 *Admin Access Required*\n\n"
                "Please type /admin to enter the admin passcode.",
                parse_mode=ParseMode.MARKDOWN,
            )
        return False
    return True


def _main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("📊 Statistics", callback_data="s"),
                InlineKeyboardButton("👥 Leads", callback_data="l:1"),
            ],
            [
                InlineKeyboardButton("📝 Templates", callback_data="t"),
                InlineKeyboardButton("⚙️ Settings", callback_data="st"),
            ],
            [
                InlineKeyboardButton("📢 Broadcast", callback_data="bc"),
                InlineKeyboardButton("📥 Export CSV", callback_data="ex"),
            ],
            [
                InlineKeyboardButton("🔍 Search", callback_data="sr"),
                InlineKeyboardButton("👤 Admins", callback_data="ad"),
            ],
        ]
    )


async def _show_dashboard(update: Update) -> None:
    stats = await db.get_lead_stats()
    total = stats.get("Total", 0)
    text = (
        "🏠 *ADZOHO Admin Dashboard*\n\n"
        f"📊 Total Leads: *{total}*\n"
    )
    for status_name in [*config.STATUSES, "Opted Out"]:
        cnt = stats.get(status_name, 0)
        if cnt:
            text += f"  {_status_emoji(status_name)} {status_name}: *{cnt}*\n"

    msg = update.effective_message
    if msg:
        try:
            await msg.reply_text(
                text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=_main_menu_keyboard(),
            )
        except Exception:
            await msg.reply_text(
                text.replace("*", ""),
                reply_markup=_main_menu_keyboard(),
            )


async def admin_panel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    if not user:
        return ConversationHandler.END

    if await _is_admin(user.id):
        await _show_dashboard(update)
        return ConversationHandler.END

    msg = update.effective_message
    if msg:
        await msg.reply_text(
            "🔐 *Admin Authentication*\n\n"
            "Please enter the *Admin Passcode* to access the dashboard:\n\n"
            "_(Send /cancel to abort)_",
            parse_mode=ParseMode.MARKDOWN,
        )
    return STATE_AUTH_PASSWORD


async def _handle_auth_password(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    msg = update.effective_message
    if not user or not msg or not msg.text:
        return ConversationHandler.END

    entered_pass = msg.text.strip()
    current_pass = await db.get_setting("admin_password") or config.ADMIN_PASSWORD

    if entered_pass == current_pass:
        await db.add_admin(user.id, user.username, is_super=True)
        try:
            await msg.delete()
        except Exception:
            pass

        await msg.reply_text(
            f"🎉 *Access Granted!*\n\n"
            f"Welcome, {html.escape(user.first_name or 'Admin')}! You are now authorized as an administrator.\n"
            f"Use /admin anytime to open your dashboard.",
            parse_mode=ParseMode.MARKDOWN,
        )
        await _show_dashboard(update)
        return ConversationHandler.END
    else:
        await msg.reply_text("❌ Incorrect passcode. Access denied.")
        return ConversationHandler.END


# ═════════════════════════════════════════════════════════════════════════
# CALLBACK QUERY ROUTER
# ═════════════════════════════════════════════════════════════════════════

async def handle_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int | None:
    query = update.callback_query
    await query.answer()
    data = query.data

    if not await _admin_guard(update):
        return None

    # ── Main menu ────────────────────────────────────────────────────
    if data == "m":
        return await _cb_main_menu(query, context)

    # ── Statistics ───────────────────────────────────────────────────
    if data == "s":
        return await _cb_stats(query, context)

    # ── Leads list ───────────────────────────────────────────────────
    if data.startswith("l:"):
        return await _cb_leads(query, context, data)

    # ── Lead filter ──────────────────────────────────────────────────
    if data.startswith("lf:"):
        return await _cb_leads_filtered(query, context, data)

    # ── Lead detail ──────────────────────────────────────────────────
    if data.startswith("ld:"):
        return await _cb_lead_detail(query, context, data)

    # ── Status change ────────────────────────────────────────────────
    if data.startswith("ls:"):
        return await _cb_lead_status(query, context, data)

    # ── Templates ────────────────────────────────────────────────────
    if data == "t":
        return await _cb_templates(query, context)
    if data.startswith("tv:"):
        return await _cb_template_view(query, context, data)
    if data.startswith("te:"):
        return await _cb_template_edit_start(query, context, data)

    # ── Settings ─────────────────────────────────────────────────────
    if data == "st":
        return await _cb_settings(query, context)
    if data == "st:wa":
        return await _cb_set_whatsapp_start(query, context)
    if data == "st:pass":
        return await _cb_set_password_start(query, context)

    # ── Broadcast ────────────────────────────────────────────────────
    if data == "bc":
        return await _cb_broadcast_start(query, context)
    if data == "bcc":
        return await _cb_broadcast_confirm(query, context)
    if data == "bcx":
        return await _cb_broadcast_cancel(query, context)

    # ── Export ────────────────────────────────────────────────────────
    if data == "ex":
        return await _cb_export(query, context)

    # ── Search ───────────────────────────────────────────────────────
    if data == "sr":
        return await _cb_search_start(query, context)

    # ── Admins ───────────────────────────────────────────────────────
    if data == "ad":
        return await _cb_admins(query, context)
    if data == "ad:add":
        return await _cb_admin_add_start(query, context)
    if data.startswith("ad:rm:"):
        return await _cb_admin_remove(query, context, data)

    # ── Notes ────────────────────────────────────────────────────────
    if data.startswith("nt:"):
        return await _cb_note_start(query, context, data)
    if data.startswith("nv:"):
        return await _cb_notes_view(query, context, data)

    # ── Manual followup ──────────────────────────────────────────────
    if data.startswith("mf:"):
        return await _cb_manual_followup(query, context, data)

    return None


# ── Callback implementations ────────────────────────────────────────────

async def _cb_main_menu(query, context) -> None:
    stats = await db.get_lead_stats()
    total = stats.get("Total", 0)
    text = (
        "🏠 *ADZOHO Admin Dashboard*\n\n"
        f"📊 Total Leads: *{total}*\n"
    )
    for status_name in [*config.STATUSES, "Opted Out"]:
        cnt = stats.get(status_name, 0)
        if cnt:
            text += f"  {_status_emoji(status_name)} {status_name}: *{cnt}*\n"

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=_main_menu_keyboard(),
    )


async def _cb_stats(query, context) -> None:
    stats = await db.get_lead_stats()
    total = stats.get("Total", 0)

    new = stats.get("New", 0)
    contacted = stats.get("Contacted", 0)
    interested = stats.get("Interested", 0)
    converted = stats.get("Converted", 0)
    not_int = stats.get("Not Interested", 0)
    opted = stats.get("Opted Out", 0)

    # Conversion funnel
    conv_rate = (converted / total * 100) if total else 0
    interest_rate = (interested / total * 100) if total else 0
    active = new + contacted + interested

    text = (
        "📊 *ADZOHO Analytics Dashboard*\n\n"
        f"📈 *Overview:*\n"
        f"  Total Leads: *{total}*\n"
        f"  Active Pipeline: *{active}*\n\n"
        f"🔥 *Funnel Breakdown:*\n"
        f"  🆕 New: *{new}*\n"
        f"  📞 Contacted: *{contacted}*\n"
        f"  🔥 Interested: *{interested}*\n"
        f"  ✅ Converted: *{converted}*\n"
        f"  ❌ Not Interested: *{not_int}*\n"
        f"  🚫 Opted Out: *{opted}*\n\n"
        f"🎯 *Rates:*\n"
        f"  Interest Rate: *{interest_rate:.1f}%*\n"
        f"  Conversion Rate: *{conv_rate:.1f}%*\n"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    f"🆕 New ({new})", callback_data="lf:New:1"
                ),
                InlineKeyboardButton(
                    f"📞 Contacted ({contacted})",
                    callback_data="lf:Contacted:1",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"🔥 Interested ({interested})",
                    callback_data="lf:Interested:1",
                ),
                InlineKeyboardButton(
                    f"✅ Converted ({converted})",
                    callback_data="lf:Converted:1",
                ),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="m")],
        ]
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
    )


async def _cb_leads(query, context, data: str) -> None:
    parts = data.split(":")
    page = int(parts[1]) if len(parts) > 1 else 1

    leads, total = await db.get_leads(page=page, per_page=PER_PAGE)
    pages = math.ceil(total / PER_PAGE) or 1

    text = f"👥 *All Leads* — Page {page}/{pages} ({total} total)\n\n"
    if not leads:
        text += "_No leads yet._"

    buttons = []
    for lead in leads:
        name = _lead_display_name(lead)
        emoji = _status_emoji(lead["status"])
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{emoji} {name}",
                    callback_data=f"ld:{lead['user_id']}",
                )
            ]
        )

    # Pagination row
    nav = []
    if page > 1:
        nav.append(
            InlineKeyboardButton("⬅️ Prev", callback_data=f"l:{page - 1}")
        )
    if page < pages:
        nav.append(
            InlineKeyboardButton("➡️ Next", callback_data=f"l:{page + 1}")
        )
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="m")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _cb_leads_filtered(query, context, data: str) -> None:
    _, status, page_str = data.split(":")
    page = int(page_str)

    # URL-safe status decode
    status_map = {
        "New": "New",
        "Contacted": "Contacted",
        "Interested": "Interested",
        "Converted": "Converted",
        "NotInterested": "Not Interested",
        "Not Interested": "Not Interested",
        "Opted Out": "Opted Out",
    }
    actual_status = status_map.get(status, status)

    leads, total = await db.get_leads(
        status=actual_status, page=page, per_page=PER_PAGE
    )
    pages = math.ceil(total / PER_PAGE) or 1
    emoji = _status_emoji(actual_status)

    text = (
        f"{emoji} *{actual_status} Leads* — "
        f"Page {page}/{pages} ({total} total)\n\n"
    )
    if not leads:
        text += "_No leads with this status._"

    buttons = []
    for lead in leads:
        name = _lead_display_name(lead)
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{name}",
                    callback_data=f"ld:{lead['user_id']}",
                )
            ]
        )

    # pagination
    safe_status = status.replace(" ", "")
    nav = []
    if page > 1:
        nav.append(
            InlineKeyboardButton(
                "⬅️ Prev", callback_data=f"lf:{safe_status}:{page-1}"
            )
        )
    if page < pages:
        nav.append(
            InlineKeyboardButton(
                "➡️ Next", callback_data=f"lf:{safe_status}:{page+1}"
            )
        )
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="s")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _cb_lead_detail(query, context, data: str) -> None:
    user_id = int(data.split(":")[1])
    lead = await db.get_lead(user_id)
    if not lead:
        await query.edit_message_text("❌ Lead not found.")
        return

    name = _lead_display_name(lead)
    emoji = _status_emoji(lead["status"])
    join = lead["join_date"][:10] if lead["join_date"] else "N/A"
    last_msg = lead["last_msg_date"][:10] if lead["last_msg_date"] else "N/A"
    next_fu = lead["next_followup"][:10] if lead["next_followup"] else "None"
    stage = lead["followup_stage"]

    text = (
        f"👤 *Lead Detail*\n\n"
        f"*Name:* {html.escape(name)}\n"
        f"*User ID:* `{user_id}`\n"
        f"*Status:* {emoji} {lead['status']}\n"
        f"*Joined:* {join}\n"
        f"*Last Message:* {last_msg}\n"
        f"*Follow-up Stage:* {stage}/5\n"
        f"*Next Follow-up:* {next_fu}\n"
        f"*Opted Out:* {'Yes' if lead['opted_out'] else 'No'}\n"
    )

    # Status change buttons
    status_buttons = []
    for s in config.STATUSES:
        if s != lead["status"]:
            status_buttons.append(
                InlineKeyboardButton(
                    f"{_status_emoji(s)} {s}",
                    callback_data=f"ls:{user_id}:{s}",
                )
            )

    rows = [status_buttons[i : i + 2] for i in range(0, len(status_buttons), 2)]

    rows.append(
        [
            InlineKeyboardButton(
                "📩 Send Follow-up Now", callback_data=f"mf:{user_id}"
            ),
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "📝 Add Note", callback_data=f"nt:{user_id}"
            ),
            InlineKeyboardButton(
                "📋 View Notes", callback_data=f"nv:{user_id}"
            ),
        ]
    )
    rows.append([InlineKeyboardButton("🔙 Back", callback_data="l:1")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(rows),
    )


async def _cb_lead_status(query, context, data: str) -> None:
    parts = data.split(":")
    user_id = int(parts[1])
    new_status = parts[2]

    await db.update_lead_status(user_id, new_status)

    # If terminal status, cancel follow-ups
    if new_status in config.TERMINAL_STATUSES:
        await cancel_followups(user_id, context.application)

    await query.answer(f"✅ Status changed to {new_status}")
    # Refresh lead detail
    await _cb_lead_detail(query, context, f"ld:{user_id}")


# ── Templates ────────────────────────────────────────────────────────────

async def _cb_templates(query, context) -> None:
    templates = await db.get_all_templates()
    text = "📝 *Message Templates*\n\nTap a template to view or edit:\n"

    buttons = []
    for tpl in templates:
        label = TEMPLATE_LABELS.get(tpl["key"], tpl["key"])
        buttons.append(
            [
                InlineKeyboardButton(
                    label, callback_data=f"tv:{tpl['key']}"
                )
            ]
        )
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="m")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _cb_template_view(query, context, data: str) -> None:
    key = data.split(":", 1)[1]
    text_content = await db.get_template(key)
    label = TEMPLATE_LABELS.get(key, key)

    # Show raw template text (escaped so markdown doesn't apply)
    preview = text_content[:800] if text_content else "_Empty_"
    text = (
        f"📝 *{label}*\n\n"
        f"```\n{preview}\n```\n\n"
        f"_Placeholders:_ `{{first_name}}`, `{{whatsapp_link}}`, `{{bot_name}}`"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✏️ Edit", callback_data=f"te:{key}"
                )
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="t")],
        ]
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
    )


async def _cb_template_edit_start(query, context, data: str) -> int:
    key = data.split(":", 1)[1]
    context.user_data["editing_template"] = key
    label = TEMPLATE_LABELS.get(key, key)

    await query.edit_message_text(
        f"✏️ *Editing: {label}*\n\n"
        f"Send me the new template text.\n"
        f"Use these placeholders:\n"
        f"  `{{first_name}}` — Lead's first name\n"
        f"  `{{whatsapp_link}}` — WhatsApp link\n"
        f"  `{{bot_name}}` — Bot name\n\n"
        f"Send /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return STATE_EDIT_TEMPLATE


# ── Settings ─────────────────────────────────────────────────────────────

async def _cb_settings(query, context) -> None:
    wa = await _whatsapp_link()
    cur_pass = await db.get_setting("admin_password") or config.ADMIN_PASSWORD

    # Get follow-up days
    schedule_lines = []
    for stage in sorted(config.FOLLOWUP_DAYS.keys()):
        days = await _get_followup_days(stage)
        tpl_key = STAGE_TEMPLATE_MAP.get(stage, "?")
        schedule_lines.append(f"  Stage {stage}: Day *{days}* ({tpl_key})")

    text = (
        "⚙️ *Bot Settings*\n\n"
        f"📲 *WhatsApp Link:*\n{wa}\n\n"
        f"🔑 *Admin Passcode:* `{cur_pass}`\n\n"
        f"📅 *Follow-up Schedule:*\n"
        + "\n".join(schedule_lines)
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📲 Change WhatsApp Link", callback_data="st:wa"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔑 Change Admin Passcode", callback_data="st:pass"
                )
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="m")],
        ]
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
    )


async def _cb_set_whatsapp_start(query, context) -> int:
    await query.edit_message_text(
        "📲 Send me the new WhatsApp link.\n"
        "Format: `https://wa.me/91XXXXXXXXXX`\n\n"
        "Send /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return STATE_SET_WHATSAPP


async def _cb_set_password_start(query, context) -> int:
    await query.edit_message_text(
        "🔑 *Change Admin Passcode*\n\n"
        "Send the new passcode/password for admin access.\n\n"
        "Send /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return STATE_SET_PASSWORD


# ── Broadcast ────────────────────────────────────────────────────────────

async def _cb_broadcast_start(query, context) -> int:
    leads = await db.get_all_active_leads()
    count = len(leads)
    await query.edit_message_text(
        f"📢 *Broadcast Message*\n\n"
        f"This will send a message to *{count}* active leads.\n\n"
        f"Type the message you want to broadcast.\n"
        f"Use `{{first_name}}` and `{{whatsapp_link}}` placeholders.\n\n"
        f"Send /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return STATE_BROADCAST


async def _cb_broadcast_confirm(query, context) -> None:
    text = context.user_data.get("broadcast_text")
    if not text:
        await query.edit_message_text("❌ No broadcast message found.")
        return

    leads = await db.get_all_active_leads()
    sent = 0
    failed = 0
    wa = await _whatsapp_link()
    wa_kb = await _whatsapp_button()

    for lead in leads:
        try:
            msg = text.format(
                first_name=html.escape(lead["first_name"] or "there"),
                whatsapp_link=wa,
                bot_name="ADZOHO",
            )
            await context.bot.send_message(
                chat_id=lead["user_id"],
                text=msg,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=wa_kb,
            )
            await db.log_message(lead["user_id"], "broadcast")
            await db.update_lead_last_message(lead["user_id"])
            sent += 1
        except Exception as e:
            logger.error("Broadcast failed for %d: %s", lead["user_id"], e)
            failed += 1

    context.user_data.pop("broadcast_text", None)
    await query.edit_message_text(
        f"📢 *Broadcast Complete!*\n\n"
        f"✅ Sent: *{sent}*\n"
        f"❌ Failed: *{failed}*",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="m")]]
        ),
    )


async def _cb_broadcast_cancel(query, context) -> None:
    context.user_data.pop("broadcast_text", None)
    await query.edit_message_text(
        "❌ Broadcast cancelled.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="m")]]
        ),
    )


# ── Export ────────────────────────────────────────────────────────────────

async def _cb_export(query, context) -> None:
    csv_data = await db.export_leads_csv()
    if not csv_data:
        await query.edit_message_text(
            "📥 No leads to export.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Back", callback_data="m")]]
            ),
        )
        return

    bio = io.BytesIO(csv_data.encode("utf-8"))
    bio.name = f"adzoho_leads_{_now().strftime('%Y%m%d_%H%M%S')}.csv"

    await query.message.reply_document(
        document=bio,
        caption="📥 *ADZOHO Leads Export*",
        parse_mode=ParseMode.MARKDOWN,
    )
    await query.edit_message_text(
        "📥 Export sent! ✅",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Back", callback_data="m")]]
        ),
    )


# ── Search ───────────────────────────────────────────────────────────────

async def _cb_search_start(query, context) -> int:
    await query.edit_message_text(
        "🔍 *Search Leads*\n\n"
        "Send a name, username, or user ID to search.\n\n"
        "Send /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return STATE_SEARCH


# ── Admins ───────────────────────────────────────────────────────────────

async def _cb_admins(query, context) -> None:
    admins = await db.get_all_admins()
    text = "👤 *Admin Management*\n\n"
    buttons = []
    for adm in admins:
        name = adm["username"] or str(adm["user_id"])
        super_tag = " 👑" if adm["is_super"] else ""
        text += f"• {name}{super_tag} (`{adm['user_id']}`)\n"
        if not adm["is_super"]:
            buttons.append(
                [
                    InlineKeyboardButton(
                        f"❌ Remove {name}",
                        callback_data=f"ad:rm:{adm['user_id']}",
                    )
                ]
            )

    buttons.append(
        [InlineKeyboardButton("➕ Add Admin", callback_data="ad:add")]
    )
    buttons.append([InlineKeyboardButton("🔙 Back", callback_data="m")])

    await query.edit_message_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )


async def _cb_admin_add_start(query, context) -> int:
    await query.edit_message_text(
        "➕ *Add Admin*\n\n"
        "Forward a message from the new admin, or send their User ID.\n\n"
        "Send /cancel to abort.",
        parse_mode=ParseMode.MARKDOWN,
    )
    return STATE_ADD_ADMIN


async def _cb_admin_remove(query, context, data: str) -> None:
    admin_id = int(data.split(":")[2])
    await db.remove_admin(admin_id)
    await query.answer("✅ Admin removed")
    await _cb_admins(query, context)


# ── Notes ────────────────────────────────────────────────────────────────

async def _cb_note_start(query, context, data: str) -> int:
    user_id = int(data.split(":")[1])
    context.user_data["note_lead_id"] = user_id
    await query.edit_message_text(
        "📝 Send the note text for this lead.\n\n"
        "Send /cancel to abort."
    )
    return STATE_ADD_NOTE


async def _cb_notes_view(query, context, data: str) -> None:
    user_id = int(data.split(":")[1])
    notes = await db.get_notes(user_id)

    if not notes:
        text = "📋 *No notes for this lead.*"
    else:
        text = "📋 *Lead Notes:*\n\n"
        for note in notes:
            date = note["created_at"][:10]
            text += f"• _{date}_ — {note['note']}\n"

    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("🔙 Back", callback_data=f"ld:{user_id}")]]
    )
    await query.edit_message_text(
        text, parse_mode=ParseMode.MARKDOWN, reply_markup=keyboard
    )


# ── Manual follow-up ────────────────────────────────────────────────────

async def _cb_manual_followup(query, context, data: str) -> None:
    user_id = int(data.split(":")[1])
    lead = await db.get_lead(user_id)
    if not lead:
        await query.answer("❌ Lead not found", show_alert=True)
        return

    next_stage = lead["followup_stage"] + 1
    if next_stage not in STAGE_TEMPLATE_MAP:
        await query.answer(
            "✅ All follow-ups already completed", show_alert=True
        )
        return

    template_key = STAGE_TEMPLATE_MAP[next_stage]

    # Duplicate guard
    if await db.was_message_sent(user_id, template_key):
        await query.answer("⚠️ This follow-up was already sent", show_alert=True)
        return

    text = await _render(template_key, lead["first_name"])
    if not text:
        await query.answer("❌ Template not found", show_alert=True)
        return

    try:
        wa_kb = await _whatsapp_button()
        await context.bot.send_message(
            chat_id=user_id,
            text=text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=wa_kb,
        )
        await db.log_message(user_id, template_key, next_stage)
        await db.update_lead_last_message(user_id)

        # Update stage
        further = next_stage + 1
        if further in STAGE_TEMPLATE_MAP:
            join_dt = datetime.fromisoformat(lead["join_date"])
            days = await _get_followup_days(further)
            next_dt = join_dt + timedelta(days=days)
            await db.update_lead_followup(user_id, next_stage, next_dt.isoformat())
        else:
            await db.update_lead_followup(user_id, next_stage, None)

        if lead["status"] == "New":
            await db.update_lead_status(user_id, "Contacted")

        await query.answer(f"✅ Sent {template_key}!")
        await _cb_lead_detail(query, context, f"ld:{user_id}")
    except Exception as e:
        await query.answer(f"❌ Failed: {e}", show_alert=True)


# ═════════════════════════════════════════════════════════════════════════
# CONVERSATION HANDLER: text input states
# ═════════════════════════════════════════════════════════════════════════

async def _text_edit_template(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    key = context.user_data.get("editing_template")
    if not key:
        await update.message.reply_text("❌ No template being edited.")
        return ConversationHandler.END

    new_text = update.message.text
    await db.set_template(key, new_text)
    context.user_data.pop("editing_template", None)
    label = TEMPLATE_LABELS.get(key, key)

    await update.message.reply_text(
        f"✅ *{label}* updated successfully!",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Dashboard", callback_data="m")]]
        ),
    )
    return ConversationHandler.END


async def _text_broadcast(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    text = update.message.text
    context.user_data["broadcast_text"] = text
    leads = await db.get_all_active_leads()
    count = len(leads)

    await update.message.reply_text(
        f"📢 *Preview your broadcast:*\n\n"
        f"{text}\n\n"
        f"This will be sent to *{count}* active leads.",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "✅ Send Now", callback_data="bcc"
                    ),
                    InlineKeyboardButton(
                        "❌ Cancel", callback_data="bcx"
                    ),
                ]
            ]
        ),
    )
    return ConversationHandler.END


async def _text_set_whatsapp(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    link = update.message.text.strip()
    if not link.startswith("http"):
        link = f"https://wa.me/{link}"

    await db.set_setting("whatsapp_link", link)
    await update.message.reply_text(
        f"✅ WhatsApp link updated:\n{link}",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Dashboard", callback_data="m")]]
        ),
    )
    return ConversationHandler.END


async def _text_set_password(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    new_pass = update.message.text.strip()
    if not new_pass:
        await update.message.reply_text("❌ Passcode cannot be empty.")
        return STATE_SET_PASSWORD

    await db.set_setting("admin_password", new_pass)
    await update.message.reply_text(
        f"✅ Admin passcode updated to: `{new_pass}`",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Dashboard", callback_data="m")]]
        ),
    )
    return ConversationHandler.END


async def _text_add_admin(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    msg = update.message

    # Check if forwarded message
    if msg.forward_from:
        new_admin = msg.forward_from
        await db.add_admin(new_admin.id, new_admin.username)
        await msg.reply_text(
            f"✅ Added admin: {new_admin.first_name} "
            f"(`{new_admin.id}`)",
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Dashboard", callback_data="m")]]
            ),
        )
    else:
        # Try parsing as user ID
        try:
            admin_id = int(msg.text.strip())
            await db.add_admin(admin_id, None)
            await msg.reply_text(
                f"✅ Added admin: `{admin_id}`",
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "🔙 Dashboard", callback_data="m"
                            )
                        ]
                    ]
                ),
            )
        except ValueError:
            await msg.reply_text(
                "❌ Invalid input. Send a User ID or forward a message.\n"
                "Send /cancel to abort."
            )
            return STATE_ADD_ADMIN

    return ConversationHandler.END


async def _text_add_note(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    lead_id = context.user_data.get("note_lead_id")
    if not lead_id:
        await update.message.reply_text("❌ Error: no lead selected.")
        return ConversationHandler.END

    note = update.message.text
    await db.add_note(lead_id, update.effective_user.id, note)
    context.user_data.pop("note_lead_id", None)

    await update.message.reply_text(
        "✅ Note added!",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Lead", callback_data=f"ld:{lead_id}")]]
        ),
    )
    return ConversationHandler.END


async def _text_search(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    query_str = update.message.text.strip()
    results = await db.search_leads(query_str)

    if not results:
        await update.message.reply_text(
            f"🔍 No leads found for '{html.escape(query_str)}'.",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🔙 Dashboard", callback_data="m")]]
            ),
        )
        return ConversationHandler.END

    text = f"🔍 *Search Results for '{html.escape(query_str)}':*\n\n"
    buttons = []
    for lead in results[:10]:
        name = _lead_display_name(lead)
        emoji = _status_emoji(lead["status"])
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{emoji} {name}",
                    callback_data=f"ld:{lead['user_id']}",
                )
            ]
        )
    buttons.append([InlineKeyboardButton("🔙 Dashboard", callback_data="m")])

    await update.message.reply_text(
        text,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=InlineKeyboardMarkup(buttons),
    )
    return ConversationHandler.END


async def _cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    context.user_data.pop("editing_template", None)
    context.user_data.pop("broadcast_text", None)
    context.user_data.pop("note_lead_id", None)
    await update.message.reply_text(
        "❌ Cancelled.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🔙 Dashboard", callback_data="m")]]
        ),
    )
    return ConversationHandler.END


# ═════════════════════════════════════════════════════════════════════════
# POST-INIT: database + scheduler
# ═════════════════════════════════════════════════════════════════════════

async def post_init(application: Application) -> None:
    await db.connect()
    await _seed_defaults()
    await _reload_pending_followups(application)
    # Prevent Render free tier from sleeping by self-pinging every 10 minutes
    if os.getenv("RENDER_EXTERNAL_URL") or os.getenv("PING_URL"):
        application.job_queue.run_repeating(_self_ping, interval=600, first=60)
        logger.info("Scheduled keep-alive self-ping every 10 minutes (Render Free tier mode)")
    logger.info("ADZOHO bot initialized ✅")


async def post_shutdown(application: Application) -> None:
    await db.close()
    logger.info("ADZOHO bot shut down.")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update: %s", context.error, exc_info=context.error)


# ═════════════════════════════════════════════════════════════════════════
# MAIN
# ═════════════════════════════════════════════════════════════════════════

def main() -> None:
    if not config.BOT_TOKEN:
        print("❌ ERROR: BOT_TOKEN not set. Check your .env file.")
        sys.exit(1)

    if not config.SUPER_ADMIN_ID and not config.ADMIN_PASSWORD:
        print("❌ ERROR: Neither SUPER_ADMIN_ID nor ADMIN_PASSWORD set in .env file.")
        print("   Set at least ADMIN_PASSWORD (e.g. ADMIN_PASSWORD=ADZOHO2026).")
        sys.exit(1)

    logger.info("Admin security initialized. Owner: %d, Passcode set: %s",
                config.SUPER_ADMIN_ID, bool(config.ADMIN_PASSWORD))

    # Start health server for Render Free Web Service (if PORT is set)
    start_health_server()

    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # ── Conversation handler for admin auth & text-input flows ───────
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("admin", admin_panel),
            CallbackQueryHandler(handle_callback),
        ],
        states={
            STATE_AUTH_PASSWORD: [
                CommandHandler("cancel", _cancel),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _handle_auth_password
                ),
            ],
            STATE_SET_PASSWORD: [
                CommandHandler("cancel", _cancel),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _text_set_password
                ),
            ],
            STATE_EDIT_TEMPLATE: [
                CommandHandler("cancel", _cancel),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _text_edit_template
                ),
            ],
            STATE_BROADCAST: [
                CommandHandler("cancel", _cancel),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _text_broadcast
                ),
            ],
            STATE_SET_WHATSAPP: [
                CommandHandler("cancel", _cancel),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _text_set_whatsapp
                ),
            ],
            STATE_ADD_ADMIN: [
                CommandHandler("cancel", _cancel),
                MessageHandler(
                    (filters.TEXT | filters.FORWARDED) & ~filters.COMMAND,
                    _text_add_admin,
                ),
            ],
            STATE_ADD_NOTE: [
                CommandHandler("cancel", _cancel),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _text_add_note
                ),
            ],
            STATE_SEARCH: [
                CommandHandler("cancel", _cancel),
                MessageHandler(
                    filters.TEXT & ~filters.COMMAND, _text_search
                ),
            ],
        },
        fallbacks=[CommandHandler("cancel", _cancel)],
        per_message=False,
    )

    # ── Register handlers ────────────────────────────────────────────
    app.add_error_handler(error_handler)
    app.add_handler(ChatJoinRequestHandler(handle_join_request))
    app.add_handler(CommandHandler("start", handle_start))
    app.add_handler(CommandHandler("help", handle_help))
    app.add_handler(CommandHandler("stop", handle_stop))
    app.add_handler(CommandHandler("whatsapp", handle_whatsapp))
    app.add_handler(conv_handler)

    # ── Run ──────────────────────────────────────────────────────────
    logger.info("🚀 Starting ADZOHO Bot…")
    app.run_polling(
        allowed_updates=[
            "message",
            "callback_query",
            "chat_join_request",
        ],
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
