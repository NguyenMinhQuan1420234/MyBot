import logging
import json
import xml.etree.ElementTree as ET
from mcp_playwright_agent import MCPPlaywrightAgent

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
        """Fetch gold price from SJC public API.

        Returns parsed JSON or XML as Python objects when possible,
        otherwise returns the raw response text. On error returns a
        descriptive string.
        """
        url = "https://mihong.vn/api/v1/gold/prices/current"
        headers = {
            'x-requested-with': 'XMLHttpRequest',
            'referer': 'https://mihong.vn/vi/gia-vang-trong-nuoc',
            'Cookie': 'laravel_session=BjzTy5xwYchpU94uwsemKJZ4L5dqrLQ01iEgogfx'
        }
        try:
            if requests:
                # disable SSL verification per user request
                resp = requests.get(url, timeout=10, headers=headers, verify=False)
                resp.raise_for_status()
                text = resp.text
                content_type = resp.headers.get("Content-Type", "")
            else:
                req = urllib.request.Request(url, headers=headers)
                # create an unverified SSL context to skip cert verification
                ctx = ssl._create_unverified_context()
                with urllib.request.urlopen(req, timeout=10, context=ctx) as r:
                    content_type = r.getheader("Content-Type", "")
                    text = r.read().decode("utf-8")

            # Try JSON and filter to only the `data` field with selected keys
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict) and 'data' in parsed:
                    data = parsed.get('data') or []
                    # Normalize to list of items
                    if isinstance(data, dict):
                        items = []
                        for v in data.values():
                            if isinstance(v, list):
                                items.extend(v)
                            elif isinstance(v, dict):
                                items.append(v)
                        # if nothing collected, treat the dict itself as one item
                        if not items:
                            items = [data]
                    else:
                        items = data

                    # Filter by `code` and map price fields to Buy/Sell
                    allowed_codes = {"SJC", "999"}
                    formatted_items = []
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        code = (item.get('code') or item.get('Code') or '').strip()
                        if code not in allowed_codes:
                            continue
                        # Extract prices and datetime with fallbacks
                        buying = item.get('buyingPrice') if 'buyingPrice' in item else item.get('Buy') if 'Buy' in item else item.get('buy')
                        selling = item.get('sellingPrice') if 'sellingPrice' in item else item.get('Sell') if 'Sell' in item else item.get('sell')
                        dt = item.get('dateTime') or item.get('date_time') or item.get('date') or ''
                        # Safe formatting with thousands separators
                        def format_price(val):
                            if val is None:
                                return 'N/A'
                            try:
                                num = float(val)
                                return f"{int(round(num)):,}"
                            except Exception:
                                # try to parse integers from strings with commas
                                try:
                                    cleaned = str(val).replace(',', '').strip()
                                    num = float(cleaned)
                                    return f"{int(round(num)):,}"
                                except Exception:
                                    return str(val)

                        b_str = format_price(buying)
                        s_str = format_price(selling)
                        dt_str = str(dt)
                        formatted = f"Giá của vàng {code} ngày {dt_str}:\n  - Giá mua: {b_str}\n  - Giá bán: {s_str}\n"
                        formatted_items.append(formatted)

                    if not formatted_items:
                        return "Không tìm thấy dữ liệu giá vàng phù hợp."
                    # Join multiple entries with a blank line
                    return "\n".join(formatted_items)
                return parsed
            except Exception:
                pass

            # Try XML
            try:
                root = ET.fromstring(text)

                def elem_to_dict(e):
                    d = {}
                    if e.attrib:
                        d.update({f"@{k}": v for k, v in e.attrib.items()})
                    children = list(e)
                    if children:
                        for c in children:
                            tag = c.tag
                            val = elem_to_dict(c)
                            if tag in d:
                                if isinstance(d[tag], list):
                                    d[tag].append(val)
                                else:
                                    d[tag] = [d[tag], val]
                            else:
                                d[tag] = val
                    text_val = e.text.strip() if e.text and e.text.strip() else None
                    if text_val and not children and not e.attrib:
                        return text_val
                    if text_val:
                        d["#text"] = text_val
                    return d

                return elem_to_dict(root)
            except Exception:
                pass

            # Fallback: return raw text
            return text
        except Exception as e:
            logging.exception("Failed to fetch gold price")
            return f"Error fetching gold price: {e}"
