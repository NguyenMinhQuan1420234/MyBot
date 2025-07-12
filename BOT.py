import telegram
from telegram.ext import Updater, MessageHandler, Filters
from dotenv import load_dotenv
import os
# Load environment variables from .env file
load_dotenv()
TOKEN = os.getenv("TELE_BOT_TOKEN")

def handle_message(update, context):
    # Echo the received message
    chat_id = update.effective_chat.id
    text = update.message.text
    context.bot.send_message(chat_id=chat_id, text=f"You said: {text}")

def main():
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher

    # Add a handler for text messages
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))

    # Start the bot
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()