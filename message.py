import logging
from telegram.ext import ContextTypes
from agent import Agent
import os

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
agent = Agent(GEMINI_API_KEY)

async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    logging.info(f"User({chat_id}) sent: {text}")
    # Let Gemini AI decide if browser interaction is needed
    ai_response = agent.ask_gemini(text)
    logging.info(f"Bot reply to User({chat_id}): {ai_response}")
    for i in range(0, len(ai_response), 4096):
        await context.bot.send_message(chat_id=chat_id, text=ai_response[i:i+4096])
