import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Protocol
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

try:
    from pymongo import MongoClient, DESCENDING
except Exception:
    MongoClient = None
    DESCENDING = None

class GoldPriceProvider(Protocol):
    name: str

    def fetch(self) -> Dict[str, Any]:
        ...


class _CallableGoldPriceProvider:
    def __init__(self, name: str, fetch):
        self.name = name
        self._fetch = fetch

    def fetch(self) -> Dict[str, Any]:
        return self._fetch()


class GoldPriceService:
    def __init__(self, api_client, mongo_uri: Optional[str] = None,
                 db_name: str = MONGO_DB_NAME, collection: str = MONGO_COLLECTION):
        self.api_client = api_client
        self.mongo_client = None
        self.mongo_db = None
        self.mongo_coll = None
        effective_mongo_uri = mongo_uri if mongo_uri is not None else MONGO_URI
        if MongoClient and effective_mongo_uri:
            try:
                self.mongo_client = MongoClient(effective_mongo_uri, serverSelectionTimeoutMS=5000)
                self.mongo_db = self.mongo_client[db_name]
                self.mongo_coll = self.mongo_db[collection]
            except Exception:
                logging.exception('GoldPriceService: MongoDB connection failed')
                self.mongo_client = None
                self.mongo_db = None
                self.mongo_coll = None

        self.providers: List[GoldPriceProvider] = [
            _CallableGoldPriceProvider("Mi Hong", self._fetch_mihong_prices_struct),
            _CallableGoldPriceProvider("Doji", self._fetch_doji_prices_struct),
            _CallableGoldPriceProvider("Ngoc Tham", self._fetch_ngoctham_prices_struct),
        ]

    def get_snapshot(self) -> Dict[str, Any]:
        as_of_dt = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        snapshot = {
            "as_of": as_of_dt,
            "currency": "VND",
            "sources": [],
            "normalized": [],
            "note": "Trao niem tin nhan tai loc.",
        }

        for provider in self.providers:
            try:
                result = provider.fetch()
            except Exception as exc:
                result = {
                    "name": getattr(provider, "name", "unknown"),
                    "status": "error",
                    "error": str(exc),
                    "raw": None,
                    "items": [],
                }

            if result.get("status") == "ok":
                # Apply change detection and computation for each item
                has_any_change = False
                for item in result.get("items", []):
                    self._apply_db_change(result.get("name"), item)
                    
                    # has_price_change is based on baseline comparison (for display)
                    if item.get("has_price_change", False):
                        has_any_change = True
                    
                    # Store to DB if price changed from last stored value
                    # (insert_if_changed handles the check internally)
                    self.insert_if_changed(
                        result.get("name"),
                        item.get("code"),
                        item.get("buyPrice"),
                        item.get("sellPrice"),
                        item.get("dateTime"),
                    )
                
                # Add source-level change flag
                result["has_any_change"] = has_any_change
                snapshot["normalized"].extend(result.get("items", []))
            else:
                # Mark error sources as having no changes
                result["has_any_change"] = False

            snapshot["sources"].append(result)

        snapshot["message"] = self._format_gold_price_message(snapshot)
        return snapshot

    def _format_gold_price_message(self, snapshot: Dict[str, Any]) -> str:
        """Format gold price message grouped by provider."""
        lines: List[str] = []

        def display_provider_name(name: str) -> str:
            if not name:
                return "Không rõ"
            name_map = {
                "Ngoc Tham": "Ngọc Thẩm",
            }
            return name_map.get(name, name)

        def format_change_arrow(change: Optional[int]) -> str:
            if change is None or change == 0:
                return ""
            arrow = "↑" if change > 0 else "↓"
            change_str = f"{change:+,}".replace(",", ".")
            return f" ({change_str} {arrow})"

        has_data = False
        for src in snapshot.get("sources", []):
            provider_name = display_provider_name(src.get("name", "Unknown"))
            status = src.get("status")
            if status != "ok":
                continue

            items = src.get("items", [])
            items_by_code = {item.get("code"): item for item in items}

            lines.append(f"Giá vàng {provider_name}:")
            for code in ("SJC", "999"):
                item = items_by_code.get(code)
                if not item:
                    continue

                has_data = True
                buy = item.get("buyPrice")
                sell = item.get("sellPrice")
                buy_change = item.get("buyChange")
                sell_change = item.get("sellChange")

                lines.append(f"- {code}:")
                if sell is not None:
                    sell_str = self._format_price(sell)
                    sell_change_str = format_change_arrow(sell_change)
                    lines.append(f"  • Giá bán: {sell_str} VNĐ{sell_change_str}")
                if buy is not None:
                    buy_str = self._format_price(buy)
                    buy_change_str = format_change_arrow(buy_change)
                    lines.append(f"  • Giá mua: {buy_str} VNĐ{buy_change_str}")
                lines.append("")

        if not has_data:
            return "Không có dữ liệu giá vàng."

        merged = "\n".join(lines).rstrip()
        note = snapshot.get("note") or ""
        return f"{merged}\n\n{note}".strip()

    def _parse_price(self, val: Optional[Any]) -> Optional[int]:
        if val is None:
            return None
        raw = str(val).strip()
        if not raw:
            return None
        digits = re.sub(r"[^0-9]", "", raw)
        if not digits:
            return None
        try:
            return int(digits)
        except Exception:
            return None

    def _format_price(self, val: Optional[int]) -> str:
        """Format price in Vietnamese currency format."""
        if val is None:
            return "Không có"
        try:
            return f"{int(val):,}".replace(",", ".")
        except Exception:
            return str(val)

    def _normalize_datetime(self, dt_str: str) -> str:
        """Normalize datetime to DD/MM/YYYY HH:MM format."""
        if not dt_str:
            return ""
        try:
            import datetime as dt_module
            if "T" in dt_str:
                dt_clean = dt_str.split("+")[0].split("-0")[0].split("Z")[0]
                dt_obj = dt_module.datetime.fromisoformat(dt_clean)
                return dt_obj.strftime("%d/%m/%Y %H:%M")
            if " " in dt_str and "-" in dt_str:
                dt_obj = dt_module.datetime.strptime(dt_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
                return dt_obj.strftime("%d/%m/%Y %H:%M")
            if "/" in dt_str:
                parts = dt_str.split()
                if parts:
                    return parts[0] + (f" {parts[1]}" if len(parts) > 1 else "")
                return dt_str
            return dt_str
        except Exception as e:
            logging.debug("Could not normalize datetime '%s': %s", dt_str, e)
            return dt_str

    def _source_key(self, source: Optional[str]) -> str:
        return re.sub(r"\s+", "", (source or "")).lower()

    def _compute_price_change(self, source: str, code: str, current_price: Optional[int], price_type: str) -> Optional[int]:
        """Compute price change vs. baseline price (first price of the day) in MongoDB."""
        if self.mongo_coll is None:
            logging.debug("No MongoDB connection for %s/%s", source, code)
            return None
        if current_price is None:
            logging.debug("Current price is None for %s/%s %s", source, code, price_type)
            return None
        try:
            import datetime as dt_module
            src_key = self._source_key(source)
            
            # Get the start of today (00:00:00)
            today_start = dt_module.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Find the FIRST (oldest) price recorded today as baseline
            baseline_doc = self.mongo_coll.find_one(
                {
                    "source": src_key,
                    "code": code,
                    "timestamp": {"$gte": today_start}
                },
                sort=[("timestamp", 1)],  # Ascending - get FIRST of day
            )
            
            if not baseline_doc:
                # No data today yet, try to get yesterday's last price as baseline
                yesterday_start = today_start - dt_module.timedelta(days=1)
                baseline_doc = self.mongo_coll.find_one(
                    {
                        "source": src_key,
                        "code": code,
                        "timestamp": {"$gte": yesterday_start, "$lt": today_start}
                    },
                    sort=[("timestamp", -1)],  # Descending - get last of yesterday
                )
            
            if not baseline_doc:
                logging.info("No baseline data found for %s/%s (source_key=%s) - first time collecting", source, code, src_key)
                return None
                
            baseline_price = baseline_doc.get(price_type)
            if baseline_price is None:
                logging.warning("Baseline doc exists but %s is None for %s/%s", price_type, source, code)
                return None
                
            change = current_price - baseline_price
            baseline_time = baseline_doc.get('timestamp', 'unknown')
            logging.info(
                "Computed %s change for %s/%s: %d - %d (baseline: %s) = %d",
                price_type,
                source,
                code,
                current_price,
                baseline_price,
                baseline_time,
                change,
            )
            return change
        except Exception:
            logging.exception("Failed computing price change for %s/%s", source, code)
            return None

    def _check_price_change(
        self,
        source: str,
        code: str,
        buy_price: Optional[int],
        sell_price: Optional[int],
    ) -> bool:
        """Return True if price changed vs. last stored doc (or if no history)."""
        if buy_price is None and sell_price is None:
            return False
        if self.mongo_coll is None:
            return True
        try:
            src_key = self._source_key(source)
            last_doc = self.mongo_coll.find_one(
                {"source": src_key, "code": code},
                sort=[("timestamp", -1)],
            )
            if not last_doc:
                return True

            last_buy = last_doc.get("buy")
            last_sell = last_doc.get("sell")

            if buy_price is not None and (last_buy is None or buy_price != last_buy):
                return True
            if sell_price is not None and (last_sell is None or sell_price != last_sell):
                return True

            return False
        except Exception:
            logging.exception("Failed checking price change for %s/%s", source, code)
            return True

    def insert_if_changed(
        self,
        source: str,
        code: str,
        buy_price: Optional[int],
        sell_price: Optional[int],
        datetime_str: Optional[str] = None,
    ) -> bool:
        """Insert a new price document only if the price changed.

        Returns:
            True if price changed and was inserted, False otherwise
        """
        if self.mongo_coll is None:
            logging.debug("No MongoDB connection, cannot store price for %s/%s", source, code)
            return False

        if buy_price is None and sell_price is None:
            logging.debug("Skipping insert for %s/%s: both prices are None", source, code)
            return False

        if not self._check_price_change(source, code, buy_price, sell_price):
            logging.info("No price change for %s/%s, skipping insert", source, code)
            return False

        try:
            import datetime as dt_module
            if datetime_str:
                try:
                    timestamp = dt_module.datetime.fromisoformat(datetime_str)
                except Exception:
                    timestamp = dt_module.datetime.utcnow()
            else:
                timestamp = dt_module.datetime.utcnow()

            src_key = self._source_key(source)
            doc = {
                "timestamp": timestamp,
                "source": src_key,
                "code": code,
                "buy": buy_price,
                "sell": sell_price,
                "source_display": source,
            }

            self.mongo_coll.insert_one(doc)
            logging.info(
                "Stored price change for %s/%s: buy=%s sell=%s at %s",
                source,
                code,
                buy_price,
                sell_price,
                timestamp,
            )
            return True
        except Exception as e:
            logging.exception("Error inserting price for %s/%s: %s", source, code, e)
            return False

    def _apply_db_change(self, source: str, item: Dict[str, Any]) -> None:
        code = item.get('code')
        if not code:
            return
        buy_price = item.get('buyPrice')
        sell_price = item.get('sellPrice')
        
        # Prioritize API-provided changes first
        api_buy_change = item.get('buyChange')
        api_sell_change = item.get('sellChange')
        
        logging.debug("_apply_db_change for %s/%s: api_buy_change=%s, api_sell_change=%s", 
                     source, code, api_buy_change, api_sell_change)
        
        # If API didn't provide changes, compute from DB baseline
        if api_buy_change is None:
            computed_buy = self._compute_price_change(source, code, buy_price, 'buy')
            item['buyChange'] = computed_buy
            logging.debug("Computed buy change for %s/%s: %s", source, code, computed_buy)
        if api_sell_change is None:
            computed_sell = self._compute_price_change(source, code, sell_price, 'sell')
            item['sellChange'] = computed_sell
            logging.debug("Computed sell change for %s/%s: %s", source, code, computed_sell)
        
        item['change'] = {
            'buy': item.get('buyChange'),
            'sell': item.get('sellChange'),
        }
        
        # CRITICAL: has_price_change must check against LAST STORED value (not baseline)
        # This ensures "changes" command only shows NEW changes, not repeated baseline diffs
        item['has_price_change'] = self._check_price_change(source, code, buy_price, sell_price)

    def _fetch_mihong_prices_struct(self):
        url = "https://api.mihong.vn/v1/gold-prices?market=domestic"
        headers = {}
        max_retries = 5
        resp = None
        for attempt in range(1, max_retries + 1):
            resp = self.api_client.get(url, headers=headers, timeout=10, verify=False)
            if resp.get('ok'):
                break
            logging.warning("Mi Hong API request failed (attempt %d/%d): %s", attempt, max_retries, resp.get('error'))
            if attempt < max_retries:
                time.sleep(attempt)
        else:
            return {
                "name": "Mi Hong",
                "status": "error",
                "error": "Khong lay duoc gia vang Mi Hong.",
                "raw": [],
                "items": [],
            }

        parsed = resp.get('json')
        text = resp.get('text', '')

        data_list = None
        if isinstance(parsed, dict):
            if 'data' in parsed and isinstance(parsed['data'], list):
                data_list = parsed['data']
            else:
                for v in parsed.values():
                    if isinstance(v, list):
                        data_list = v
                        break
        elif isinstance(parsed, list):
            data_list = parsed
        else:
            try:
                j = json.loads(text)
                if isinstance(j, dict) and 'data' in j and isinstance(j['data'], list):
                    data_list = j['data']
                elif isinstance(j, list):
                    data_list = j
            except Exception:
                pass

        if not data_list:
            return {
                "name": "Mi Hong",
                "status": "error",
                "error": "Khong tim thay du lieu gia vang phu hop.",
                "raw": [],
                "items": [],
            }

        wanted = {"SJC", "999"}
        raw_items = []
        items = []
        for item in data_list:
            if not isinstance(item, dict):
                continue
            code = str(item.get('code') or item.get('Code') or item.get('symbol') or '').strip()
            if not code:
                for k in ['ma', 'type']:
                    if k in item:
                        code = str(item.get(k) or '').strip()
                        break
            if not code:
                continue
            code_norm = code.upper()
            if code_norm not in wanted:
                if code_norm.replace('.', '').isdigit() and '999' not in code_norm:
                    continue
                if '999' not in code_norm and 'SJC' not in code_norm:
                    continue
            buying = item.get('buyingPrice') or item.get('buying_price') or item.get('Buy') or item.get('buy') or item.get('gia_mua') or item.get('mua')
            selling = item.get('sellingPrice') or item.get('selling_price') or item.get('Sell') or item.get('sell') or item.get('gia_ban') or item.get('ban')
            dt = item.get('dateTime') or item.get('date_time') or item.get('date') or item.get('updated_at') or ''
            buy_change = item.get('buyChange') or item.get('buy_change')
            sell_change = item.get('sellChange') or item.get('sell_change')
            buy_change_pct = item.get('buyChangePercent') or item.get('buy_change_percent')
            sell_change_pct = item.get('sellChangePercent') or item.get('sell_change_percent')

            buy_price = self._parse_price(buying)
            sell_price = self._parse_price(selling)
            buy_change_val = self._parse_price(buy_change)
            sell_change_val = self._parse_price(sell_change)

            logging.info('Mi Hong %s: buy=%s sell=%s (buyChange=%s sellChange=%s)', 
                        code_norm, buy_price, sell_price, buy_change_val, sell_change_val)

            raw_items.append({
                "buyingPrice": buy_price,
                "sellingPrice": sell_price,
                "code": code_norm,
                "sellChange": sell_change_val,
                "sellChangePercent": sell_change_pct,
                "buyChange": buy_change_val,
                "buyChangePercent": buy_change_pct,
                "dateTime": str(dt) if dt is not None else "",
            })

            items.append({
                "source": "Mi Hong",
                "code": code_norm,
                "buyPrice": buy_price,
                "sellPrice": sell_price,
                "dateTime": str(dt) if dt is not None else "",
                "buyChange": buy_change_val,
                "sellChange": sell_change_val,
            })

        if not items:
            return {
                "name": "Mi Hong",
                "status": "error",
                "error": "Khong tim thay du lieu gia vang phu hop.",
                "raw": [],
                "items": [],
            }

        return {
            "name": "Mi Hong",
            "status": "ok",
            "error": None,
            "raw": raw_items,
            "items": items,
        }

    def _fetch_doji_prices_struct(self):
        doji_url = "https://giavang.doji.vn/sites/default/files/data/hienthi/vungmien_109.dat"
        try:
            resp2 = self.api_client.get(doji_url, timeout=10, verify=False)
        except Exception as e:
            return {
                "name": "Doji",
                "status": "error",
                "error": f"Loi khi lay Doji: {e}",
                "raw": [],
                "items": [],
            }

        if not resp2.get('ok'):
            return {
                "name": "Doji",
                "status": "error",
                "error": f"Loi khi lay Doji: {resp2.get('error')}",
                "raw": [],
                "items": [],
            }

        raw = (resp2.get('text') or '')
        if not raw.strip():
            return {
                "name": "Doji",
                "status": "error",
                "error": "Khong co du lieu tu Doji.",
                "raw": [],
                "items": [],
            }

        def map_code(label: str) -> Optional[str]:
            if 'SJC' in label:
                return 'SJC'
            if '999' in label:
                return '999'
            return None

        try:
            rows = re.findall(r'<tr[^>]*>.*?</tr>', raw, flags=re.S | re.I)
            targets = [
                "SJC - Bán Lẻ",
                "Nhẫn Tròn 9999 Hưng Thịnh Vượng - Bán Lẻ",
            ]
            as_of_dt = time.strftime("%Y-%m-%dT%H:%M:%S%z")
            raw_items = []
            items = []
            for tr in rows:
                tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, flags=re.S | re.I)
                if not tds:
                    continue
                clean = [re.sub(r'<.*?>', '', td).strip() for td in tds]
                label = clean[0]
                if any(label == t or t in label for t in targets):
                    nums = []
                    for td in clean[1:]:
                        m = re.search(r'([0-9][0-9\.,]+)', td)
                        if m:
                            nums.append(m.group(1))
                    buy = nums[0] if len(nums) > 0 else 'N/A'
                    sell = nums[1] if len(nums) > 1 else ('N/A' if len(nums) > 0 else 'N/A')
                    buy_price_raw = self._parse_price(buy)
                    sell_price_raw = self._parse_price(sell)
                    # Doji prices need to be multiplied by 1000
                    buy_price = buy_price_raw * 1000 if buy_price_raw else None
                    sell_price = sell_price_raw * 1000 if sell_price_raw else None
                    code = map_code(label)

                    logging.info('Doji %s: buy=%s sell=%s (raw: %s/%s) from label=%s', 
                                code, buy_price, sell_price, buy_price_raw, sell_price_raw, label)

                    raw_items.append({
                        "label": label,
                        "buyingPrice": buy_price,
                        "sellingPrice": sell_price,
                    })

                    if code:
                        items.append({
                            "source": "Doji",
                            "code": code,
                            "buyPrice": buy_price,
                            "sellPrice": sell_price,
                            "dateTime": as_of_dt,
                            "buyChange": None,
                            "sellChange": None,
                        })
            if not items:
                return {
                    "name": "Doji",
                    "status": "error",
                    "error": "Khong tim thay muc Doji phu hop.",
                    "raw": raw_items,
                    "items": [],
                }
            return {
                "name": "Doji",
                "status": "ok",
                "error": None,
                "raw": raw_items,
                "items": items,
            }
        except Exception as e:
            return {
                "name": "Doji",
                "status": "error",
                "error": f"Loi phan tich Doji: {e}",
                "raw": [],
                "items": [],
            }

    def _fetch_ngoctham_prices_struct(self):
        url = "https://ngoctham.com/ajax/proxy_banggia.php"
        try:
            resp = self.api_client.get(url, timeout=10, verify=False)
        except Exception as e:
            return {
                "name": "Ngoc Tham",
                "status": "error",
                "error": f"Loi khi lay du lieu Ngoc Tham: {e}",
                "raw": None,
                "items": [],
            }

        if not resp.get('ok'):
            return {
                "name": "Ngoc Tham",
                "status": "error",
                "error": f"Loi khi lay du lieu Ngoc Tham: {resp.get('error')}",
                "raw": None,
                "items": [],
            }

        parsed = resp.get('json')
        text = resp.get('text') or ''

        def extract_payload(data_obj):
            if isinstance(data_obj, dict) and 'chitiet' in data_obj:
                return data_obj
            if isinstance(data_obj, dict) and isinstance(data_obj.get('data'), list):
                for entry in data_obj.get('data'):
                    if isinstance(entry, dict) and 'chitiet' in entry:
                        return entry
            if isinstance(data_obj, list):
                for entry in data_obj:
                    if isinstance(entry, dict) and 'chitiet' in entry:
                        return entry
            return None

        payload = extract_payload(parsed)
        if payload is None:
            try:
                j = json.loads(text)
                payload = extract_payload(j)
            except Exception:
                payload = None

        if not payload or not isinstance(payload.get('chitiet'), list):
            return {
                "name": "Ngoc Tham",
                "status": "error",
                "error": "Khong tim thay du lieu Ngoc Tham cho muc yeu cau.",
                "raw": None,
                "items": [],
            }

        wanted_ids = {"10", "58"}
        filtered = []
        items = []
        payload_date = payload.get('date') or ""
        for detail in payload.get('chitiet', []):
            if not isinstance(detail, dict):
                continue
            idloaivang = detail.get('idloaivang') or []
            id_set = {str(x) for x in idloaivang} if isinstance(idloaivang, list) else {str(idloaivang)}
            if not wanted_ids.intersection(id_set):
                continue
            filtered.append(detail)

            code = 'SJC' if '58' in id_set else '999'
            buy = detail.get('giamua') or detail.get('mua') or ''
            sell = detail.get('giaban') or detail.get('ban') or ''
            buy_price = self._parse_price(buy)
            sell_price = self._parse_price(sell)

            logging.info('Ngoc Tham %s (idloaivang=%s): buy=%s sell=%s', 
                        code, id_set, buy_price, sell_price)

            items.append({
                "source": "Ngoc Tham",
                "code": code,
                "buyPrice": buy_price,
                "sellPrice": sell_price,
                "dateTime": payload_date,
                "buyChange": None,
                "sellChange": None,
            })

        raw_payload = {
            "id": payload.get('id'),
            "date": payload_date,
            "chitiet": filtered,
        }

        if not items:
            return {
                "name": "Ngoc Tham",
                "status": "error",
                "error": "Khong tim thay du lieu Ngoc Tham cho muc yeu cau.",
                "raw": raw_payload,
                "items": [],
            }

        return {
            "name": "Ngoc Tham",
            "status": "ok",
            "error": None,
            "raw": raw_payload,
            "items": items,
        }

    # ==================== Public API Methods ====================

    @staticmethod
    def _format_vn_price(val: Optional[int]) -> str:
        """Format price in Vietnamese currency format (dot separator)."""
        if val is None:
            return "Không có"
        try:
            return f"{int(val):,}".replace(',', '.')
        except Exception:
            return str(val)

    @staticmethod
    def _format_change_arrow(change: Optional[int]) -> str:
        """Format change value with arrow direction."""
        if change is None or change == 0:
            return ""
        arrow = "↑" if change > 0 else "↓"
        change_str = f"{change:+,}".replace(',', '.')
        return f" ({change_str} {arrow})"

    @staticmethod
    def _display_provider_name(name: str) -> str:
        """Normalize provider display names in Vietnamese."""
        if not name:
            return "Không rõ"
        name_map = {
            "Ngoc Tham": "Ngọc Thẩm",
        }
        return name_map.get(name, name)

    def _compute_change_vs_yesterday(self, source: str, code: str, buy_price: Optional[int], sell_price: Optional[int]):
        """Return (buy_change, sell_change) vs latest record of yesterday for source/code."""
        if self.mongo_coll is None:
            return None, None

        try:
            import datetime as dt_module
            today_start = dt_module.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            yesterday_start = today_start - dt_module.timedelta(days=1)

            last_yesterday = self.mongo_coll.find_one(
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

    def get_info(self) -> Dict[str, Any]:
        """Get full gold price information with yesterday comparison fallback.
        
        Returns:
            Dict with:
                - message: Formatted Vietnamese message string
                - data: Full snapshot dict with all provider data
                - has_any_change: Boolean indicating if any provider has changes
        """
        import datetime as dt_module
        
        snapshot = self.get_snapshot()
        # use Hanoi/GMT+7 time for headers
        try:
            from zoneinfo import ZoneInfo
            now = dt_module.datetime.now(ZoneInfo('Asia/Ho_Chi_Minh'))
        except Exception:
            now = dt_module.datetime.utcnow() + dt_module.timedelta(hours=7)
        
        vn_days = {
            0: 'THỨ HAI', 1: 'THỨ BA', 2: 'THỨ TƯ',
            3: 'THỨ NĂM', 4: 'THỨ SÁU', 5: 'THỨ BẢY', 6: 'CHỦ NHẬT'
        }
        day_name = vn_days.get(now.weekday(), 'CHỦ NHẬT')
        date_header = f"{day_name} NGÀY {now.day:02d} THÁNG {now.month:02d} NĂM {now.year}"
        time_header = now.strftime("%I:%M:%S %p")

        lines = [
            "THÔNG TIN GIÁ VÀNG",
            date_header,
            time_header,
            "=" * 80,
        ]

        has_data = False
        overall_has_change = False

        for src in snapshot.get('sources', []):
            provider_name = self._display_provider_name(src.get('name', 'Unknown'))
            source_name = src.get('name', 'Unknown')
            status = src.get('status')
            has_any_change = src.get('has_any_change', False)

            if status != 'ok':
                continue

            if has_any_change:
                overall_has_change = True

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

                # Info-only: if no intraday changes, compare with yesterday
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

        lines.append("=" * 80)
        message = "\n".join(lines)

        return {
            'message': message,
            'data': snapshot,
            'has_any_change': overall_has_change
        }

    def get_changes(self) -> Dict[str, Any]:
        """Get only gold price changes (filters out unchanged providers).
        
        Returns:
            Dict with:
                - message: Formatted Vietnamese message string (None if no changes)
                - data: Filtered snapshot with only changed providers
                - total_changes: Number of changed items
                - has_any_change: Boolean indicating if any changes detected
        """
        import datetime as dt_module
        
        snapshot = self.get_snapshot()
        # use GMT+7 / Hanoi time
        try:
            from zoneinfo import ZoneInfo
            now = dt_module.datetime.now(ZoneInfo('Asia/Ho_Chi_Minh'))
        except Exception:
            now = dt_module.datetime.utcnow() + dt_module.timedelta(hours=7)
        
        vn_days = {
            0: 'THỨ HAI', 1: 'THỨ BA', 2: 'THỨ TƯ',
            3: 'THỨ NĂM', 4: 'THỨ SÁU', 5: 'THỨ BẢY', 6: 'CHỦ NHẬT'
        }
        day_name = vn_days.get(now.weekday(), 'CHỦ NHẬT')
        date_header = f"{day_name} NGÀY {now.day:02d} THÁNG {now.month:02d} NĂM {now.year}"
        time_header = now.strftime("%I:%M:%S %p")

        lines = [
            "THAY ĐỔI GIÁ VÀNG",
            date_header,
            time_header,
            "=" * 80,
        ]

        total_changes = 0
        has_any_change = False
        filtered_sources = []

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
            
            # Add to filtered sources
            filtered_src = {**src, 'items': changed_items}
            filtered_sources.append(filtered_src)
            
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

        if not has_any_change:
            lines.append("Không có thay đổi giá nào được phát hiện.")
            lines.append("")

        # summary lines intentionally omitted for consistency

        filtered_snapshot = {
            **snapshot,
            'sources': filtered_sources
        }

        return {
            'message': "\n".join(lines) if has_any_change else None,
            'data': filtered_snapshot,
            'total_changes': total_changes,
            'has_any_change': has_any_change
        }

    def check_database(self) -> Dict[str, Any]:
        """Check database status and return statistics.
        
        Returns:
            Dict with database statistics and formatted message
        """
        if self.mongo_coll is None:
            return {
                'message': 'Không có kết nối MongoDB',
                'total_count': 0,
                'today_count': 0,
                'stats': {}
            }
        
        try:
            import datetime as dt_module
            from collections import Counter
            
            count = self.mongo_coll.count_documents({})
            lines = [
                "=" * 80,
                "KIỂM TRA CƠ SỞ DỮ LIỆU",
                "=" * 80,
                f"Tổng số bản ghi: {count}"
            ]
            
            stats = {
                'total_count': count,
                'today_count': 0,
                'by_source_code': {},
                'latest_records': []
            }
            
            if count > 0:
                today = dt_module.datetime.now().date()
                recent_for_stats = list(self.mongo_coll.find().sort('timestamp', -1).limit(500))
                today_docs = [
                    doc for doc in recent_for_stats
                    if hasattr(doc.get('timestamp'), 'date') and doc.get('timestamp').date() == today
                ]
                today_counter = Counter((doc.get('source', 'N/A'), doc.get('code', 'N/A')) for doc in today_docs)
                
                stats['today_count'] = len(today_docs)
                stats['by_source_code'] = dict(today_counter)
                
                lines.append(f"Bản ghi hôm nay: {len(today_docs)}")
                if today_counter:
                    lines.append("Theo nguồn/mã (hôm nay):")
                    for (src, code), qty in sorted(today_counter.items()):
                        lines.append(f"  - {src:10s} | {code:5s} | {qty} bản ghi")
                
                # Show latest records
                latest = list(self.mongo_coll.find().sort('timestamp', -1).limit(10))
                lines.append(f"\n10 bản ghi gần nhất:")
                for doc in latest:
                    ts = doc.get('timestamp', 'N/A')
                    src = doc.get('source', 'N/A')
                    code = doc.get('code', 'N/A')
                    buy = doc.get('buy')
                    sell = doc.get('sell')
                    lines.append(f"  {ts} | {src:10s} | {code:5s} | Mua: {self._format_vn_price(buy):15s} | Bán: {self._format_vn_price(sell):15s}")
                    stats['latest_records'].append({
                        'timestamp': ts,
                        'source': src,
                        'code': code,
                        'buy': buy,
                        'sell': sell
                    })
            else:
                lines.append("\nCơ sở dữ liệu trống - lần chạy đầu tiên sẽ tạo dữ liệu cơ bản")

            return {
                'message': '\n'.join(lines),
                **stats
            }
            
        except Exception:
            logging.exception("Lỗi khi kiểm tra database")
            return {
                'message': 'Lỗi khi kiểm tra database',
                'total_count': 0,
                'today_count': 0,
                'stats': {}
            }
