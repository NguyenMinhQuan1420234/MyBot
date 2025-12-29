import logging
import json
import xml.etree.ElementTree as ET
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
        """Shorter implementation: use APIClient for HTTP and keep concise parsing/formatting."""
        url = "https://mihong.vn/api/v1/gold/prices/current"
        headers = {
            'x-requested-with': 'XMLHttpRequest',
            'referer': 'https://mihong.vn/vi/gia-vang-trong-nuoc',
            'Cookie': 'laravel_session=BjzTy5xwYchpU94uwsemKJZ4L5dqrLQ01iEgogfx'
        }
        # Retry logic: attempt up to 5 times with incremental backoff
        max_retries = 5
        resp = None
        for attempt in range(1, max_retries + 1):
            resp = self.api_client.get(url, headers=headers, timeout=10, verify=False)
            if resp.get('ok'):
                break
            logging.warning("Gold API request failed (attempt %d/%d): %s", attempt, max_retries, resp.get('error'))
            if attempt < max_retries:
                # simple backoff: sleep 1s, 2s, 3s, ...
                time.sleep(attempt)
        else:
            # all attempts failed
            err = resp.get('error') if resp is not None else 'unknown error'
            return f"Error fetching gold price after {max_retries} attempts: {err}"

        text = resp.get('text', '')
        parsed = resp.get('json')

        def fmt_price(val):
            if val is None:
                return 'N/A'
            try:
                num = float(str(val).replace(',', '').strip())
                return f"{int(round(num)):,}"
            except Exception:
                return str(val)

        # Prefer JSON structured response
        if isinstance(parsed, dict) and 'data' in parsed:
            data = parsed.get('data') or []
            # normalize to list
            if isinstance(data, dict):
                items = [v for v in (x for x in data.values()) if isinstance(v, dict) or isinstance(v, list)]
                # flatten lists
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
                out.append(f"Giá của vàng {code} ngày {dt}:\n  - Giá mua: {fmt_price(buying)}\n  - Giá bán: {fmt_price(selling)}\n")
            return "\n".join(out) if out else "Không tìm thấy dữ liệu giá vàng phù hợp."

        # Try XML fallback
        try:
            root = ET.fromstring(text)
            def elem_to_dict(e):
                if not list(e) and (e.text is None or not e.text.strip()) and not e.attrib:
                    return None
                d = {}
                for k, v in e.attrib.items():
                    d[f"@{k}"] = v
                children = list(e)
                if children:
                    for c in children:
                        val = elem_to_dict(c)
                        if val is None:
                            continue
                        if c.tag in d:
                            if isinstance(d[c.tag], list):
                                d[c.tag].append(val)
                            else:
                                d[c.tag] = [d[c.tag], val]
                        else:
                            d[c.tag] = val
                text_val = e.text.strip() if e.text and e.text.strip() else None
                if text_val:
                    if d:
                        d['#text'] = text_val
                    else:
                        return text_val
                return d
            xml_parsed = elem_to_dict(root)
            return xml_parsed
        except Exception:
            pass

        # Fallback: return raw text
        return text
