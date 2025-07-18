import logging
from telegram.ext import ContextTypes
from agent import Agent
import os

agent = None

def set_agent(provider, api_key, **kwargs):
    global agent
    agent = Agent(provider, api_key, **kwargs)

async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    text = update.message.text
    logging.info(f"User({chat_id}) sent: {text}")
    ai_response = agent.ask(text)
    logging.info(f"Bot reply to User({chat_id}): {ai_response}")
    for i in range(0, len(ai_response), 4096):
        await context.bot.send_message(chat_id=chat_id, text=ai_response[i:i+4096])
