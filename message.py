import logging
import json
from telegram.ext import ContextTypes
from agent import Agent
import os
from telegram import MessageEntity

agent = None

THREAD_CHAT_ID = -1003835873764
THREAD_ID = 2


def _send_kwargs(chat_id):
    if chat_id == THREAD_CHAT_ID:
        return {'message_thread_id': THREAD_ID}
    return {}

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
        await context.bot.send_message(chat_id=chat_id, text=ai_response[i:i+4096], **_send_kwargs(chat_id))


async def handle_gold(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await send_gold_to(chat_id, context)


async def handle_money(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /money command. Usage: /money [CODE]
    
    With no argument returns both USD and JPY.
    """
    chat_id = update.effective_chat.id
    if not agent:
        await context.bot.send_message(chat_id=chat_id, text="Agent not configured.", **_send_kwargs(chat_id))
        return
    args = getattr(context, 'args', []) or []
    note = ''
    if not args:
        code = None
        note = 'Hãy nhập đơn vị tiền tệ bạn muốn sau câu lệnh (VD: /money EUR)\n\n'
    else:
        code = args[0]

    try:
        result = agent.get_money_rate(code)
    except Exception as e:
        result = f"Lỗi lấy thông tin tiền tệ: {e}"

    def _format_rate(r) -> str:
        if not isinstance(r, dict):
            return str(r)
        name = r.get('name', r.get('code', ''))
        code_str = r.get('code', '')
        lines = [f"💱 {name} ({code_str})"]
        if r.get('buy_cash'):
            lines.append(f"  Mua tiền mặt : {r['buy_cash']}")
        if r.get('sell_cash'):
            lines.append(f"  Bán tiền mặt : {r['sell_cash']}")
        return '\n'.join(lines)

    if isinstance(result, list):
        text = note + '\n\n'.join(_format_rate(r) for r in result)
    else:
        text = note + _format_rate(result)

    for i in range(0, len(text), 4096):
        await context.bot.send_message(chat_id=chat_id, text=text[i:i+4096], **_send_kwargs(chat_id))


async def handle_help(update, context: ContextTypes.DEFAULT_TYPE):
    """Respond to /help with supported commands summary."""
    chat_id = update.effective_chat.id
    text = "Bot dỏm Tele hiện đang hỗ trợ 2 lệnh /gold và /money"
    await context.bot.send_message(chat_id=chat_id, text=text, **_send_kwargs(chat_id))


async def send_money_to(chat_id, context: ContextTypes.DEFAULT_TYPE):
    """Send default USD+JPY exchange rates to a given chat id (scheduled job)."""
    logging.info(f"Sending money rate to chat {chat_id}")
    if not agent:
        return
    try:
        result = agent.get_money_rate()
    except Exception as e:
        logging.exception('Failed fetching money rate in send_money_to')
        await context.bot.send_message(chat_id=chat_id, text=f"Lỗi lấy tỷ giá: {e}", **_send_kwargs(chat_id))
        return

    def _format_rate(r) -> str:
        if not isinstance(r, dict):
            return str(r)
        name = r.get('name', r.get('code', ''))
        code_str = r.get('code', '')
        lines = [f"💱 {name} ({code_str})"]
        if r.get('buy_cash'):
            lines.append(f"  Mua tiền mặt : {r['buy_cash']}")
        if r.get('sell_cash'):
            lines.append(f"  Bán tiền mặt : {r['sell_cash']}")
        return '\n'.join(lines)

    if isinstance(result, list):
        text = '\n\n'.join(_format_rate(r) for r in result)
    else:
        text = _format_rate(result)

    for i in range(0, len(text), 4096):
        await context.bot.send_message(chat_id=chat_id, text=text[i:i+4096], **_send_kwargs(chat_id))


async def send_gold_to(chat_id, context: ContextTypes.DEFAULT_TYPE):
    """Send gold price to a given chat id (used by command and scheduled jobs).

    Uses `GoldPriceService.get_info()` so formatting matches CLI and watcher
    output. The service also handles database comparisons and message
    composition, keeping behavior consistent across components.
    """
    logging.info(f"Sending gold price to chat {chat_id}")
    if not agent:
        await context.bot.send_message(chat_id=chat_id, text="Agent not configured.", **_send_kwargs(chat_id))
        return

    try:
        from api_client import APIClient
        from crawl_gold_price import GoldPriceService
        api_client = APIClient()
        service = GoldPriceService(api_client)
        result = service.get_info()
        text = result.get('message') or json.dumps(result.get('data', {}), ensure_ascii=False, indent=2)
    except Exception as e:
        logging.exception('Failed fetching gold info in send_gold_to')
        text = f"Lỗi lấy thông tin giá vàng: {e}"

    for i in range(0, len(text), 4096):
        await context.bot.send_message(chat_id=chat_id, text=text[i:i+4096], **_send_kwargs(chat_id))
