"""HOSE (Ho Chi Minh Stock Exchange) stock market data service.

Uses VNDirect public API as the primary data source:
    https://finfo-api.vndirect.com.vn/v4/stock_prices

Data from VNDirect represents end-of-day prices for the most recent
trading session.  The watcher calls ``get_changes`` periodically; it
stores each new close in MongoDB and raises an alert only when the
absolute percentage move exceeds a configurable threshold.

HOSE market hours (Asia/Ho_Chi_Minh, UTC+7):
    ATO (opening) :  9:00 – 9:15
    Morning session: 9:15 – 11:30
    Afternoon     : 13:00 – 14:30
    ATC (closing) : 14:30 – 15:00
"""

import logging
import re
import time as _time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config import MONGO_URI, MONGO_DB_NAME

try:
    from zoneinfo import ZoneInfo
    _HCM_TZ = ZoneInfo("Asia/Ho_Chi_Minh")
except Exception:
    _HCM_TZ = None

try:
    from pymongo import MongoClient, DESCENDING
except Exception:
    MongoClient = None
    DESCENDING = None

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HOSE_STOCK_COLLECTION = "hose-stock-collection"
VNDIRECT_API_BASE = "https://finfo-api.vndirect.com.vn/v4"

# Well-known HOSE indices
KNOWN_INDICES = {"VNINDEX", "VN30", "HNXINDEX", "UPINDEX"}

VN_DAYS = {
    0: "THỨ HAI", 1: "THỨ BA", 2: "THỨ TƯ",
    3: "THỨ NĂM", 4: "THỨ SÁU", 5: "THỨ BẢY", 6: "CHỦ NHẬT",
}


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------
class HOSEStockService:
    """Fetch, store and format HOSE stock / index data.

    Parameters
    ----------
    api_client:
        An ``APIClient`` instance (from ``api_client.py``).
    mongo_uri:
        Optional MongoDB connection URI.  Falls back to ``config.MONGO_URI``.
    db_name:
        MongoDB database name.
    collection:
        MongoDB collection name for storing price snapshots.
    """

    def __init__(
        self,
        api_client,
        mongo_uri: Optional[str] = None,
        db_name: str = MONGO_DB_NAME,
        collection: str = HOSE_STOCK_COLLECTION,
    ):
        self.api_client = api_client
        self.mongo_client = None
        self.mongo_coll = None

        effective_uri = mongo_uri if mongo_uri is not None else MONGO_URI
        if MongoClient and effective_uri:
            try:
                self.mongo_client = MongoClient(effective_uri, serverSelectionTimeoutMS=5000)
                db = self.mongo_client[db_name]
                self.mongo_coll = db[collection]
            except Exception:
                logging.exception("HOSEStockService: MongoDB connection failed")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _now_hcm(self) -> datetime:
        if _HCM_TZ:
            return datetime.now(_HCM_TZ)
        return datetime.utcnow() + timedelta(hours=7)

    def _fmt_price(self, val, decimals: int = 2) -> str:
        """Format a price with Vietnamese dot-separator style."""
        if val is None:
            return "N/A"
        try:
            f = float(val)
            # For large whole-number prices (> 1000 VND), skip decimal places
            if decimals == 0 or (f == int(f) and f > 1000):
                return f"{int(f):,}".replace(",", ".")
            return f"{f:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return str(val)

    def _fmt_volume(self, val) -> str:
        if val is None:
            return "N/A"
        try:
            return f"{int(val):,}".replace(",", ".")
        except Exception:
            return str(val)

    def _fmt_value_billion(self, val) -> str:
        """Format a monetary value in billions VND."""
        if val is None:
            return "N/A"
        try:
            b = float(val) / 1_000_000_000
            return f"{b:,.2f} tỷ".replace(",", "X").replace(".", ",").replace("X", ".")
        except Exception:
            return str(val)

    def _pct_arrow(self, pct) -> str:
        if pct is None:
            return ""
        try:
            f = float(pct)
            if f > 0:
                arrow = "↑"
                sign = "+"
            elif f < 0:
                arrow = "↓"
                sign = ""
            else:
                arrow = "→"
                sign = ""
            return f" ({sign}{f:.2f}% {arrow})"
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # VNDirect API
    # ------------------------------------------------------------------

    def _fetch_vndirect(self, query: str, size: int = 1, sort: str = "date:desc") -> Optional[List[Dict]]:
        """Fetch records from the VNDirect stock-prices endpoint.

        Returns a list of price dictionaries, or ``None`` on failure.
        """
        url = f"{VNDIRECT_API_BASE}/stock_prices"
        params = {"sort": sort, "q": query, "size": size, "page": 1}
        max_retries = 3
        for attempt in range(1, max_retries + 1):
            resp = self.api_client.get(url, params=params, timeout=10)
            if resp.get("ok"):
                parsed = resp.get("json")
                if isinstance(parsed, dict) and isinstance(parsed.get("data"), list):
                    return parsed["data"]
                logging.warning("VNDirect API: unexpected response shape: %s", str(parsed)[:200])
                return None
            logging.warning(
                "VNDirect API attempt %d/%d failed (query=%s): %s",
                attempt, max_retries, query, resp.get("error"),
            )
            if attempt < max_retries:
                _time.sleep(attempt)
        return None

    # ------------------------------------------------------------------
    # Public data-fetch methods
    # ------------------------------------------------------------------

    def get_market_index(self, index_code: str = "VNINDEX") -> Dict[str, Any]:
        """Fetch the latest close for a market index (e.g. VNINDEX, VN30)."""
        code = index_code.upper()
        data = self._fetch_vndirect(f"code:{code}", size=1)
        if not data:
            return {"status": "error", "code": code, "error": f"Không lấy được dữ liệu {code}"}
        item = data[0]
        return {
            "status": "ok",
            "code": code,
            "date": item.get("date"),
            "close": item.get("close"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "nmVolume": item.get("nmVolume"),
            "nmValue": item.get("nmValue"),
            "pctChange": item.get("pctChange"),
            "change": item.get("change"),
        }

    def get_stock_price(self, ticker: str) -> Dict[str, Any]:
        """Fetch the latest end-of-day price for a specific HOSE stock ticker."""
        code = ticker.upper()
        data = self._fetch_vndirect(f"code:{code}", size=1)
        if not data:
            return {"status": "error", "code": code, "error": f"Không tìm thấy dữ liệu cho mã '{code}'"}
        item = data[0]
        return {
            "status": "ok",
            "code": code,
            "date": item.get("date"),
            "close": item.get("close"),
            "open": item.get("open"),
            "high": item.get("high"),
            "low": item.get("low"),
            "nmVolume": item.get("nmVolume"),
            "nmValue": item.get("nmValue"),
            "pctChange": item.get("pctChange"),
            "change": item.get("change"),
        }

    def get_snapshot(self, ticker: Optional[str] = None) -> Dict[str, Any]:
        """Return a combined snapshot: VN-Index + optional individual ticker."""
        now = self._now_hcm()
        snapshot: Dict[str, Any] = {
            "as_of": now.isoformat(),
            "index": None,
            "stock": None,
        }
        snapshot["index"] = self.get_market_index("VNINDEX")

        if ticker and ticker.upper() not in KNOWN_INDICES:
            snapshot["stock"] = self.get_stock_price(ticker)
        elif ticker and ticker.upper() in KNOWN_INDICES and ticker.upper() != "VNINDEX":
            # Support e.g. /stock VN30
            snapshot["index"] = self.get_market_index(ticker)

        return snapshot

    # ------------------------------------------------------------------
    # MongoDB helpers
    # ------------------------------------------------------------------

    def _last_stored_close(self, code: str):
        """Return the close price of the most recently stored record, or None."""
        if self.mongo_coll is None:
            return None
        try:
            doc = self.mongo_coll.find_one({"code": code}, sort=[("timestamp", DESCENDING)])
            return doc.get("close") if doc else None
        except Exception:
            logging.exception("HOSEStockService: failed reading last close for %s", code)
            return None

    def insert_if_changed(
        self,
        code: str,
        close_price,
        pct_change=None,
        date_str: Optional[str] = None,
    ) -> bool:
        """Persist a price record only when the close price differs from the last stored value.

        Returns ``True`` if a new document was inserted.
        """
        if self.mongo_coll is None or close_price is None:
            return False
        last = self._last_stored_close(code)
        if last is not None and last == close_price:
            logging.info("HOSEStockService: no price change for %s (%s), skipping insert", code, close_price)
            return False
        try:
            doc = {
                "timestamp": datetime.utcnow(),
                "code": code,
                "close": close_price,
                "pctChange": pct_change,
                "date": date_str or datetime.utcnow().strftime("%Y-%m-%d"),
            }
            self.mongo_coll.insert_one(doc)
            logging.info("HOSEStockService: stored %s close=%s pct=%s", code, close_price, pct_change)
            return True
        except Exception:
            logging.exception("HOSEStockService: error inserting price for %s", code)
            return False

    # ------------------------------------------------------------------
    # Formatted message methods (consumed by message.py / hose_watcher.py)
    # ------------------------------------------------------------------

    def get_info(self, ticker: Optional[str] = None) -> Dict[str, Any]:
        """Build a human-readable Telegram message with the latest market data.

        Parameters
        ----------
        ticker:
            Optional stock or index code (e.g. ``"VNM"``, ``"VN30"``).
            When ``None`` only the VN-Index is shown.

        Returns
        -------
        dict with keys:
            - ``message``       – formatted string ready to send via Telegram
            - ``data``          – raw snapshot dict
            - ``has_any_change``– always ``False`` in info mode
        """
        snapshot = self.get_snapshot(ticker)
        now = self._now_hcm()
        day_name = VN_DAYS.get(now.weekday(), "")
        date_header = f"{day_name} NGÀY {now.day:02d} THÁNG {now.month:02d} NĂM {now.year}"
        time_header = now.strftime("%I:%M:%S %p")

        lines: List[str] = [
            "THÔNG TIN THỊ TRƯỜNG CHỨNG KHOÁN HOSE",
            date_header,
            time_header,
            "",
        ]

        # ---- VN-Index (or requested index) ----
        idx = snapshot.get("index") or {}
        if idx.get("status") == "ok":
            self.insert_if_changed(
                idx["code"], idx.get("close"), idx.get("pctChange"), idx.get("date")
            )
            close_str = self._fmt_price(idx.get("close"))
            pct_str = self._pct_arrow(idx.get("pctChange"))
            change = idx.get("change")
            change_str = f" ({change:+.2f})" if change is not None else ""
            lines.append(f"{idx['code']}: {close_str} điểm{change_str}{pct_str}")
            if idx.get("nmVolume") is not None:
                lines.append(f"  Khối lượng: {self._fmt_volume(idx['nmVolume'])} CP")
            if idx.get("nmValue") is not None:
                lines.append(f"  Giá trị  : {self._fmt_value_billion(idx['nmValue'])}")
            if idx.get("date"):
                lines.append(f"  Phiên    : {idx['date']}")
        else:
            lines.append(f"VN-INDEX: {idx.get('error', 'Không có dữ liệu')}")
        lines.append("")

        # ---- Individual stock ----
        stk = snapshot.get("stock")
        if stk:
            if stk.get("status") == "ok":
                self.insert_if_changed(
                    stk["code"], stk.get("close"), stk.get("pctChange"), stk.get("date")
                )
                close_str = self._fmt_price(stk.get("close"), decimals=0)
                pct_str = self._pct_arrow(stk.get("pctChange"))
                change = stk.get("change")
                change_str = f" ({change:+.0f})" if change is not None else ""
                lines.append(f"Mã: {stk['code']}")
                lines.append(f"  Đóng cửa : {close_str} VNĐ{change_str}{pct_str}")
                if stk.get("open") is not None:
                    lines.append(f"  Mở cửa   : {self._fmt_price(stk['open'], decimals=0)} VNĐ")
                if stk.get("high") is not None:
                    lines.append(f"  Cao nhất : {self._fmt_price(stk['high'], decimals=0)} VNĐ")
                if stk.get("low") is not None:
                    lines.append(f"  Thấp nhất: {self._fmt_price(stk['low'], decimals=0)} VNĐ")
                if stk.get("nmVolume") is not None:
                    lines.append(f"  Khối lượng: {self._fmt_volume(stk['nmVolume'])} CP")
                if stk.get("date"):
                    lines.append(f"  Phiên    : {stk['date']}")
            else:
                lines.append(stk.get("error", "Không có dữ liệu cho mã yêu cầu"))
            lines.append("")

        lines.append("Nguồn: VNDirect")

        return {
            "message": "\n".join(lines),
            "data": snapshot,
            "has_any_change": False,
        }

    def get_changes(self, threshold_pct: float = 0.5) -> Dict[str, Any]:
        """Detect and report a significant VN-Index move since the last stored close.

        An alert is raised only when ``|pctChange| >= threshold_pct``.

        Parameters
        ----------
        threshold_pct:
            Minimum absolute percentage move to trigger an alert (default 0.5 %).

        Returns
        -------
        dict with keys:
            - ``message``        – formatted alert string, or ``None`` if no alert
            - ``data``           – raw index dict
            - ``has_any_change`` – ``True`` when an alert is generated
            - ``total_changes``  – 1 if alert generated, else 0
        """
        now = self._now_hcm()
        day_name = VN_DAYS.get(now.weekday(), "")
        date_header = f"{day_name} NGÀY {now.day:02d} THÁNG {now.month:02d} NĂM {now.year}"
        time_header = now.strftime("%I:%M:%S %p")

        idx = self.get_market_index("VNINDEX")
        has_change = False
        message = None

        if idx.get("status") == "ok":
            close = idx.get("close")
            pct = idx.get("pctChange")
            last_close = self._last_stored_close("VNINDEX")

            price_changed = last_close is None or last_close != close

            significant = False
            if pct is not None and price_changed:
                try:
                    significant = abs(float(pct)) >= threshold_pct
                except Exception:
                    significant = price_changed

            if price_changed and significant:
                has_change = True
                self.insert_if_changed("VNINDEX", close, pct, idx.get("date"))

                pct_str = self._pct_arrow(pct)
                change = idx.get("change")
                change_str = f" ({change:+.2f})" if change is not None else ""
                lines: List[str] = [
                    "THAY ĐỔI THỊ TRƯỜNG HOSE",
                    date_header,
                    time_header,
                    "",
                    f"VN-INDEX: {self._fmt_price(close)} điểm{change_str}{pct_str}",
                    "",
                    "Nguồn: VNDirect",
                ]
                message = "\n".join(lines)

        return {
            "message": message,
            "data": idx,
            "has_any_change": has_change,
            "total_changes": 1 if has_change else 0,
        }


__all__ = ["HOSEStockService", "HOSE_STOCK_COLLECTION", "KNOWN_INDICES"]
