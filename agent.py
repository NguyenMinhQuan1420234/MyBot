import logging
import json
import xml.etree.ElementTree as ET
import re
from mcp_playwright_agent import MCPPlaywrightAgent
from api_client import APIClient

# Prefer requests if available, fall back to urllib
try:
    import requests
except ImportError:
    requests = None
import ssl
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    urllib3 = None
import urllib.request
import urllib.error
import time

# Optional imports for AI providers
try:
    import google.generativeai as genai
except ImportError:
    genai = None
try:
    from xai_sdk import Client as xai_Client
    from xai_sdk.chat import user as xai_user, system as xai_system
except ImportError:
    xai_Client = None
try:
    import openai
except ImportError:
    openai = None
# Azure OpenAI can use openai with endpoint config

class Agent:
    def __init__(self, provider, api_key, **kwargs):
        self.provider = provider.lower()
        self.api_key = api_key
        self.kwargs = kwargs
        self.mcp_agent = MCPPlaywrightAgent()
        # initialize a reusable API client (disable SSL verification for legacy endpoints)
        self.api_client = APIClient(verify=False)

        if self.provider == "gemini" and genai:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(kwargs.get('model', 'models/gemini-2.5-flash'))
        elif self.provider == "xai" and xai_Client:
            self.xai_client = xai_Client(api_key=api_key)
            self.xai_model = kwargs.get('model', 'grok-4-0709')
            self.xai_temperature = kwargs.get('temperature', 0)
        elif self.provider == "openai" and openai:
            openai.api_key = api_key
            self.openai_model = kwargs.get('model', 'gpt-3.5-turbo')
        elif self.provider == "azure":
            # Azure OpenAI setup
            openai.api_key = api_key
            openai.api_base = kwargs.get('api_base')
            openai.api_type = "azure"
            openai.api_version = kwargs.get('api_version', '2023-05-15')
            self.azure_deployment = kwargs.get('deployment', 'gpt-35-turbo')
        else:
            raise ValueError(f"Unsupported provider or missing package: {provider}")

    def ask(self, prompt, system_prompt=None):
        logging.info(f"AI Request ({self.provider}): {prompt}")
        if self.provider == "gemini" and genai:
            response = self.model.generate_content(prompt)
            result = response.text if hasattr(response, 'text') else str(response)
        elif self.provider == "xai" and xai_Client:
            chat = self.xai_client.chat.create(model=self.xai_model, temperature=self.xai_temperature)
            if system_prompt:
                chat.append(xai_system(system_prompt))
            chat.append(xai_user(prompt))
            response = chat.sample()
            result = response.content
        elif self.provider == "openai" and openai:
            completion = openai.ChatCompletion.create(
                model=self.openai_model,
                messages=[{"role": "system", "content": system_prompt or "You are a helpful assistant."},
                          {"role": "user", "content": prompt}]
            )
            result = completion.choices[0].message.content
        elif self.provider == "azure" and openai:
            completion = openai.ChatCompletion.create(
                engine=self.azure_deployment,
                messages=[{"role": "system", "content": system_prompt or "You are a helpful assistant."},
                          {"role": "user", "content": prompt}]
            )
            result = completion.choices[0].message.content
        else:
            result = "AI provider not available or not configured."
        logging.info(f"AI Response ({self.provider}): {result}")
        return result

    def run_playwright(self, command):
        logging.info(f"Playwright Command: {command}")
        return self.mcp_agent.run_command(command)

    def get_gold_price(self):
        # Delegate to provider-specific helpers and combine their outputs
        mi_hong_text = self._fetch_mihong_prices()
        doji_text = self._fetch_doji_prices()
        
        # Add signature line
        return f"Giá vàng Mi Hồng:\n{mi_hong_text}\n\nGiá vàng Doji:\n{doji_text}\n\nTrao niềm tin nhận tài lộc."

    def _fetch_mihong_prices(self):
        url = "https://mihong.vn/api/v1/gold/prices/current"
        headers = {
            'x-requested-with': 'XMLHttpRequest',
            'referer': 'https://mihong.vn/vi/gia-vang-trong-nuoc',
            'Cookie': 'laravel_session=BjzTy5xwYchpU94uwsemKJZ4L5dqrLQ01iEgogfx'
        }
        max_retries = 5
        resp = None
        for attempt in range(1, max_retries + 1):
            resp = self.api_client.get(url, headers=headers, timeout=10, verify=False)
            if resp.get('ok'):
                break
            logging.warning("Mi Hồng API request failed (attempt %d/%d): %s", attempt, max_retries, resp.get('error'))
            if attempt < max_retries:
                time.sleep(attempt)
        else:
            return "Không lấy được giá vàng Mi Hồng."

        parsed = resp.get('json')
        text = resp.get('text', '')

        def fmt_price(val):
            if val is None:
                return 'N/A'
            try:
                num = float(str(val).replace(',', '').strip())
                return f"{int(round(num)):,}"
            except Exception:
                return str(val)

        if isinstance(parsed, dict) and 'data' in parsed:
            data = parsed.get('data') or []
            if isinstance(data, dict):
                items = [v for v in (x for x in data.values()) if isinstance(v, dict) or isinstance(v, list)]
                flat = []
                for it in items:
                    if isinstance(it, list):
                        flat.extend([x for x in it if isinstance(x, dict)])
                    elif isinstance(it, dict):
                        flat.append(it)
                if not flat:
                    flat = [data]
                items = flat
            else:
                items = data

            allowed = {"SJC", "999"}
            out = []
            for item in items:
                if not isinstance(item, dict):
                    continue
                code = (item.get('code') or item.get('Code') or '').strip()
                if code not in allowed:
                    continue
                buying = item.get('buyingPrice') or item.get('Buy') or item.get('buy')
                selling = item.get('sellingPrice') or item.get('Sell') or item.get('sell')
                dt = item.get('dateTime') or item.get('date_time') or item.get('date') or ''
                out.append(f"- {code} (ngày {dt}):\n  - Giá mua: {fmt_price(buying)}\n  - Giá bán: {fmt_price(selling)}")
            return "\n".join(out) if out else "Không tìm thấy dữ liệu giá vàng phù hợp."
        return "Không tìm thấy dữ liệu giá vàng phù hợp."

    def _fetch_doji_prices(self):
        doji_url = "https://giavang.doji.vn/sites/default/files/data/hienthi/vungmien_109.dat"
        try:
            resp2 = self.api_client.get(doji_url, timeout=10, verify=False)
        except Exception as e:
            return f"Lỗi khi lấy Doji: {e}"

        if not resp2.get('ok'):
            return f"Lỗi khi lấy Doji: {resp2.get('error')}"

        raw = (resp2.get('text') or '')
        if not raw.strip():
            return "Không có dữ liệu từ Doji."

        try:
            rows = re.findall(r'<tr[^>]*>.*?</tr>', raw, flags=re.S | re.I)
            targets = [
                "SJC - Bán Lẻ",
                "Nhẫn Tròn 9999 Hưng Thịnh Vượng - Bán Lẻ",
            ]
            found = []
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
                    found.append(f"- {label}:\n  - Giá mua: {buy}\n  - Giá bán: {sell}")
            return "\n".join(found) if found else "Không tìm thấy mục Doji phù hợp."
        except Exception as e:
            return f"Lỗi phân tích Doji: {e}"

    def get_money_rate(self, code='usd'):
        """Fetch fiat exchange info from external API and return formatted result.

        The API returns a JSON payload; we try to find the requested currency code
        (case-insensitive). If not found, return a helpful message.
        """
        url = "https://exchange.goonus.io/exchange/api/v1/fiat"
        try:
            resp = self.api_client.get(url, timeout=10, verify=False)
        except Exception as e:
            return f"Lỗi khi gọi API tiền tệ: {e}"

        if not resp.get('ok'):
            return f"Lỗi khi lấy dữ liệu tiền tệ: {resp.get('error')}"
        parsed = resp.get('json')
        text = resp.get('text') or ''

        code_norm = (code or 'usd').strip().lower()

        # Expected sample shape: {"data": [ {"name": "Đô la Mỹ", "code": "USD", "buy": "26061.00", "sell": "26381.00", ... } ] }
        if isinstance(parsed, dict) and 'data' in parsed and isinstance(parsed['data'], list):
            items = parsed['data']
            for itm in items:
                if not isinstance(itm, dict):
                    continue
                itm_code = str(itm.get('code') or '').strip().lower()
                if itm_code == code_norm:
                    name = itm.get('name') or itm.get('code') or code.upper()
                    buy = itm.get('buy') or ''
                    sell = itm.get('sell') or ''
                    return {
                        'name': str(name),
                        'code': str(itm_code).upper(),
                        'buy': str(buy),
                        'sell': str(sell),
                    }
            return f"Không tìm thấy thông tin cho mã tiền tệ '{code}'."

        # fallback: try to parse text as JSON and repeat
        try:
            j = json.loads(text)
            if isinstance(j, dict) and 'data' in j and isinstance(j['data'], list):
                for itm in j['data']:
                    if not isinstance(itm, dict):
                        continue
                    itm_code = str(itm.get('code') or '').strip().lower()
                    if itm_code == code_norm:
                        name = itm.get('name') or itm.get('code') or code.upper()
                        buy = itm.get('buy') or ''
                        sell = itm.get('sell') or ''
                        return {
                            'name': str(name),
                            'code': str(itm_code).upper(),
                            'buy': str(buy),
                            'sell': str(sell),
                        }
        except Exception:
            pass

        return "Không nhận được dữ liệu hợp lệ từ API tiền tệ."
