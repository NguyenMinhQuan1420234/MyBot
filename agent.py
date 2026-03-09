import logging
import json
import xml.etree.ElementTree as ET
import re
from typing import Any, Dict, List, Optional, Protocol
from mcp_playwright_agent import MCPPlaywrightAgent
from api_client import APIClient
from crawl_gold_price import GoldPriceService

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
try:
    import anthropic
except ImportError:
    anthropic = None


class Agent:
    def __init__(self, provider, api_key, **kwargs):
        self.provider = provider.lower()
        self.api_key = api_key
        self.kwargs = kwargs
        self.mcp_agent = MCPPlaywrightAgent()
        # initialize a reusable API client (disable SSL verification for legacy endpoints)
        self.api_client = APIClient(verify=False)
        # initialize gold price service with optional MongoDB URI for change computation
        mongo_uri = kwargs.get('mongo_uri')
        self.gold_service = GoldPriceService(self.api_client, mongo_uri=mongo_uri)

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
        elif self.provider == "claude" and anthropic:
            self.claude_client = anthropic.Anthropic(api_key=api_key)
            self.claude_model = kwargs.get('model', 'claude-opus-4-5')
            self.claude_tools = self._build_claude_tools()
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
        elif self.provider == "claude" and anthropic:
            result = self._ask_claude(prompt, system_prompt)
        else:
            result = "AI provider not available or not configured."
        logging.info(f"AI Response ({self.provider}): {result}")
        return result

    def _build_claude_tools(self) -> List[Dict]:
        """Define Claude Skills (tools) available to the Claude AI model."""
        return [
            {
                "name": "get_gold_price",
                "description": (
                    "Lấy giá vàng hiện tại từ các nguồn uy tín tại Việt Nam "
                    "(Mi Hồng, Doji, Ngọc Thẩm). Trả về bảng giá vàng mua/bán chi tiết."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "get_money_rate",
                "description": (
                    "Lấy tỷ giá ngoại tệ so với VND. "
                    "Trả về giá mua và bán của đơn vị tiền tệ được chỉ định."
                ),
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "code": {
                            "type": "string",
                            "description": "Mã tiền tệ ISO 4217 (ví dụ: USD, EUR, JPY, GBP, ...)"
                        }
                    },
                    "required": ["code"]
                }
            }
        ]

    def _execute_claude_tool(self, tool_name: str, tool_input: Dict) -> str:
        """Execute a Claude skill (tool) by name and return its result as a string."""
        if tool_name == "get_gold_price":
            result = self.get_gold_price()
            return json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else str(result)
        elif tool_name == "get_money_rate":
            code = tool_input.get("code", "USD")
            result = self.get_money_rate(code)
            return json.dumps(result, ensure_ascii=False, indent=2) if isinstance(result, dict) else str(result)
        return f"Unknown skill: {tool_name}"

    def _ask_claude(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """Send a prompt to Claude with Skills (tool use) support and return the response."""
        messages = [{"role": "user", "content": prompt}]
        sys = system_prompt or "You are a helpful assistant."

        while True:
            response = self.claude_client.messages.create(
                model=self.claude_model,
                max_tokens=8192,
                system=sys,
                tools=self.claude_tools,
                messages=messages,
            )

            if response.stop_reason == "tool_use":
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        logging.info(f"Claude skill call: {block.name}({block.input})")
                        tool_output = self._execute_claude_tool(block.name, block.input)
                        logging.info(f"Claude skill result for {block.name}: {tool_output[:200]}")
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": tool_output,
                        })
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                text_parts = [block.text for block in response.content if hasattr(block, "text")]
                return "".join(text_parts) or "Không có phản hồi từ Claude."

    def run_playwright(self, command):
        logging.info(f"Playwright Command: {command}")
        return self.mcp_agent.run_command(command)

    def get_gold_price(self):
        return self.gold_service.get_snapshot()

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
