import asyncio
import logging
from typing import Optional
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

try:
    from pymongo import MongoClient, ASCENDING, DESCENDING
except Exception as e:
    MongoClient = None


class GoldWatcher:
    """Poll gold prices via GoldPriceService and send alerts to Telegram chat.

    Usage:
      watcher = GoldWatcher(agent, mongo_uri, chat_id=chat_id)
      job_queue.run_daily(watcher.job_info, time)  # Periodic info
      job_queue.run_repeating(watcher.job, interval=600)  # Change detection
    """

    def __init__(self, agent, mongo_uri: str, db_name: str = MONGO_DB_NAME, collection: str = MONGO_COLLECTION, chat_id: Optional[int] = None):
        if MongoClient is None:
            raise RuntimeError('pymongo is required for GoldWatcher (install pymongo)')
        self.agent = agent
        self.mongo_uri = mongo_uri
        self.client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
        self.db = self.client[db_name]
        self.coll = self.db[collection]
        # ensure indexes
        try:
            self.coll.create_index([('source', ASCENDING), ('code', ASCENDING), ('timestamp', DESCENDING)])
        except Exception:
            logging.exception('Could not create index on %s', collection)
        self.chat_id = chat_id
        
        # Create GoldPriceService for formatting and data retrieval
        self.gold_service = None
        try:
            from api_client import APIClient
            from crawl_gold_price import GoldPriceService
            api_client = APIClient()
            self.gold_service = GoldPriceService(api_client, mongo_uri, db_name, collection)
        except Exception:
            logging.exception('Failed to create GoldPriceService in watcher')

    async def job_info(self, context):
        """Periodic sender: always send `info` style message."""
        if self.gold_service is None:
            logging.warning('GoldWatcher info job: GoldPriceService not available')
            return
            
        try:
            result = self.gold_service.get_info()
            message = result.get('message')
        except Exception:
            logging.exception('Failed to get info from GoldPriceService')
            return

        if not message:
            logging.info('GoldWatcher info job: no message generated')
            return

        chat_id = self.chat_id
        if chat_id is None:
            try:
                chat_id = getattr(context.job, 'context', None) or getattr(context, 'chat_id', None)
            except Exception:
                chat_id = None

        if chat_id is None:
            logging.info('GoldWatcher info job: no chat_id configured; skipping alert')
            return

        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
        except Exception:
            logging.exception('Failed to send gold info message')

    async def job(self, context):
        """Change sender: send only when there are changes (`changes` style)."""
        if self.gold_service is None:
            logging.warning('GoldWatcher changes job: GoldPriceService not available')
            return
            
        try:
            result = self.gold_service.get_changes()
            message = result.get('message')
            has_changes = result.get('has_any_change', False)
        except Exception:
            logging.exception('Failed to get changes from GoldPriceService')
            return

        if not has_changes or not message:
            logging.debug('GoldWatcher: no changes detected')
            return

        chat_id = self.chat_id
        if chat_id is None:
            try:
                chat_id = getattr(context.job, 'context', None) or getattr(context, 'chat_id', None)
            except Exception:
                chat_id = None

        if chat_id is None:
            logging.info('GoldWatcher changes job: no chat_id configured; skipping alert')
            return

        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
        except Exception:
            logging.exception('Failed to send gold changes message')


DEFAULT_MONGO_URI = MONGO_URI

__all__ = ['GoldWatcher', 'DEFAULT_MONGO_URI']



DEFAULT_MONGO_URI = MONGO_URI

__all__ = ['GoldWatcher', 'DEFAULT_MONGO_URI']
