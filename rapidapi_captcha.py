"""
rapidapi_captcha — решение reCAPTCHA через Anti-Captcha (https://anti-captcha.com/).

Нужно для авто-подписки: мутация createApiSubscription требует recaptchaToken (reCAPTCHA v3),
который обычно выпускается только браузером. Anti-Captcha решает его за деньги с баланса.

Ключ берётся: аргумент -> env ANTICAPTCHA_API_KEY -> secrets.json {"anticaptcha_api_key": "..."}.
"""

from __future__ import annotations

import json
import os
import time
from typing import Optional

import requests

API = "https://api.anti-captcha.com"


def load_key(key: Optional[str] = None, secrets_file: str = "secrets.json") -> str:
    if key:
        return key
    env = os.environ.get("ANTICAPTCHA_API_KEY")
    if env:
        return env
    if os.path.exists(secrets_file):
        with open(secrets_file, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("anticaptcha_api_key"):
            return data["anticaptcha_api_key"]
    raise RuntimeError("Не найден ключ Anti-Captcha (ANTICAPTCHA_API_KEY или secrets.json).")


def balance(key: Optional[str] = None) -> float:
    r = requests.post(f"{API}/getBalance", json={"clientKey": load_key(key)}, timeout=30)
    data = r.json()
    if data.get("errorId"):
        raise RuntimeError(f"Anti-Captcha error: {data.get('errorCode')} {data.get('errorDescription')}")
    return data.get("balance")


def solve_recaptcha_v3(website_url: str, website_key: str, *, page_action: str = "",
                       min_score: float = 0.3, is_enterprise: bool = False,
                       key: Optional[str] = None, timeout_s: int = 180) -> str:
    """Решить reCAPTCHA v3, вернуть токен (gRecaptchaResponse)."""
    client_key = load_key(key)
    task = {
        "type": "RecaptchaV3TaskProxyless",
        "websiteURL": website_url,
        "websiteKey": website_key,
        "minScore": min_score,
    }
    if page_action:
        task["pageAction"] = page_action
    if is_enterprise:
        task["isEnterprise"] = True

    r = requests.post(f"{API}/createTask", json={"clientKey": client_key, "task": task}, timeout=30)
    data = r.json()
    if data.get("errorId"):
        raise RuntimeError(f"createTask error: {data.get('errorCode')} {data.get('errorDescription')}")
    task_id = data["taskId"]

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        time.sleep(5)
        r = requests.post(f"{API}/getTaskResult",
                          json={"clientKey": client_key, "taskId": task_id}, timeout=30)
        res = r.json()
        if res.get("errorId"):
            raise RuntimeError(f"getTaskResult error: {res.get('errorCode')} {res.get('errorDescription')}")
        if res.get("status") == "ready":
            return res["solution"]["gRecaptchaResponse"]
    raise TimeoutError(f"Anti-Captcha не решил капчу за {timeout_s}с (taskId {task_id}).")
