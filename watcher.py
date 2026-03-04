import asyncio
import datetime
import logging
import re
from typing import Dict, Any, List, Optional
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

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

    @staticmethod
    def _format_vn_price(val: Optional[int]) -> str:
        if val is None:
            return "Không có"
        try:
            return f"{int(val):,}".replace(',', '.')
        except Exception:
            return str(val)

    @staticmethod
    def _format_change_arrow(change: Optional[int]) -> str:
        if change is None or change == 0:
            return ""
        arrow = "↑" if change > 0 else "↓"
        change_str = f"{change:+,}".replace(',', '.')
        return f" ({change_str} {arrow})"

    @staticmethod
    def _display_provider_name(name: str) -> str:
        if not name:
            return "Không rõ"
        name_map = {
            "Ngoc Tham": "Ngọc Thẩm",
        }
        return name_map.get(name, name)

    @staticmethod
    def _source_key(source: str) -> str:
        return re.sub(r"\s+", "", (source or "")).lower()

    def _compute_change_vs_yesterday(self, source: str, code: str, buy_price: Optional[int], sell_price: Optional[int]):
        """Return (buy_change, sell_change) vs latest record of yesterday for source/code."""
        if self.coll is None:
            return None, None

        try:
            today_start = datetime.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - datetime.timedelta(days=1)

            last_yesterday = self.coll.find_one(
                {
                    "source": self._source_key(source),
                    "code": code,
                    "timestamp": {"$gte": yesterday_start, "$lt": today_start},
                },
                sort=[("timestamp", -1)],
            )

            if not last_yesterday:
                return None, None

            y_buy = last_yesterday.get("buy")
            y_sell = last_yesterday.get("sell")

            buy_change = None if buy_price is None or y_buy is None else (buy_price - y_buy)
            sell_change = None if sell_price is None or y_sell is None else (sell_price - y_sell)
            return buy_change, sell_change
        except Exception:
            logging.exception("Không tính được thay đổi so với hôm qua cho %s/%s", source, code)
            return None, None

    def _get_snapshot(self) -> Dict[str, Any]:
        try:
            snapshot = self.agent.get_gold_price()
            return snapshot if isinstance(snapshot, dict) else {}
        except Exception:
            logging.exception("Failed to get gold snapshot from agent")
            return {}

    def build_info_message(self, snapshot: Dict[str, Any]) -> str:
        now = datetime.datetime.now()
        vn_days = {
            0: 'THỨ HAI',
            1: 'THỨ BA',
            2: 'THỨ TƯ',
            3: 'THỨ NĂM',
            4: 'THỨ SÁU',
            5: 'THỨ BẢY',
            6: 'CHỦ NHẬT'
        }
        day_name = vn_days.get(now.weekday(), 'CHỦ NHẬT')
        date_header = f"{day_name} NGÀY {now.day:02d} THÁNG {now.month:02d} NĂM {now.year}"
        time_header = now.strftime("%I:%M:%S %p")

        lines: List[str] = [
            "THÔNG TIN GIÁ VÀNG",
            date_header,
            time_header,
            "=" * 80,
        ]

        has_data = False
        for src in snapshot.get('sources', []):
            provider_name = self._display_provider_name(src.get('name', 'Unknown'))
            source_name = src.get('name', 'Unknown')
            status = src.get('status')
            has_any_change = src.get('has_any_change', False)

            if status != 'ok':
                continue

            change_marker = " [CÓ THAY ĐỔI]" if has_any_change else ""
            lines.append(f"Giá vàng {provider_name}{change_marker}:")

            items = src.get('items', [])
            items_by_code = {item.get('code'): item for item in items}

            for code in ['SJC', '999']:
                item = items_by_code.get(code)
                if not item:
                    continue

                has_data = True
                buy = item.get('buyPrice')
                sell = item.get('sellPrice')
                buy_change = item.get('buyChange')
                sell_change = item.get('sellChange')
                has_change = item.get('has_price_change', False)
                buy_ref_note = ""
                sell_ref_note = ""

                if not has_any_change and not has_change:
                    y_buy_change, y_sell_change = self._compute_change_vs_yesterday(source_name, code, buy, sell)
                    if y_buy_change not in (None, 0):
                        buy_change = y_buy_change
                        buy_ref_note = " [so với hôm qua]"
                    if y_sell_change not in (None, 0):
                        sell_change = y_sell_change
                        sell_ref_note = " [so với hôm qua]"

                code_marker = " ●" if has_change else ""
                lines.append(f"- {code}{code_marker}:")
                lines.append(f"  MUA VÀO: {self._format_vn_price(buy)} VNĐ{self._format_change_arrow(buy_change)}{buy_ref_note}")
                lines.append(f"  BÁN RA : {self._format_vn_price(sell)} VNĐ{self._format_change_arrow(sell_change)}{sell_ref_note}")
                lines.append("")

        if not has_data:
            lines.append("Không có dữ liệu giá vàng.")

        return "\n".join(lines).strip()

    def build_changes_message(self, snapshot: Dict[str, Any]) -> Optional[str]:
        now = datetime.datetime.now()
        vn_days = {
            0: 'THỨ HAI',
            1: 'THỨ BA',
            2: 'THỨ TƯ',
            3: 'THỨ NĂM',
            4: 'THỨ SÁU',
            5: 'THỨ BẢY',
            6: 'CHỦ NHẬT'
        }
        day_name = vn_days.get(now.weekday(), 'CHỦ NHẬT')
        date_header = f"{day_name} NGÀY {now.day:02d} THÁNG {now.month:02d} NĂM {now.year}"
        time_header = now.strftime("%I:%M:%S %p")

        lines: List[str] = [
            "THAY ĐỔI GIÁ VÀNG",
            date_header,
            time_header,
            "(Chỉ hiển thị nhà cung cấp có thay đổi)",
            "=" * 80,
        ]

        total_changes = 0
        has_any_change = False

        for src in snapshot.get('sources', []):
            name = src.get('name', 'Không rõ')
            status = src.get('status')
            has_change = src.get('has_any_change', False)

            if status != 'ok' or not has_change:
                continue

            changed_items = [item for item in (src.get('items', []) or []) if item.get('has_price_change', False)]
            if not changed_items:
                continue

            has_any_change = True
            total_changes += len(changed_items)
            provider_name = self._display_provider_name(name)
            lines.append(f"Giá vàng {provider_name} [CÓ THAY ĐỔI]:")
            items_by_code = {item.get('code'): item for item in changed_items}

            for code in ['SJC', '999']:
                item = items_by_code.get(code)
                if not item:
                    continue

                buy = item.get('buyPrice')
                sell = item.get('sellPrice')
                buy_change = item.get('buyChange')
                sell_change = item.get('sellChange')

                lines.append(f"- {code} ●:")
                lines.append(f"  MUA VÀO: {self._format_vn_price(buy)} VNĐ{self._format_change_arrow(buy_change)}")
                lines.append(f"  BÁN RA : {self._format_vn_price(sell)} VNĐ{self._format_change_arrow(sell_change)}")
                lines.append("")

        lines.append("=" * 80)
        lines.append(f"Tổng số mục thay đổi: {total_changes}")
        lines.append("=" * 80)

        if not has_any_change:
            return None
        return "\n".join(lines).strip()

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
        """Call agent fetchers and return list of source dicts with parsed values.

        This function is resilient to two Agent behaviours:
        - Older Agent exposes individual helpers: `_fetch_mihong_prices()`, `_fetch_doji_prices()`, `_fetch_ngoctham_prices()` returning bullet text.
        - Hypothetical Agent may return a structured snapshot from `get_gold_price()`.

        We prefer calling individual fetchers and parsing their text; if those are not available
        we attempt to interpret a structured snapshot returned by `get_gold_price()`.
        """
        sources = []
        # Prefer calling individual fetchers if present
        try:
            mihong_fn = getattr(self.agent, '_fetch_mihong_prices', None)
            doji_fn = getattr(self.agent, '_fetch_doji_prices', None)
            ngoctham_fn = getattr(self.agent, '_fetch_ngoctham_prices', None)
            if callable(mihong_fn) and callable(doji_fn) and callable(ngoctham_fn):
                try:
                    mihong_text = mihong_fn()
                except Exception as e:
                    logging.exception('Error fetching Mi Hong prices: %s', e)
                    mihong_text = f'Error: {e}'
                try:
                    doji_text = doji_fn()
                except Exception as e:
                    logging.exception('Error fetching Doji prices: %s', e)
                    doji_text = f'Error: {e}'
                try:
                    ngoctham_text = ngoctham_fn()
                except Exception as e:
                    logging.exception('Error fetching Ngọc Thắm prices: %s', e)
                    ngoctham_text = f'Error: {e}'

                sources.append({'source': 'mihong', 'text': mihong_text, 'parsed': self._parse_bullet_text(mihong_text)})
                sources.append({'source': 'doji', 'text': doji_text, 'parsed': self._parse_bullet_text(doji_text)})
                sources.append({'source': 'ngoctham', 'text': ngoctham_text, 'parsed': self._parse_bullet_text(ngoctham_text)})
                return sources
        except Exception:
            logging.exception('Error while attempting individual fetchers')

        # Fallback: try to use structured snapshot from get_gold_price()
        try:
            snapshot = None
            try:
                snapshot = self.agent.get_gold_price()
            except Exception:
                snapshot = None
            if isinstance(snapshot, dict):
                for src_data in snapshot.get('sources', []):
                    src_name = src_data.get('name', 'unknown')
                    source_map = {'Mi Hong': 'mihong', 'Doji': 'doji', 'Ngoc Tham': 'ngoctham'}
                    source_code = source_map.get(src_name, src_name.lower())
                    items_list = src_data.get('items', [])
                    parsed = {}
                    if src_data.get('status') == 'ok':
                        for item in items_list:
                            code = item.get('code')
                            if not code:
                                continue
                            buy_price = item.get('buyPrice') or item.get('buy')
                            sell_price = item.get('sellPrice') or item.get('sell')
                            parsed[code] = {
                                'buy_raw': buy_price,
                                'sell_raw': sell_price,
                                'buy': self._to_int(buy_price) if buy_price is not None else None,
                                'sell': self._to_int(sell_price) if sell_price is not None else None,
                                'text': code,
                                'has_price_change': item.get('has_price_change', True),
                            }
                    sources.append({
                        'source': source_code,
                        'text': snapshot.get('message', '') if isinstance(snapshot, dict) else '',
                        'parsed': parsed,
                        'status': src_data.get('status'),
                    })
                return sources
        except Exception:
            logging.exception('Error parsing structured snapshot from agent.get_gold_price()')

        # If everything fails return empty list
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
            logging.info('%s empty — seeding current fetched prices', self.coll.name)
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

    def compare_with_db(self) -> Dict[str, Any]:
        """Fetch latest prices from `gold-price-collection` and compare with current fetch.

        Returns a dict with keys:
          - db: mapping (source -> code -> {'buy','sell','timestamp'})
          - current: mapping (source -> code -> {'buy','sell'})
          - diffs: list of entries where values differ
        """
        result: Dict[str, Any] = {'db': {}, 'current': {}, 'diffs': []}
        # load latest per (source,code)
        try:
            pipeline = [
                {'$sort': {'timestamp': -1}},
                {'$group': {'_id': {'source': '$source', 'code': '$code'}, 'doc': {'$first': '$$ROOT'}}}
            ]
            agg = list(self.coll.aggregate(pipeline))
        except Exception:
            logging.exception('DB aggregation failed in compare_with_db')
            agg = []

        for entry in agg:
            key = entry.get('_id') or {}
            src = key.get('source')
            code = key.get('code')
            doc = entry.get('doc') or {}
            if src is None:
                continue
            result['db'].setdefault(src, {})
            result['db'][src][code] = {
                'buy': doc.get('buy'),
                'sell': doc.get('sell'),
                'timestamp': doc.get('timestamp')
            }

        # get current snapshot using existing fetch logic
        sources = self._collect_sources()
        for s in sources:
            src = s.get('source')
            parsed: Dict[str, Dict[str, Any]] = s.get('parsed') or {}
            result['current'].setdefault(src, {})
            for code, vals in parsed.items():
                cur_buy = vals.get('buy')
                cur_sell = vals.get('sell')
                # normalize to int where possible
                cur_buy_n = self._to_int(cur_buy) if cur_buy is not None else None
                cur_sell_n = self._to_int(cur_sell) if cur_sell is not None else None
                result['current'][src][code] = {'buy': cur_buy_n, 'sell': cur_sell_n}

        # compute diffs
        for src, codes in result['current'].items():
            for code, curvals in codes.items():
                dbvals = result['db'].get(src, {}).get(code)
                db_buy = dbvals.get('buy') if dbvals else None
                db_sell = dbvals.get('sell') if dbvals else None
                cur_buy = curvals.get('buy')
                cur_sell = curvals.get('sell')
                if db_buy != cur_buy or db_sell != cur_sell:
                    result['diffs'].append({
                        'source': src,
                        'code': code,
                        'db_buy': db_buy,
                        'db_sell': db_sell,
                        'cur_buy': cur_buy,
                        'cur_sell': cur_sell,
                    })

        # also report any db entries missing from current snapshot
        for src, codes in result['db'].items():
            for code, dbvals in codes.items():
                if src not in result['current'] or code not in result['current'][src]:
                    result['diffs'].append({
                        'source': src,
                        'code': code,
                        'db_buy': dbvals.get('buy'),
                        'db_sell': dbvals.get('sell'),
                        'cur_buy': None,
                        'cur_sell': None,
                        'note': 'missing_in_current'
                    })

        return result

    async def job_info(self, context):
        """Periodic sender: always send `info` style message."""
        snapshot = self._get_snapshot()
        if not snapshot:
            logging.info('GoldWatcher info job: no snapshot data')
            return

        message = self.build_info_message(snapshot)
        if not message:
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
        snapshot = self._get_snapshot()
        if not snapshot:
            logging.info('GoldWatcher changes job: no snapshot data')
            return

        message = self.build_changes_message(snapshot)
        if not message:
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
