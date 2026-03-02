import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Protocol

try:
    from pymongo import MongoClient, DESCENDING
except Exception:
    MongoClient = None
    DESCENDING = None

try:
    from watcher import DEFAULT_MONGO_URI
except Exception:
    DEFAULT_MONGO_URI = None


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
    def __init__(self, api_client, mongo_uri: Optional[str] = DEFAULT_MONGO_URI,
                 db_name: str = 'bot', collection: str = 'prices'):
        self.api_client = api_client
        self.mongo_client = None
        self.mongo_db = None
        self.mongo_coll = None
        if MongoClient and mongo_uri:
            try:
                self.mongo_client = MongoClient(mongo_uri, serverSelectionTimeoutMS=5000)
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
                for item in result.get("items", []):
                    self._apply_db_change(result.get("name"), item)
                snapshot["normalized"].extend(result.get("items", []))

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
        """Compute price change vs. last stored price in MongoDB."""
        if self.mongo_coll is None or current_price is None:
            return None
        try:
            src_key = self._source_key(source)
            last_doc = self.mongo_coll.find_one(
                {"source": src_key, "code": code},
                sort=[("timestamp", -1)],
            )
            if not last_doc:
                return None
            last_price = last_doc.get(price_type)
            if last_price is None:
                return None
            change = current_price - last_price
            logging.info(
                "Computed %s change for %s/%s: %d - %d = %d",
                price_type,
                source,
                code,
                current_price,
                last_price,
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
        
        # If API didn't provide changes, compute from DB
        if api_buy_change is None:
            item['buyChange'] = self._compute_price_change(source, code, buy_price, 'buy')
        if api_sell_change is None:
            item['sellChange'] = self._compute_price_change(source, code, sell_price, 'sell')
        
        item['change'] = {
            'buy': item.get('buyChange'),
            'sell': item.get('sellChange'),
        }
        
        # Check if price has changed for selective storage
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
