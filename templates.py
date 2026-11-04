"""
ADZOHO Bot — Default Message Templates
Seeded into the DB on first run. Admins can edit them at any time via the dashboard.

Placeholders:  {first_name}  {whatsapp_link}  {bot_name}

NOTE: The WhatsApp inline button is added AUTOMATICALLY by the bot.
      You do NOT need to include the link in the template text, but you
      can if you also want it as plain text.
"""

DEFAULT_TEMPLATES: dict[str, str] = {
    # ── Welcome (Instant — after join request approved) ──────────────
    "welcome": (
        "Hi {first_name}! 👋\n"
        "\n"
        "You recently requested to join our Telegram channel.\n"
        "\n"
        "Need digital marketing services for your business?\n"
        "\n"
        "ADZOHO offers:\n"
        "• Telegram Ads & Bot Setup\n"
        "• Meta, Google & Snapchat Ads\n"
        "• Website & App Development\n"
        "• Agency Ad Accounts\n"
        "• Digital Marketing & Campaign Management\n"
        "\n"
        "📲 *Discuss your requirements with our team:*\n"
        "{whatsapp_link}\n"
        "\n"
        "Let's connect and get your project started! 🚀"
    ),
    # ── Day 2 ────────────────────────────────────────────────────────
    "followup_day2": (
        "Hi {first_name}! 👋 Just checking in.\n"
        "\n"
        "Are you looking for advertising or digital marketing "
        "services for your business?\n"
        "\n"
        "Our team is ready to discuss your requirements "
        "and help you choose the right solution.\n"
        "\n"
        "📲 *Contact us on WhatsApp:*\n"
        "{whatsapp_link}"
    ),
    # ── Day 7 ────────────────────────────────────────────────────────
    "followup_day7": (
        "Need help with Telegram Ads, Meta Ads, Google Ads, "
        "website development, or other digital services?\n"
        "\n"
        "ADZOHO can help you plan and manage your project.\n"
        "\n"
        "📲 *Let's discuss your requirements:*\n"
        "{whatsapp_link}"
    ),
    # ── Day 15 ───────────────────────────────────────────────────────
    "followup_day15": (
        "Hi {first_name}! 👋 Still considering digital marketing "
        "services for your business?\n"
        "\n"
        "Whether you need ads, a website, an app, or a Telegram bot — "
        "our team is happy to discuss your goals and pricing.\n"
        "\n"
        "📲 *Connect with ADZOHO:*\n"
        "{whatsapp_link}"
    ),
    # ── Day 30 ───────────────────────────────────────────────────────
    "followup_day30": (
        "A quick follow-up from ADZOHO! 🚀\n"
        "\n"
        "If you're planning to launch or improve your digital marketing, "
        "we're here to help with advertising, development, "
        "and campaign management.\n"
        "\n"
        "📲 *Discuss your project with us:*\n"
        "{whatsapp_link}"
    ),
    # ── Day 90 ───────────────────────────────────────────────────────
    "followup_day90": (
        "Hi {first_name}! 👋 Checking in from ADZOHO.\n"
        "\n"
        "Are you currently looking for digital marketing, advertising, "
        "or development services?\n"
        "\n"
        "If you have a project in mind, contact us to discuss "
        "your requirements with our team.\n"
        "\n"
        "📲 {whatsapp_link}"
    ),
}

# Maps follow-up stage number → template key
STAGE_TEMPLATE_MAP: dict[int, str] = {
    1: "followup_day2",
    2: "followup_day7",
    3: "followup_day15",
    4: "followup_day30",
    5: "followup_day90",
}

TEMPLATE_LABELS: dict[str, str] = {
    "welcome": "🎉 Welcome Message",
    "followup_day2": "📅 Day 2 Follow-up",
    "followup_day7": "📅 Day 7 Follow-up",
    "followup_day15": "📅 Day 15 Follow-up",
    "followup_day30": "📅 Day 30 Follow-up",
    "followup_day90": "📅 Day 90 Follow-up",
}
