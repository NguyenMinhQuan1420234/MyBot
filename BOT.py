
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
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

# Load environment variables from .env file
load_dotenv("BOT_TOKEN.env")
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
    args = parser.parse_args()

    # Automatically read API key from environment
    env_key_map = {
        'gemini': 'GEMINI_API_KEY',
        'openai': 'OPENAI_API_KEY',
        'xai': 'XAI_API_KEY',
        'azure': 'AZURE_API_KEY'
    }
    api_key = os.getenv(env_key_map.get(args.provider))
    if not api_key:
        raise ValueError(f"API key for provider '{args.provider}' not found in BOT_TOKEN.env.")

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