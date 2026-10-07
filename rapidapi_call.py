"""
rapidapi_call — вызов ПОДПИСАННОГО API через официальный прокси RapidAPI (без UI).

Это стабильный документированный контракт (в отличие от внутреннего GraphQL поиска):
после subscribe на тариф ты получаешь один ключ X-RapidAPI-Key и дёргаешь хост
<host>.p.rapidapi.com. Хост берётся из блока "Code Snippets" на странице API.

Ключ читается (в порядке приоритета):
  1) аргумент key=...
  2) переменная окружения RAPIDAPI_KEY
  3) файл keys.json  -> {"key": "..."} или {"<host>": "ключ-для-этого-хоста"}
"""

from __future__ import annotations

import json
import os
import re
from typing import Optional

import requests

from rapidapi_hub import _normalize_curl_text, _find_headers, _find_flag_value


def load_key(host: Optional[str] = None, key: Optional[str] = None,
             keys_file: str = "keys.json") -> str:
    if key:
        return key
    env = os.environ.get("RAPIDAPI_KEY")
    if env:
        return env
    if os.path.exists(keys_file):
        with open(keys_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if host and host in data:
            return data[host]
        if "key" in data:
            return data["key"]
    raise RuntimeError(
        "Не найден X-RapidAPI-Key. Задай его через --key, переменную RAPIDAPI_KEY "
        "или файл keys.json ({\"key\": \"...\"})."
    )


def call(host: str, path: str, *, method: str = "GET",
         params: Optional[dict] = None, json_body: Optional[dict] = None,
         key: Optional[str] = None, timeout: int = 30) -> requests.Response:
    """Вызвать эндпоинт подписанного API.

    host — например 'youtube138.p.rapidapi.com'
    path — например '/search' или '/v1/videos'
    """
    api_key = load_key(host=host, key=key)
    url = f"https://{host}{path if path.startswith('/') else '/' + path}"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": host,
        "Accept": "application/json",
    }
    return requests.request(method.upper(), url, headers=headers,
                            params=params, json=json_body, timeout=timeout)


def replay_curl(path: str, key_override: Optional[str] = None,
                timeout: int = 30) -> requests.Response:
    """Воспроизвести cURL эндпоинта API, скопированный со страницы RapidAPI (или из DevTools).

    Берёт из cURL URL, метод, заголовки (в т.ч. X-RapidAPI-Key/Host) и тело — и повторяет запрос
    как есть. Это «подключить и вызвать в одну вставку»: скопировал cURL эндпоинта -> сюда.
    """
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        text = _normalize_curl_text(fh.read())

    urls = re.findall(r"https?://[^\s\"'\\]+", text)
    target = next((u for u in urls if "p.rapidapi.com" in u), urls[0] if urls else None)
    if not target:
        raise RuntimeError("В cURL не найден URL эндпоинта (https://<host>.p.rapidapi.com/...).")

    headers = {k: v for k, v in _find_headers(text).items()}
    # нормализуем имена ключевых заголовков к каноничным
    canon = {}
    for k, v in headers.items():
        if k == "x-rapidapi-key":
            canon["X-RapidAPI-Key"] = v
        elif k == "x-rapidapi-host":
            canon["X-RapidAPI-Host"] = v
        else:
            canon[k] = v
    if key_override:
        canon["X-RapidAPI-Key"] = key_override

    body = _find_flag_value(r"--data-raw|--data-binary|--data|-d", text)
    method = _find_flag_value(r"-X|--request", text) or ("POST" if body else "GET")

    return requests.request(method.upper(), target, headers=canon,
                            data=body.encode("utf-8") if body else None, timeout=timeout)


def snippet(host: str, path: str, *, method: str = "GET",
            params: Optional[dict] = None, lang: str = "python") -> str:
    """Сгенерировать готовый код вызова (для вставки в свой проект)."""
    path = path if path.startswith("/") else "/" + path
    if lang == "python":
        q = f", params={params!r}" if params else ""
        return (
            "import requests\n\n"
            f'url = "https://{host}{path}"\n'
            'headers = {\n'
            '    "X-RapidAPI-Key": "<YOUR_KEY>",\n'
            f'    "X-RapidAPI-Host": "{host}",\n'
            "}\n"
            f'resp = requests.request("{method.upper()}", url, headers=headers{q})\n'
            "print(resp.json())\n"
        )
    if lang == "curl":
        qs = ""
        if params:
            qs = "?" + "&".join(f"{k}={v}" for k, v in params.items())
        return (
            f'curl "https://{host}{path}{qs}" \\\n'
            f'  -H "X-RapidAPI-Key: <YOUR_KEY>" \\\n'
            f'  -H "X-RapidAPI-Host: {host}"\n'
        )
    raise ValueError(f"lang должен быть python|curl, а не {lang!r}")
