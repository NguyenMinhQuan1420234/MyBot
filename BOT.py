import os
import sys
import argparse
import logging
from logging.handlers import RotatingFileHandler
from datetime import time as dt_time, datetime, timedelta
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler

import message as _message
from message import handle_message, handle_gold, send_gold_to, handle_money, handle_help, set_agent

try:
    from config import MONGO_URI
except Exception:
    MONGO_URI = None

try:
    from watcher import GoldWatcher
except Exception:
    GoldWatcher = None

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=100000, backupCount=1, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)

# ---------------------------------------------------------------------------
# Environment variables
# ---------------------------------------------------------------------------
if 'TELE_BOT_TOKEN' not in os.environ:
    if load_dotenv:
        load_dotenv("BOT_TOKEN.env")
    else:
        env_path = "BOT_TOKEN.env"
        if os.path.exists(env_path):
            try:
                with open(env_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            k, v = line.split('=', 1)
                            os.environ.setdefault(k.strip(), v.strip())
            except Exception:
                pass

_ENV_TOKEN = os.getenv("TELE_BOT_TOKEN")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CHAT_LIST = [-1002713059877, -1003835873764]
SCHEDULE_TIMES = [(9, 0)]

ENV_KEY_MAP = {
    'gemini': 'GEMINI_API_KEY',
    'openai': 'OPENAI_API_KEY',
    'xai': 'XAI_API_KEY',
    'azure': 'AZURE_API_KEY',
}

# ---------------------------------------------------------------------------
# Callbacks
# ---------------------------------------------------------------------------
async def on_startup(app):
    logging.info("Bot is up and running!")


async def _scheduled_gold_job(context):
    """Send gold price when GMT+7 time matches one of SCHEDULE_TIMES."""
    try:
        now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
    except Exception:
        now = datetime.utcnow() + timedelta(hours=7)

    if (now.hour, now.minute) not in SCHEDULE_TIMES:
        logging.info("Skipping scheduled gold job; GMT+7 time %02d:%02d not in schedule", now.hour, now.minute)
        return

    for cid in CHAT_LIST:
        try:
            await send_gold_to(cid, context)
        except Exception:
            logging.exception("Failed sending scheduled gold to %s", cid)

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Telegram AI Bot")
    parser.add_argument('--provider', type=str, choices=['gemini', 'openai', 'xai', 'azure'], default='gemini', help='AI provider to use')
    parser.add_argument('--model', type=str, help='Model name (optional)')
    parser.add_argument('--api_base', type=str, help='Azure OpenAI API base (optional)')
    parser.add_argument('--deployment', type=str, help='Azure OpenAI deployment name (optional)')
    parser.add_argument('--api_version', type=str, help='Azure OpenAI API version (optional)')
    parser.add_argument('--api-key', type=str, help='API key to use (overrides env)')
    parser.add_argument('--gemini-key', type=str, help='Gemini API key specifically (overrides env when provider is gemini)')
    parser.add_argument('--tele-token', type=str, help='Telegram bot token (overrides env TELE_BOT_TOKEN)')
    args = parser.parse_args()

    # Resolve API key: CLI > provider-specific CLI > env
    api_key = args.api_key
    if not api_key and args.provider == 'gemini' and getattr(args, 'gemini_key', None):
        api_key = args.gemini_key
    if not api_key:
        api_key = os.getenv(ENV_KEY_MAP.get(args.provider))
    if not api_key:
        raise ValueError(f"API key for provider '{args.provider}' not found. Provide via env or --api-key/--{args.provider}-key CLI option.")

    agent_kwargs = {}
    for attr in ('model', 'api_base', 'deployment', 'api_version'):
        val = getattr(args, attr, None)
        if val:
            agent_kwargs[attr] = val
    set_agent(args.provider, api_key, **agent_kwargs)

    # Resolve Telegram token: CLI > env
    token = getattr(args, 'tele_token', None) or _ENV_TOKEN
    if not token:
        raise ValueError("Telegram bot token not found. Set TELE_BOT_TOKEN env var or pass --tele-token.")

    app = ApplicationBuilder().token(token).post_init(on_startup).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler('gold', handle_gold))
    app.add_handler(CommandHandler('money', handle_money))
    app.add_handler(CommandHandler('help', handle_help))

    # ---- Job scheduling ----
    jobq = getattr(app, 'job_queue', None)
    if not jobq:
        logging.warning(
            "No JobQueue set up; skipping scheduled gold jobs. "
            "To enable scheduling install: pip install \"python-telegram-bot[job-queue]\""
        )
    elif not getattr(app, '_scheduled_gold_jobs_created', False):
        app._scheduled_gold_jobs_created = True

        try:
            hanoi_tz = ZoneInfo("Asia/Ho_Chi_Minh")
        except Exception:
            hanoi_tz = None

        # Try to create GoldWatcher
        watcher = None
        if GoldWatcher is not None:
            try:
                mongo_uri = os.getenv('MONGO_URI', MONGO_URI or '')
                watcher = GoldWatcher(_message.agent, mongo_uri, chat_id=CHAT_LIST)
                logging.info('Registered GoldWatcher')
            except Exception:
                logging.exception('Failed to register GoldWatcher')

        for h, m in SCHEDULE_TIMES:
            t = dt_time(hour=h, minute=m, tzinfo=hanoi_tz) if hanoi_tz else dt_time(hour=h, minute=m)
            callback = watcher.job_info if watcher else _scheduled_gold_job
            jobq.run_daily(callback, t)
            logging.info("Scheduled gold info job at %02d:%02d", h, m)

        if watcher is not None:
            jobq.run_repeating(watcher.job, interval=300, first=30)
            logging.info('Registered GoldWatcher changes job (every 5 minutes)')

    app.run_polling()


if __name__ == '__main__':
    main()