import logging
import json
from telegram.ext import ContextTypes
from agent import Agent
import os
from telegram import MessageEntity

agent = None

def set_agent(provider, api_key, **kwargs):
    global agent
    agent = Agent(provider, api_key, **kwargs)

async def handle_message(update, context: ContextTypes.DEFAULT_TYPE):
    # Only respond in private chats or when the bot is explicitly mentioned in group chats
    msg = update.message
    if not msg:
        return
    chat = update.effective_chat
    chat_id = chat.id
    text = msg.text or ""

    def is_mentioned(message, ctx):
        # Private chat: always respond
        if chat.type == 'private':
            return True
        # Check entities for mention or text_mention
        entities = message.entities or []
        for ent in entities:
            if ent.type == MessageEntity.MENTION:
                mentioned = text[ent.offset: ent.offset + ent.length]
                if mentioned.lstrip('@').lower() == (ctx.bot.username or '').lower():
                    return True
            if ent.type == MessageEntity.TEXT_MENTION:
                if ent.user and ent.user.id == ctx.bot.id:
                    return True
        # NOTE: do not treat replies as mentions — only explicit mentions are allowed
        return False

    if not is_mentioned(msg, context):
        return

    logging.info(f"User({chat_id}) sent: {text}")
    ai_response = agent.ask(text)
    logging.info(f"Bot reply to User({chat_id}): {ai_response}")
    for i in range(0, len(ai_response), 4096):
        await context.bot.send_message(chat_id=chat_id, text=ai_response[i:i+4096])


async def handle_gold(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    logging.info(f"User({chat_id}) requested gold price")
    if not agent:
        await context.bot.send_message(chat_id=chat_id, text="Agent not configured.")
        return
    result = agent.get_gold_price()
    if isinstance(result, (dict, list)):
        text = json.dumps(result, ensure_ascii=False, indent=2)
    else:
        text = str(result)
    for i in range(0, len(text), 4096):
        await context.bot.send_message(chat_id=chat_id, text=text[i:i+4096])
