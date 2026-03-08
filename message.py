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
    """Handle /money command. Usage: /money USD"""
    chat_id = update.effective_chat.id
    if not agent:
        await context.bot.send_message(chat_id=chat_id, text="Agent not configured.", **_send_kwargs(chat_id))
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
        await context.bot.send_message(chat_id=chat_id, text=text[i:i+4096], **_send_kwargs(chat_id))


async def handle_help(update, context: ContextTypes.DEFAULT_TYPE):
    """Respond to /help with supported commands summary."""
    chat_id = update.effective_chat.id
    text = (
        "Bot dỏm Tele hiện đang hỗ trợ các lệnh:\n"
        "/gold – Giá vàng hiện tại\n"
        "/money [mã] – Tỷ giá ngoại tệ (ví dụ: /money USD)\n"
        "/stock [mã] – Thị trường chứng khoán HOSE\n"
        "  Ví dụ: /stock hoặc /stock VNM hoặc /stock VNINDEX"
    )
    await context.bot.send_message(chat_id=chat_id, text=text, **_send_kwargs(chat_id))


async def handle_stock(update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /stock command.  Usage: /stock [TICKER]

    Examples::

        /stock              – VN-Index overview
        /stock VNINDEX      – explicit VN-Index
        /stock VN30         – VN30 index
        /stock VNM          – price for Vinamilk stock
    """
    chat_id = update.effective_chat.id
    await send_stock_to(chat_id, context, ticker=(context.args or [None])[0])


async def send_stock_to(chat_id, context: ContextTypes.DEFAULT_TYPE, ticker=None):
    """Send HOSE market info to *chat_id*.  Used by command and scheduled jobs."""
    logging.info("Sending HOSE stock info to chat %s (ticker=%s)", chat_id, ticker)
    if not agent:
        await context.bot.send_message(
            chat_id=chat_id, text="Agent not configured.", **_send_kwargs(chat_id)
        )
        return

    try:
        if agent and agent.stock_service:
            result = agent.stock_service.get_info(ticker)
        else:
            from api_client import APIClient
            from crawl_hose_stock import HOSEStockService
            api_client = APIClient()
            service = HOSEStockService(api_client)
            result = service.get_info(ticker)
        text = result.get("message") or json.dumps(result.get("data", {}), ensure_ascii=False, indent=2)
    except Exception as e:
        logging.exception("Failed fetching HOSE stock info in send_stock_to")
        text = f"Lỗi lấy thông tin chứng khoán: {e}"

    for i in range(0, len(text), 4096):
        await context.bot.send_message(chat_id=chat_id, text=text[i : i + 4096], **_send_kwargs(chat_id))


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
