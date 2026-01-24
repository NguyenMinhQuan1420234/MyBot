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
    await send_gold_to(chat_id, context)


async def handle_money(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /money command. Usage: /money USD"""
    chat_id = update.effective_chat.id
    if not agent:
        await context.bot.send_message(chat_id=chat_id, text="Agent not configured.")
        return
    args = getattr(context, 'args', []) or []
    note = ''
    if not args:
        code = 'usd'
        note = 'Hãy nhập đơn vị tiền tệ bạn muốn sau câu lệnh\n'
    else:
        code = args[0]

    try:
        result = agent.get_money_rate(code)
    except Exception as e:
        result = f"Lỗi lấy thông tin tiền tệ: {e}"

    # If agent returned structured dict with only the required keys, format to text
    if isinstance(result, dict):
        name = result.get('name', '')
        buy = result.get('buy', '')
        sell = result.get('sell', '')
        text = f"{note}{name}:\n mua: {buy}\n bán: {sell}\n"
    else:
        text = f"{note}{result}"
    for i in range(0, len(text), 4096):
        await context.bot.send_message(chat_id=chat_id, text=text[i:i+4096])


async def handle_help(update, context: ContextTypes.DEFAULT_TYPE):
    """Respond to /help with supported commands summary."""
    chat_id = update.effective_chat.id
    text = "Bot dỏm Tele hiện đang hỗ trợ 2 lệnh /gold và /money"
    await context.bot.send_message(chat_id=chat_id, text=text)


async def send_gold_to(chat_id, context: ContextTypes.DEFAULT_TYPE):
    """Send gold price to a given chat id (used by command and scheduled jobs)."""
    logging.info(f"Sending gold price to chat {chat_id}")
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
