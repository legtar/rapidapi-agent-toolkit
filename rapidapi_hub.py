"""
rapidapi_hub — программный доступ к внутреннему GraphQL RapidAPI Hub (без UI).

Что умеет:
  * Creds.from_curl(path)      — вытащить креды (cookie / csrf / entity-id / UA / privateApisJwt)
                                 из сохранённого cURL запроса `searchApis` (Copy as cURL из DevTools).
  * iter_nodes(...)            — итерироваться по всем API выдачи с курсорной пагинацией.
  * search_apis(...)           — собрать нормализованный список (с фильтром по категории и лимитом).
  * overview(...)              — total + facets по категориям (одна страница).
  * normalize(node)            — плоская запись об API (name/provider/slug/pricing/метрики/url).

Детали эндпоинта — см. FINDINGS.md.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from typing import Iterator, Optional

import requests

GRAPHQL_URL = "https://rapidapi.com/gateway/graphql"

# Точный запрос searchApis, снятый из живого трафика (см. FINDINGS.md).
SEARCH_QUERY = """
query searchApis($searchApiWhereInput: SearchApiWhereInput!, $paginationInput: PaginationInput, $searchApiOrderByInput: SearchApiOrderByInput) {
  products: searchApis(where: $searchApiWhereInput, pagination: $paginationInput, orderBy: $searchApiOrderByInput) {
    nodes {
      id
      thumbnail
      name
      description
      slugifiedName
      pricing
      updatedAt
      categoryName
      isSavedApi
      title
      visibility
      category: categoryName
      apiCategory { name color }
      score { popularityScore avgLatency avgServiceLevel avgSuccessRate }
      version { tags { id status tagdefinition type value } }
      user: User {
        id
        username
        slugifiedName: username
        name
        type
        parents { id name slugifiedName type thumbnail }
      }
    }
    facets { category { key count } }
    pageInfo { endCursor hasNextPage hasPreviousPage startCursor }
    total
    queryID
    replicaIndex
  }
}
""".strip()


# --------------------------------------------------------------------------- #
#  Разбор сохранённого cURL
# --------------------------------------------------------------------------- #

# Двойная / одинарная кавычка с поддержкой экранирования \" внутри значения.
_DQ = r'"((?:[^"\\]|\\.)*)"'
_SQ = r"'((?:[^'\\]|\\.)*)'"


def _unescape(v: str) -> str:
    return v.replace('\\"', '"').replace("\\'", "'")


def _normalize_curl_text(text: str) -> str:
    """Привести cURL к виду, удобному для регэкспов.

    Поддерживает и Windows cmd-форму (экранирование ^), и bash-форму (\\ + перенос строки).
    Тело GraphQL мы не парсим (запрос захардкожен) — нужны только cookie/заголовки/JWT,
    поэтому агрессивная нормализация переносов безопасна.
    """
    if "^" in text:  # Windows cmd "Copy as cURL"
        text = text.replace("^", "")
    text = re.sub(r"\\\r?\n", " ", text)  # bash-перенос строки
    text = re.sub(r"\r?\n", " ", text)  # прочие переносы -> пробел
    return text


def _find_flag_value(flags: str, text: str) -> Optional[str]:
    m = re.search(r"(?:%s)\s+(?:%s|%s)" % (flags, _DQ, _SQ), text)
    if not m:
        return None
    return _unescape(m.group(1) if m.group(1) is not None else m.group(2))


def _find_headers(text: str) -> dict:
    headers: dict[str, str] = {}
    for m in re.finditer(r"(?:-H|--header)\s+(?:%s|%s)" % (_DQ, _SQ), text):
        raw = m.group(1) if m.group(1) is not None else m.group(2)
        raw = _unescape(raw)
        if ":" not in raw:
            continue
        name, value = raw.split(":", 1)
        headers[name.strip().lower()] = value.strip()
    return headers


@dataclass
class Creds:
    cookie: str
    csrf_token: str = ""
    entity_id: str = ""
    user_agent: str = ""
    private_apis_jwt: str = ""
    referer: str = "https://rapidapi.com/search/Data?term=&sortBy=ByRelevance"
    extra_headers: dict = field(default_factory=dict)

    @classmethod
    def from_curl(cls, path: str) -> "Creds":
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            raw = fh.read()
        text = _normalize_curl_text(raw)
        headers = _find_headers(text)

        # cookie: из -b/--cookie либо из заголовка cookie
        cookie = _find_flag_value(r"-b|--cookie", text) or headers.get("cookie", "")
        if not cookie:
            raise ValueError(
                "В cURL не найден cookie (флаг -b или заголовок 'cookie:'). "
                "Проверь, что сохранён полный запрос searchApis из DevTools."
            )

        entity_id = headers.get("x-entity-id", "")
        if not entity_id:
            m = re.search(r"rapidapi-context-id=(\d+)", cookie)
            entity_id = m.group(1) if m else ""

        # privateApisJwt из тела (опционально)
        jwt = ""
        mj = re.search(r"privateApisJwt.{0,20}?(eyJ[\w\-]+\.[\w\-]+\.[\w\-]+)", text)
        if mj:
            jwt = mj.group(1)

        known = {"content-type", "accept", "cookie", "csrf-token", "x-entity-id",
                 "user-agent", "referer", "origin", "rapid-client", "x-correlation-id"}
        extra = {k: v for k, v in headers.items() if k not in known}

        return cls(
            cookie=cookie,
            csrf_token=headers.get("csrf-token", ""),
            entity_id=entity_id,
            user_agent=headers.get("user-agent", ""),
            private_apis_jwt=jwt,
            referer=headers.get("referer", cls.referer),
            extra_headers=extra,
        )

    def request_headers(self) -> dict:
        h = {
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "origin": "https://rapidapi.com",
            "referer": self.referer,
            "rapid-client": "hub-service",
            "x-correlation-id": str(uuid.uuid4()),
            "cookie": self.cookie,
        }
        if self.csrf_token:
            h["csrf-token"] = self.csrf_token
        if self.entity_id:
            h["x-entity-id"] = self.entity_id
        if self.user_agent:
            h["user-agent"] = self.user_agent
        return h


# --------------------------------------------------------------------------- #
#  GraphQL-клиент
# --------------------------------------------------------------------------- #


class RapidApiError(RuntimeError):
    pass


def graphql(creds: Creds, query: str, variables: Optional[dict] = None,
            operation: Optional[str] = None,
            session: Optional[requests.Session] = None) -> dict:
    """Выполнить произвольную операцию к внутреннему GraphQL RapidAPI и вернуть data.

    Универсально: подходит для searchApis, getEntityProjects, getFullApiEndpoint и т.д.
    """
    own = session or requests.Session()
    payload: dict = {"query": query}
    if variables is not None:
        payload["variables"] = variables
    if operation:
        payload["operationName"] = operation
    try:
        resp = own.post(GRAPHQL_URL, json=payload, headers=creds.request_headers(), timeout=30)
    finally:
        if session is None:
            own.close()

    head = resp.text.lower()[:2000]
    if resp.status_code in (401, 403) or "cloudflare" in head or "just a moment" in head:
        raise RapidApiError(
            f"HTTP {resp.status_code}: доступ отклонён (вероятно, протух cf_clearance/cookie или "
            f"CSRF). Обнови curl.txt свежим запросом из DevTools."
        )
    try:
        data = resp.json()
    except json.JSONDecodeError:
        raise RapidApiError(f"HTTP {resp.status_code}: ответ не JSON (первые 300 симв.):\n{resp.text[:300]}")
    if data.get("errors"):
        raise RapidApiError("GraphQL errors: " + json.dumps(data["errors"], ensure_ascii=False)[:800])
    return data.get("data") or {}


def _post(session: requests.Session, creds: Creds, term: str,
          first: int, after: Optional[str], order: Optional[str]) -> dict:
    where: dict = {"term": term}
    if creds.entity_id:
        where["contextId"] = creds.entity_id
    if creds.private_apis_jwt:
        where["privateApisJwt"] = creds.private_apis_jwt

    pagination: dict = {"first": first}
    if after:
        pagination["after"] = after

    variables: dict = {"searchApiWhereInput": where, "paginationInput": pagination}
    if order:
        variables["searchApiOrderByInput"] = order

    data = graphql(creds, SEARCH_QUERY, variables, "searchApis", session=session)
    products = data.get("products")
    if products is None:
        raise RapidApiError("Пустой ответ (data.products = null). Проверь права/креды.")
    return products


def iter_nodes(creds: Creds, term: str, first: int = 50,
               order: Optional[str] = None, session: Optional[requests.Session] = None) -> Iterator[dict]:
    """Итератор по всем сырым узлам API выдачи (с курсорной пагинацией)."""
    own = session or requests.Session()
    after: Optional[str] = None
    try:
        while True:
            products = _post(own, creds, term, first, after, order)
            for node in products.get("nodes", []):
                yield node
            page = products.get("pageInfo") or {}
            if not page.get("hasNextPage") or not page.get("endCursor"):
                break
            after = page["endCursor"]
    finally:
        if session is None:
            own.close()


def overview(creds: Creds, term: str) -> dict:
    """total + facets по категориям (одна страница)."""
    session = requests.Session()
    try:
        products = _post(session, creds, term, first=1, after=None, order=None)
    finally:
        session.close()
    return {
        "total": products.get("total"),
        "facets": (products.get("facets") or {}).get("category", []),
    }


# --------------------------------------------------------------------------- #
#  Нормализация
# --------------------------------------------------------------------------- #

_EM = re.compile(r"</?em>")

# Порядок колонок для экспорта.
FIELDS = ["name", "provider", "provider_name", "provider_type", "category", "pricing",
          "popularity", "success_rate", "latency_ms", "service_level", "updated_at",
          "url", "id", "description"]


def _clean(s: Optional[str]) -> str:
    return _EM.sub("", s or "").strip()


def normalize(node: dict) -> dict:
    user = node.get("user") or {}
    username = user.get("username")
    slug = node.get("slugifiedName")
    score = node.get("score") or {}
    return {
        "name": _clean(node.get("name") or node.get("title")),
        "title": _clean(node.get("title")),
        "provider": username,
        "provider_name": user.get("name"),
        "provider_type": user.get("type"),
        "category": node.get("categoryName") or node.get("category"),
        "pricing": node.get("pricing"),
        "popularity": score.get("popularityScore"),
        "latency_ms": score.get("avgLatency"),
        "success_rate": score.get("avgSuccessRate"),
        "service_level": score.get("avgServiceLevel"),
        "updated_at": node.get("updatedAt"),
        "url": f"https://rapidapi.com/{username}/api/{slug}" if username and slug else None,
        "description": _clean(node.get("description")),
        "id": node.get("id"),
    }


def search_apis(creds: Creds, term: str, category: Optional[str] = None,
                limit: Optional[int] = None, first: int = 50,
                order: Optional[str] = None) -> list[dict]:
    """Собрать нормализованный список API.

    category — клиентский фильтр по categoryName (регистронезависимо), т.к. серверное
    имя поля фильтра неизвестно (см. FINDINGS.md, открытые вопросы).
    limit — максимум записей (None = все страницы).
    """
    cat = category.lower() if category else None
    out: list[dict] = []
    for node in iter_nodes(creds, term, first=first, order=order):
        rec = normalize(node)
        if cat and (rec["category"] or "").lower() != cat:
            continue
        out.append(rec)
        if limit and len(out) >= limit:
            break
    return out
