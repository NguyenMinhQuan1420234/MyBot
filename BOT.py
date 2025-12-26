
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None
from telegram.ext import ApplicationBuilder, MessageHandler, filters, CommandHandler
from message import handle_message, handle_gold

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

TOKEN = os.getenv("TELE_BOT_TOKEN")


import argparse
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

    app = ApplicationBuilder().token(TOKEN).post_init(on_startup).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler('gold', handle_gold))
    app.run_polling()

if __name__ == '__main__':
    main()