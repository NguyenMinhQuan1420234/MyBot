import asyncio
import datetime
import logging
import re
from typing import Dict, Any, List, Optional

try:
    from pymongo import MongoClient, ASCENDING, DESCENDING
except Exception as e:
    MongoClient = None


class GoldWatcher:
    """Poll gold prices via an Agent, store numeric values in MongoDB,
    and provide an async job wrapper to alert a chat when prices change.

    Usage:
      watcher = GoldWatcher(agent, mongo_uri)
      job_queue.run_repeating(watcher.job, interval=900, first=10)
    """

    def __init__(self, agent, mongo_uri: str, db_name: str = 'bot', collection: str = 'gold-price-collection', chat_id: Optional[int] = None):
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
            logging.exception('Could not create index on gold-price-collection')
        self.chat_id = chat_id

    @staticmethod
    def _to_int(val: Any) -> Optional[int]:
        if val is None:
            return None
        s = str(val).strip()
        if not s or s.lower() in ('n/a', 'na'):
            return None
        # strip non-digit characters
        digits = re.sub(r'[^0-9]', '', s)
        if not digits:
            return None
        try:
            return int(digits)
        except Exception:
            return None

    @staticmethod
    def _parse_bullet_text(text: str) -> Dict[str, Dict[str, Any]]:
        """Parse bullet-style text into mapping code -> {buy, sell, text}.

        Expects input like:
        - SJC (ngày ...):
          - Giá mua: 59,000,000
          - Giá bán: 59,200,000
        """
        res: Dict[str, Dict[str, Any]] = {}
        if not text:
            return res
        lines = text.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            if line.startswith('-'):
                # label line
                # remove leading dash and possible numbering
                label = re.sub(r'^[-\s]+', '', line)
                # take the first token as code if present
                mcode = re.match(r'([A-Za-z0-9\.]+)', label)
                code = mcode.group(1).upper() if mcode else label
                buy = None
                sell = None
                j = i + 1
                # gather next few lines for buy/sell
                while j < len(lines) and not lines[j].strip().startswith('-'):
                    l = lines[j].strip()
                    mbuy = re.search(r'Gi[áa]\s*mua\s*[:\-]?\s*([0-9\.,]+)', l)
                    msell = re.search(r'Gi[áa]\s*b[áa]n\s*[:\-]?\s*([0-9\.,]+)', l)
                    if mbuy:
                        buy = mbuy.group(1)
                    if msell:
                        sell = msell.group(1)
                    j += 1
                # fallback: try to extract numbers from subsequent indented lines
                if buy is None or sell is None:
                    # look a few lines ahead
                    k = i + 1
                    while k < min(len(lines), i + 6):
                        l = lines[k]
                        nums = re.findall(r'([0-9][0-9\.,]+)', l)
                        if nums and buy is None:
                            buy = nums[0]
                        if len(nums) > 1 and sell is None:
                            sell = nums[1]
                        k += 1

                res[code] = {
                    'buy_raw': buy,
                    'sell_raw': sell,
                    'buy': GoldWatcher._to_int(buy),
                    'sell': GoldWatcher._to_int(sell),
                    'text': label,
                }
                i = j
            else:
                i += 1
        return res

    def _collect_sources(self) -> List[Dict[str, Any]]:
        """Call agent.get_gold_price() and extract normalized source dicts."""
        sources = []
        try:
            snapshot = self.agent.get_gold_price()
        except Exception as e:
            logging.exception('Error calling agent.get_gold_price(): %s', e)
            return sources

        # Iterate through sources in snapshot and convert to internal format
        for src_data in snapshot.get('sources', []):
            src_name = src_data.get('name', 'unknown')
            # Map source names to internal source codes
            source_map = {'Mi Hong': 'mihong', 'Doji': 'doji', 'Ngoc Tham': 'ngoctham'}
            source_code = source_map.get(src_name, src_name.lower())

            # Use normalized items from snapshot
            items_list = src_data.get('items', [])

            # Convert normalized items to parsed dict format
            parsed = {}
            if src_data.get('status') == 'ok':
                for item in items_list:
                    code = item.get('code')
                    if not code:
                        continue
                    buy_price = item.get('buyPrice')
                    sell_price = item.get('sellPrice')
                    has_change = item.get('has_price_change', True)  # Default to True if not set
                    parsed[code] = {
                        'buy_raw': buy_price,
                        'sell_raw': sell_price,
                        'buy': buy_price,
                        'sell': sell_price,
                        'text': code,
                        'has_price_change': has_change,
                    }

            sources.append({
                'source': source_code,
                'text': snapshot.get('message', ''),
                'parsed': parsed,
                'status': src_data.get('status'),
            })
        return sources

    def check_and_store(self) -> List[Dict[str, Any]]:
        """Blocking: fetch prices, compare with last stored, insert new docs for changes.

        Returns list of changes inserted.
        """
        changes = []
        now = datetime.datetime.utcnow()
        sources = self._collect_sources()
        # If collection is empty, seed it with the current fetched prices
        try:
            is_empty = self.coll.count_documents({}) == 0
        except Exception:
            logging.exception('DB count_documents failed')
            is_empty = False

        if is_empty:
            logging.info('gold-price-collection empty — seeding current fetched prices')
            for s in sources:
                src = s.get('source')
                text = s.get('text')
                parsed: Dict[str, Dict[str, Any]] = s.get('parsed') or {}
                if parsed:
                    for code, vals in parsed.items():
                        buy = vals.get('buy')
                        sell = vals.get('sell')
                        doc = {
                            'timestamp': now,
                            'source': src,
                            'code': code,
                            'buy': buy,
                            'sell': sell,
                            'raw_text': text,
                            'parsed': vals,
                        }
                        try:
                            self.coll.insert_one(doc)
                        except Exception:
                            logging.exception('DB insert error during seeding')
                else:
                    # no parsed entries — store raw text as a document for the source
                    doc = {
                        'timestamp': now,
                        'source': src,
                        'code': None,
                        'buy': None,
                        'sell': None,
                        'raw_text': text,
                        'parsed': {},
                    }
                    try:
                        self.coll.insert_one(doc)
                    except Exception:
                        logging.exception('DB insert error during seeding')
            # After seeding, return without alerting (first-run seed should not notify)
            return []
        for s in sources:
            src = s.get('source')
            text = s.get('text')
            parsed: Dict[str, Dict[str, Any]] = s.get('parsed') or {}
            for code, vals in parsed.items():
                buy = vals.get('buy')
                sell = vals.get('sell')
                has_change = vals.get('has_price_change', True)  # Skip if explicitly False
                
                # Skip storing if no price change detected
                if not has_change:
                    logging.debug('Skipping insert for %s/%s: no price change', src, code)
                    continue
                
                # Price changed or is new, so insert
                doc = {
                    'timestamp': now,
                    'source': src,
                    'code': code,
                    'buy': buy,
                    'sell': sell,
                    'raw_text': text,
                    'parsed': vals,
                }
                try:
                    self.coll.insert_one(doc)
                    if buy is not None or sell is not None:
                        changes.append(doc)
                        logging.info('Stored price change for %s/%s: buy=%s sell=%s', 
                                    src, code, buy, sell)
                except Exception:
                    logging.exception('DB insert error')
        return changes

    async def job(self, context):
        """Async job wrapper suitable for python-telegram-bot job_queue.

        Example registration (in BOT.py):
          jobq.run_repeating(watcher.job, interval=900, first=10)
        """
        try:
            changes = await asyncio.to_thread(self.check_and_store)
        except Exception:
            logging.exception('Watcher check_and_store failed')
            return

        if not changes:
            logging.debug('GoldWatcher: no changes detected')
            return

        # Build a short message summarizing changes
        parts = []
        for ch in changes:
            code = ch.get('code')
            src = ch.get('source')
            buy = ch.get('buy')
            sell = ch.get('sell')
            parts.append(f"[{src}] {code}: mua={buy or 'N/A'} bán={sell or 'N/A'}")
        message = "Giá vàng cập nhật:\n" + "\n".join(parts)

        # try to get chat id from watcher config or job context
        chat_id = self.chat_id
        if chat_id is None:
            # context may carry a chat id via job context
            try:
                chat_id = getattr(context.job, 'context', None) or getattr(context, 'chat_id', None)
            except Exception:
                chat_id = None

        if chat_id is None:
            logging.info('GoldWatcher detected changes but no chat_id configured; skipping alert')
            return

        try:
            await context.bot.send_message(chat_id=chat_id, text=message)
        except Exception:
            logging.exception('Failed to send gold update message')


DEFAULT_MONGO_URI = 'mongodb+srv://banchi0072000_db_user:e1eWC71hSnWVzvkw@milo-database.oopvg0c.mongodb.net/?appName=milo-database'

__all__ = ['GoldWatcher', 'DEFAULT_MONGO_URI']
