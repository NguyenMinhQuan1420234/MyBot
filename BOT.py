from telegram.ext import ApplicationBuilder, MessageHandler, ContextTypes, filters
from dotenv import load_dotenv
import os
import google.generativeai as genai
import logging
import sys

async def on_startup(app):
    logging.info("Bot is up and running!")
    # You can add more startup actions here if needed

logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

# Load environment variables from .env file
load_dotenv("BOT_TOKEN.env")
TOKEN = os.getenv("TELE_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

def ask_gemini_ai(prompt):
    model = genai.GenerativeModel('models/gemini-2.0-flash-exp')
    response = model.generate_content(prompt)
    logging.info(f"GeminiAI Request: {prompt}")
    logging.info(f"GeminiAI Response: {response.text if hasattr(response, 'text') else str(response)}")
    return response.text if hasattr(response, 'text') else str(response)

async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    logging.info(f"User({chat_id}) sent: {text}")
    # Send user message to Gemini AI and get response
    ai_response = ask_gemini_ai(text)
    logging.info(f"Bot reply to User({chat_id}): {ai_response}")
    await context.bot.send_message(chat_id=chat_id, text=ai_response)

def main():
    app = ApplicationBuilder().token(TOKEN).post_init(on_startup).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.run_polling()

if __name__ == '__main__':
    main()