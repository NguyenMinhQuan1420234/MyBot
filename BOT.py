
import os
import sys
import logging
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from telegram.ext import ApplicationBuilder, MessageHandler, filters
from message import handle_message

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

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(on_startup).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == '__main__':
    main()