"""Optional Telegram bot client for CHINNU FF API.
Run as a separate process/service. It does not expose API keys in chat output.
Environment variables: BOT_TOKEN, API_BASE_URL, API_KEY, ALLOWED_TELEGRAM_IDS (comma-separated IDs).
"""
import os
import asyncio
import aiohttp
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
API_BASE_URL = os.getenv("API_BASE_URL", "").strip().rstrip("/")
API_KEY = os.getenv("API_KEY", "").strip()
ALLOWED_IDS = {x.strip() for x in os.getenv("ALLOWED_TELEGRAM_IDS", "").split(",") if x.strip()}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("CHINNU API Bot is ready.\nUse /player UID REGION (example: /player 123456789 IND).")

async def player(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if ALLOWED_IDS and str(update.effective_user.id) not in ALLOWED_IDS:
        await update.message.reply_text("You are not allowed to use this bot.")
        return
    if len(context.args) < 1:
        await update.message.reply_text("Usage: /player UID [REGION]\nExample: /player 123456789 IND")
        return
    uid = context.args[0].strip()
    region = context.args[1].strip().upper() if len(context.args) > 1 else "IND"
    if not uid.isdigit() or int(uid) <= 0:
        await update.message.reply_text("UID must be a positive number.")
        return
    if not (BOT_TOKEN and API_BASE_URL and API_KEY):
        await update.message.reply_text("Bot setup is incomplete. Ask the owner to configure environment variables.")
        return
    url = f"{API_BASE_URL}/player-info"
    try:
        timeout = aiohttp.ClientTimeout(total=25)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, params={"uid": uid, "server_name": region}, headers={"X-API-Key": API_KEY}) as resp:
                data = await resp.json(content_type=None)
                if resp.status != 200 or not data.get("ok"):
                    await update.message.reply_text(f"API error ({resp.status}): {data.get('error', 'Request failed')}")
                    return
        p = data["player"]
        await update.message.reply_text(
            f"👤 Player Info\\nUID: {p.get('uid')}\\nName: {p.get('nickname') or 'Unknown'}\\n"
            f"Region: {p.get('region')}\\nLikes: {p.get('likes')}"
        )
    except asyncio.TimeoutError:
        await update.message.reply_text("API timed out. Try again later.")
    except Exception:
        await update.message.reply_text("Could not contact API. Check API service logs.")

def main():
    if not BOT_TOKEN:
        raise SystemExit("Set BOT_TOKEN environment variable first.")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("player", player))
    app.run_polling()

if __name__ == "__main__":
    main()
