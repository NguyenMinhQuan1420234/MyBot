"""
Eximbank exchange rate service.

Fetches currency exchange rates from the Eximbank public API:
  GET https://eximbank.com.vn/api/front/v1/exchange-rate
      ?strQuoteCNT=12&strNoticeday=YYYYMMDD&strBRCD=1000

Usage:
    from api_client import APIClient
    from eximbank_exchange_rate import EximbankExchangeRateService

    service = EximbankExchangeRateService(APIClient(verify=False))
    result = service.get_rate('USD')
"""

import logging
from typing import Any, Dict, List, Optional, Union


_BASE_URL = "https://eximbank.com.vn/api/front/v1/exchange-rate"

_HEADERS = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9,vi;q=0.8",
    "Connection": "keep-alive",
    "Content-Type": "application/json",
    "Referer": "https://eximbank.com.vn/bang-ty-gia",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/145.0.0.0 Safari/537.36"
    ),
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
}


class EximbankExchangeRateService:
    def __init__(self, api_client, branch_code: str = "1000"):
        self.api_client = api_client
        self.branch_code = branch_code

    def get_rate(
        self, code: Union[str, List[str], None] = None
    ) -> Union[Dict[str, Any], List[Any], str]:
        """Return exchange rate info for one or more currency codes.

        *code* can be:
        - None / omitted  → returns both USD and JPY (default)
        - a string        → returns a single dict (or error string)
        - a list          → returns a list of dicts/error strings, one per code

        Each successful dict has keys: name, code, buy_cash, sell_cash,
        buy_transfer, sell_transfer.
        """
        if code is None:
            codes: List[str] = ["usd", "jpy"]
        elif isinstance(code, list):
            codes = [c.strip().lower() for c in code]
        else:
            codes = [code.strip().lower()]
        single = len(codes) == 1
        params = {
            "strBRCD": "1000",
        }
        try:
            resp = self.api_client.get(
                _BASE_URL,
                params=params,
                headers=_HEADERS,
                timeout=10,
                verify=False,
            )
        except Exception as exc:
            logging.error("EximbankExchangeRateService: request failed: %s", exc)
            return f"Lỗi khi gọi API tỷ giá Eximbank: {exc}"

        if not resp.get("ok"):
            return f"Lỗi khi lấy dữ liệu tỷ giá Eximbank: {resp.get('error')}"

        parsed = resp.get("json")
        if parsed is None:
            return "Không nhận được dữ liệu hợp lệ từ API Eximbank."

        results = [self._find_currency(parsed, c) for c in codes]
        return results[0] if single else results

    def _find_currency(self, data: Any, code: str) -> Dict[str, Any] | str:
        code_norm = (code or "usd").strip().lower()

        # Top-level list or wrapped in "data" key
        items = data if isinstance(data, list) else (
            data.get("data") if isinstance(data, dict) else None
        )
        if not isinstance(items, list):
            return "Cấu trúc phản hồi từ Eximbank không như mong đợi."

        for itm in items:
            if not isinstance(itm, dict):
                continue
            itm_code = str(itm.get("CCYCD") or "").strip().lower()
            if itm_code != code_norm:
                continue

            return {
                "name": str(itm.get("Cur_NameVN") or itm.get("Cur_NameEN") or itm_code.upper()),
                "code": itm_code.upper(),
                "buy_cash": str(itm.get("CSHBUYRT") or ""),
                "sell_cash": str(itm.get("CSHSELLRT") or ""),
                "buy_transfer": str(itm.get("TTBUYRT") or ""),
                "sell_transfer": str(itm.get("TTSELLRT") or ""),
                "buy_cash_diff": str(itm.get("CSHBUYRT_DIFF") or ""),
                "sell_cash_diff": str(itm.get("CSHSELLRT_DIFF") or ""),
                "buy_transfer_diff": str(itm.get("TTBUYRT_DIFF") or ""),
                "sell_transfer_diff": str(itm.get("TTSELLRT_DIFF") or ""),
                "quote_time": str(itm.get("QUOTETM") or ""),
            }

        return f"Không tìm thấy thông tin cho mã tiền tệ '{code.upper()}'."
