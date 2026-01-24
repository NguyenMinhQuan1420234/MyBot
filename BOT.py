import os
import sys
import logging
from logging.handlers import RotatingFileHandler

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler
from message import handle_message, handle_gold, send_gold_to, handle_money, handle_help

async def on_startup(app):
    logging.info("Bot is up and running!")
    # You can add more startup actions here if needed

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        RotatingFileHandler("bot.log", maxBytes=100000, backupCount=1, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Load environment variables: prefer existing env (GitHub Actions), otherwise try .env
if 'TELE_BOT_TOKEN' not in os.environ:
    if load_dotenv:
        load_dotenv("BOT_TOKEN.env")
    else:
        # Try to read BOT_TOKEN.env manually if present
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
                            k = k.strip()
                            v = v.strip()
                            os.environ.setdefault(k, v)
            except Exception:
                pass

# Do not resolve TELE_BOT_TOKEN here; allow CLI override later
_ENV_TOKEN = os.getenv("TELE_BOT_TOKEN")


import argparse
from zoneinfo import ZoneInfo
from message import set_agent

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

    # Automatically read API key from environment
    env_key_map = {
        'gemini': 'GEMINI_API_KEY',
        'openai': 'OPENAI_API_KEY',
        'xai': 'XAI_API_KEY',
        'azure': 'AZURE_API_KEY'
    }
    # Determine API key precedence: CLI --api-key, then provider-specific CLI (e.g. --gemini-key), then environment
    api_key = None
    if args.api_key:
        api_key = args.api_key
    elif args.provider == 'gemini' and getattr(args, 'gemini_key', None):
        api_key = args.gemini_key
    else:
        api_key = os.getenv(env_key_map.get(args.provider))

    if not api_key:
        raise ValueError(f"API key for provider '{args.provider}' not found. Provide via env or --api-key/--{args.provider}-key CLI option.")

    agent_kwargs = {}
    if args.model:
        agent_kwargs['model'] = args.model
    if args.api_base:
        agent_kwargs['api_base'] = args.api_base
    if args.deployment:
        agent_kwargs['deployment'] = args.deployment
    if args.api_version:
        agent_kwargs['api_version'] = args.api_version
    set_agent(args.provider, api_key, **agent_kwargs)

    # Determine Telegram token: CLI overrides env
    token = args.tele_token if getattr(args, 'tele_token', None) else _ENV_TOKEN
    if not token:
        raise ValueError("Telegram bot token not found. Set TELE_BOT_TOKEN env var or pass --tele-token.")

    app = ApplicationBuilder().token(token).post_init(on_startup).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler('gold', handle_gold))
    app.add_handler(CommandHandler('money', handle_money))
    app.add_handler(CommandHandler('help', handle_help))
    # Schedule daily gold price messages at 09:00, 12:00, 15:00 and 18:00 Hanoi time (GMT+7)
    from datetime import time as dt_time, datetime, timedelta

    async def _scheduled_gold_job(context):
        """Send gold price only when current time in GMT+7 matches one of schedule_times.

        This avoids relying on the host timezone. If ZoneInfo is not available, fall back to UTC+7 arithmetic.
        """
        # compute current time in GMT+7
        try:
            now = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh"))
        except Exception:
            now = datetime.utcnow() + timedelta(hours=7)

        current_hm = (now.hour, now.minute)
        # schedule_times is defined below; use it if present, otherwise use defaults
        try:
            scheduled = schedule_times
        except NameError:
            scheduled = [(9, 0), (12, 0), (15, 0), (18, 0)]

        if current_hm not in scheduled:
            logging.info("Skipping scheduled gold job; GMT+7 time %02d:%02d not in schedule", now.hour, now.minute)
            return

        # time matches — send to configured chat ids (or default)
        chat_ids = [-1002713059877]
 
        for cid in chat_ids:
            try:
                await send_gold_to(cid, context)
            except Exception as e:
                logging.exception(f"Failed sending scheduled gold to {cid}: {e}")
    
    # Use Hanoi timezone (Asia/Ho_Chi_Minh) so times align with GMT+7 regardless of host TZ
    try:
        hanoi_tz = ZoneInfo("Asia/Ho_Chi_Minh")
    except Exception:
        hanoi_tz = None

    jobq = getattr(app, 'job_queue', None)
    if not jobq:
        logging.warning(
            "No JobQueue set up; skipping scheduled gold jobs. "
            "To enable scheduling install: pip install \"python-telegram-bot[job-queue]\""
        )
    else:
        schedule_times = [(9, 0), (14, 0)]
        for h, m in schedule_times:
            if hanoi_tz:
                t = dt_time(hour=h, minute=m, tzinfo=hanoi_tz)
            else:
                t = dt_time(hour=h, minute=m)
            jobq.run_daily(_scheduled_gold_job, t)
    app.run_polling()

if __name__ == '__main__':
    main()