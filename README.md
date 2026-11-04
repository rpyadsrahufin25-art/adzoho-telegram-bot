# ADZOHO — Telegram Lead Generation Bot

A production-ready Telegram bot that auto-approves channel join requests, sends
welcome messages, runs scheduled follow-up campaigns, and drives qualified
WhatsApp inquiries for ADZOHO's advertising services.

---

## 🚀 Features

| Feature | Description |
|---|---|
| **Auto-Approve** | Instantly approves channel join requests |
| **Welcome Message** | Sends branded DM immediately after approval |
| **5-Stage Follow-ups** | Automated messages on Day 2, 7, 15, 30, 90 |
| **Lead Tracking** | Status pipeline: New → Contacted → Interested → Converted |
| **Smart Stop** | Halts follow-ups on conversion, opt-out, or "Not Interested" |
| **Duplicate Guard** | Prevents the same message from being sent twice |
| **WhatsApp CTA** | Every message includes a WhatsApp contact link |
| **Admin Dashboard** | Full inline-keyboard admin panel in Telegram |
| **Editable Templates** | All message templates editable by admin in-chat |
| **Broadcast** | Send messages to all active leads at once |
| **CSV Export** | Export all lead data to CSV |
| **Lead Search** | Search leads by name, username, or ID |
| **Lead Notes** | Admins can add private notes to any lead |
| **Multi-Admin** | Add multiple admins with super-admin control |
| **Analytics** | Conversion rate, interest rate, funnel stats |

---

## 📋 Prerequisites

- Python 3.11+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- The bot added as **admin** to your Telegram channel

---

## ⚡ Quick Start

### 1. Clone / download the project

```bash
cd adzoho-bot
```

### 2. Create a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate   # macOS / Linux
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and set:
```env
BOT_TOKEN=your_bot_token_here
WHATSAPP_LINK=https://wa.me/91XXXXXXXXXX
```

### 5. Run the bot

```bash
python bot.py
```

### 6. Admin Authentication

1. Open your bot in Telegram: [@AdzohoBot](https://t.me/AdzohoBot)
2. Send `/admin`
3. The bot will ask for the **Admin Passcode** (default: `ADZOHO2026`).
4. Enter the passcode — access is granted and your Telegram user is permanently authorized!
5. You can change this passcode at any time via **⚙️ Settings → Change Admin Passcode**.

### 7. Channel setup

1. Go to your Telegram channel → Settings → Admins
2. Add `@AdzohoBot` as an admin (ensure "Invite Users via Link" / "Add Members" is enabled)
3. Enable **"Approve New Members"** in the channel join link settings
4. The bot will now auto-approve and message every new joiner

---

## ☁️ Deploying 24/7 on Render

You can host this bot on [Render.com](https://render.com) in 5 minutes:

### Step 1: Push project to GitHub
Create a private GitHub repository and push this `adzoho-bot` directory.

### Step 2: Create a Web Service on Render (100% Free)
1. Log in to [Render Dashboard](https://dashboard.render.com).
2. Click **New +** → **Web Service** *(Choose Web Service, which is 100% FREE!)*.
3. Connect your GitHub repository: `rpyadsrahufin25-art/adzoho-telegram-bot`.
4. Set the following settings:
   - **Name:** `adzoho-bot`
   - **Environment:** `Python 3`
   - **Plan:** Select **Free** ($0/month)
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `python bot.py`
5. Under **Environment Variables**, add:
   - `BOT_TOKEN`: `your_telegram_bot_token`
   - `ADMIN_PASSWORD`: `ADZOHO2026`
   - `WHATSAPP_LINK`: `https://wa.me/15819052863`
   - `DATABASE_PATH`: `adzoho_bot.db`
   - `LOG_LEVEL`: `INFO`
6. Click **Create Web Service**!

The bot runs a lightweight HTTP health check endpoint on `$PORT` so Render recognizes it as an active Web Service. The bot also automatically pings its own URL every 10 minutes to prevent Render's free tier from sleeping!

---

## 🤖 Bot Commands

### User commands
| Command | Description |
|---|---|
| `/start` | Start the bot |
| `/help` | Show help text |
| `/whatsapp` | Get the WhatsApp link |
| `/stop` | Opt out of all messages |

### Admin commands
| Command | Description |
|---|---|
| `/admin` | Open admin dashboard (prompts for passcode if not logged in) |

---

## 🛠️ Admin Dashboard

The admin dashboard is an interactive inline-keyboard panel. Access it with
`/admin`:

- **📊 Statistics** — Funnel analytics with conversion rates
- **👥 Leads** — Paginated list, tap any lead for details
- **📝 Templates** — View and edit all 6 message templates
- **⚙️ Settings** — WhatsApp link, follow-up schedule
- **📢 Broadcast** — Send a message to all active leads
- **📥 Export CSV** — Download all leads as CSV
- **🔍 Search** — Find leads by name/username/ID
- **👤 Admins** — Add or remove admin users

### Lead Detail View
Tap any lead to see:
- Status with one-tap change buttons
- Join date, last message, next follow-up
- Manual follow-up trigger
- Add/view private notes

---

## 📅 Follow-up Schedule

| Stage | Timing | Template Key |
|---|---|---|
| Welcome | Immediately | `welcome` |
| Stage 1 | Day 2 | `followup_day2` |
| Stage 2 | Day 7 | `followup_day7` |
| Stage 3 | Day 15 | `followup_day15` |
| Stage 4 | Day 30 | `followup_day30` |
| Stage 5 | Day 90 | `followup_day90` |

Follow-ups stop automatically when a lead is marked as **Converted**,
**Not Interested**, or **Opted Out**.

---

## 📝 Template Placeholders

Use these in your message templates:

| Placeholder | Replaced with |
|---|---|
| `{first_name}` | Lead's first name |
| `{whatsapp_link}` | Configured WhatsApp link |
| `{bot_name}` | "ADZOHO" |

Templates support Telegram Markdown formatting (`*bold*`, `_italic_`, etc.).

---

## 🗂️ Project Structure

```
adzoho-bot/
├── bot.py           # Main entry point, handlers, scheduler
├── config.py        # Configuration from environment
├── database.py      # Async SQLite database layer
├── templates.py     # Default message templates
├── requirements.txt # Python dependencies
├── .env.example     # Environment variable template
└── README.md        # This file
```

---

## 🔒 Security Notes

- **Never commit your `.env` file** or bot token to version control
- Add `.env` and `*.db` to your `.gitignore`
- Regenerate your bot token if it's ever exposed
- The super admin cannot be removed via the bot UI
- Only admins can access the dashboard and management features

---

## 📜 License

Private — ADZOHO proprietary software.
