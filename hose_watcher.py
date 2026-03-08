"""HOSE stock market watcher for scheduled Telegram alerts.

Mirrors the design of ``watcher.py`` (GoldWatcher) so the two can
coexist side-by-side in ``BOT.py``.

Typical wiring inside ``BOT.py``::

    hose_watcher = HOSEWatcher(mongo_uri, chat_id=CHAT_LIST)
    # Daily market summary at 09:00 and 15:15 (market open / close)
    jobq.run_daily(hose_watcher.job_info, dt_time(9, 0, tzinfo=tz))
    jobq.run_daily(hose_watcher.job_info, dt_time(15, 15, tzinfo=tz))
    # Intraday change alerts every 30 minutes
    jobq.run_repeating(hose_watcher.job, interval=1800, first=60)
"""

import logging
from typing import List, Optional

from config import MONGO_URI, MONGO_DB_NAME

try:
    from api_client import APIClient
    from crawl_hose_stock import HOSEStockService, HOSE_STOCK_COLLECTION
except Exception:
    APIClient = None
    HOSEStockService = None
    HOSE_STOCK_COLLECTION = "hose-stock-collection"

# Mirror the thread-specific chat constants from watcher.py
_THREAD_CHAT_ID = -1003835873764
_THREAD_ID = 2


class HOSEWatcher:
    """Poll HOSE market data via ``HOSEStockService`` and push alerts to Telegram.

    Parameters
    ----------
    mongo_uri:
        MongoDB connection URI for storing price history (change detection).
    db_name:
        MongoDB database name.
    collection:
        MongoDB collection name for HOSE price snapshots.
    chat_id:
        A single chat ID (int) **or** a list/tuple of chat IDs.
    change_threshold_pct:
        Minimum absolute percentage move to trigger a change alert (default 0.5 %).
    """

    def __init__(
        self,
        mongo_uri: str = "",
        db_name: str = MONGO_DB_NAME,
        collection: str = HOSE_STOCK_COLLECTION,
        chat_id=None,
        change_threshold_pct: float = 0.5,
    ):
        if isinstance(chat_id, (list, tuple, set)):
            self.chat_ids: List[int] = list(chat_id)
        elif chat_id is not None:
            self.chat_ids = [chat_id]
        else:
            self.chat_ids = []

        self.chat_id: Optional[int] = self.chat_ids[0] if self.chat_ids else None
        self.change_threshold_pct = change_threshold_pct

        self.stock_service: Optional[HOSEStockService] = None
        if APIClient and HOSEStockService:
            try:
                api_client = APIClient()
                self.stock_service = HOSEStockService(
                    api_client,
                    mongo_uri or MONGO_URI,
                    db_name,
                    collection,
                )
                logging.info("HOSEWatcher: HOSEStockService initialised")
            except Exception:
                logging.exception("HOSEWatcher: failed to create HOSEStockService")

    # ------------------------------------------------------------------
    # Scheduled job callbacks
    # ------------------------------------------------------------------

    async def job_info(self, context):
        """Telegram job: send a full HOSE market summary (VN-Index + metadata)."""
        if self.stock_service is None:
            logging.warning("HOSEWatcher job_info: HOSEStockService not available")
            return
        try:
            result = self.stock_service.get_info()
            message = result.get("message")
        except Exception:
            logging.exception("HOSEWatcher: failed to get market info")
            return

        if not message:
            logging.info("HOSEWatcher job_info: no message generated")
            return

        await self._send_to_all_chats(context, message)

    async def job(self, context):
        """Telegram job: send an alert only when VN-Index moves significantly."""
        if self.stock_service is None:
            logging.warning("HOSEWatcher job: HOSEStockService not available")
            return
        try:
            result = self.stock_service.get_changes(threshold_pct=self.change_threshold_pct)
            has_change = result.get("has_any_change", False)
            message = result.get("message")
        except Exception:
            logging.exception("HOSEWatcher: failed to get market changes")
            return

        if not has_change or not message:
            logging.debug("HOSEWatcher: no significant VN-Index change detected")
            return

        await self._send_to_all_chats(context, message)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _send_to_all_chats(self, context, message: str) -> None:
        for cid in self.chat_ids:
            try:
                kwargs = {"message_thread_id": _THREAD_ID} if cid == _THREAD_CHAT_ID else {}
                # Telegram message limit is 4096 characters
                for i in range(0, len(message), 4096):
                    await context.bot.send_message(
                        chat_id=cid, text=message[i : i + 4096], **kwargs
                    )
            except Exception:
                logging.exception("HOSEWatcher: failed to send message to chat %s", cid)


__all__ = ["HOSEWatcher"]
