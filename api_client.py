"""
Simple API client wrapper that provides GET, POST, PUT, PATCH using
requests when available and falling back to urllib when not.

Each method returns a dictionary with keys:
- ok (bool)
- status_code (int or None)
- headers (dict-like) or {}
- text (raw response text)
- json (parsed JSON or None)
- error (exception string on failure)

Designed to be safe to import and use from `agent.py`.
"""
from typing import Optional, Any, Dict
import json
import ssl
try:
    import requests
except Exception:
    requests = None
import urllib.request
import urllib.parse
import urllib.error


class APIClient:
    def __init__(self, verify: bool = True, default_headers: Optional[Dict[str, str]] = None):
        self.verify = verify
        self.default_headers = default_headers or {}

    def _build_headers(self, headers: Optional[Dict[str, str]]):
        h = dict(self.default_headers)
        if headers:
            h.update(headers)
        return h

    def get(self, url: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None,
            timeout: int = 10, verify: Optional[bool] = None):
        if params:
            qs = urllib.parse.urlencode(params)
            url = f"{url}?{qs}"
        return self._request('GET', url, None, headers, timeout, verify)

    def post(self, url: str, data: Optional[Any] = None, json_body: Optional[Any] = None,
             headers: Optional[Dict[str, str]] = None, timeout: int = 10, verify: Optional[bool] = None):
        payload = json_body if json_body is not None else data
        return self._request('POST', url, payload, headers, timeout, verify)

    def put(self, url: str, data: Optional[Any] = None, json_body: Optional[Any] = None,
            headers: Optional[Dict[str, str]] = None, timeout: int = 10, verify: Optional[bool] = None):
        payload = json_body if json_body is not None else data
        return self._request('PUT', url, payload, headers, timeout, verify)

    def patch(self, url: str, data: Optional[Any] = None, json_body: Optional[Any] = None,
              headers: Optional[Dict[str, str]] = None, timeout: int = 10, verify: Optional[bool] = None):
        payload = json_body if json_body is not None else data
        return self._request('PATCH', url, payload, headers, timeout, verify)

    def _request(self, method: str, url: str, payload: Optional[Any], headers: Optional[Dict[str, str]],
                 timeout: int, verify: Optional[bool]):
        hdrs = self._build_headers(headers)
        verify_final = self.verify if verify is None else bool(verify)

        if requests:
            try:
                # requests will handle JSON if json= is provided
                req_kwargs = dict(method=method, url=url, headers=hdrs, timeout=timeout)
                if isinstance(payload, (dict, list)):
                    req_kwargs['json'] = payload
                elif payload is not None:
                    # send raw payload as data
                    req_kwargs['data'] = payload
                req_kwargs['verify'] = verify_final
                r = requests.request(**req_kwargs)
                try:
                    parsed = r.json()
                except Exception:
                    parsed = None
                return {
                    'ok': r.ok,
                    'status_code': r.status_code,
                    'headers': dict(r.headers) if r.headers is not None else {},
                    'text': r.text,
                    'json': parsed,
                    'error': None
                }
            except Exception as e:
                return {'ok': False, 'status_code': None, 'headers': {}, 'text': '', 'json': None, 'error': str(e)}

        # Fallback: urllib
        try:
            data_bytes = None
            if payload is not None:
                if isinstance(payload, (dict, list)):
                    if 'Content-Type' not in hdrs:
                        hdrs['Content-Type'] = 'application/json'
                    data_bytes = json.dumps(payload).encode('utf-8')
                elif isinstance(payload, str):
                    data_bytes = payload.encode('utf-8')
                elif isinstance(payload, bytes):
                    data_bytes = payload
                else:
                    # try to stringify
                    data_bytes = str(payload).encode('utf-8')

            req = urllib.request.Request(url, data=data_bytes, headers=hdrs, method=method)
            ctx = None if verify_final else ssl._create_unverified_context()
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
                raw = resp.read()
                try:
                    text = raw.decode('utf-8')
                except Exception:
                    text = raw.decode('latin-1', errors='ignore')
                resp_headers = dict(resp.getheaders()) if hasattr(resp, 'getheaders') else {}
                parsed = None
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = None
                return {'ok': True, 'status_code': getattr(resp, 'status', None) or None,
                        'headers': resp_headers, 'text': text, 'json': parsed, 'error': None}
        except urllib.error.HTTPError as he:
            try:
                body = he.read().decode('utf-8', errors='ignore')
            except Exception:
                body = ''
            return {'ok': False, 'status_code': he.code, 'headers': {}, 'text': body, 'json': None, 'error': str(he)}
        except Exception as e:
            return {'ok': False, 'status_code': None, 'headers': {}, 'text': '', 'json': None, 'error': str(e)}
