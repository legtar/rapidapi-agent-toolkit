"""
rapidapi_meta — внутренние GraphQL-операции RapidAPI для АВТОМАТИЗАЦИИ подключения.

Пойманы из playground в DevTools. Дают полный цикл без UI:
  * projects()        — твои проекты + X-RapidAPI-Key (xMashapeKey) + подписанные API   [getEntityProjects]
  * endpoint(id)      — полное описание эндпоинта: route/method/параметры/примеры        [getFullApiEndpoint]
  * gateways()        — прокси-шлюзы (dns вида <...>.p.rapidapi.com) + шаблоны заголовков [getPlaygroundGateways]
  * active_user()     — данные активного пользователя                                     [activeUser]

Все используют общий клиент rapidapi_hub.graphql() и те же креды из curl.txt.
"""

from __future__ import annotations

import re
from typing import Optional

import requests

import rapidapi_hub as hub
from rapidapi_hub import Creds, graphql

# Публичный site-key reCAPTCHA v3 для rapidapi.com (из конфига страницы, поле RECAPTCHA_V3_SITE_KEY).
RECAPTCHA_V3_SITE_KEY = "6LcBAiIlAAAAAH7OT1u0VP9-UYl9A5NThSLwT7Wj"


# --------------------------------------------------------------------------- #
#  Запросы (транскрибированы из пойманного трафика)
# --------------------------------------------------------------------------- #

GET_ENTITY_PROJECTS = """
query getEntityProjects($entityID: ID) {
  entityById(id: $entityID) {
    ...EntityCoreFields
    projectAcls {
      Project { ...ProjectFields }
      NacApplicationStatus
    }
  }
}
fragment EntityCoreFields on Entity { name id thumbnail username email }
fragment ProjectFields on Project {
  id
  name
  mashapeId
  thumbnail
  favorite
  xMashapeKey
  enableLimitsToAPIs
  projectAllowedAPIs { ...ProjectAllowedAPIsFields }
}
fragment ProjectAllowedAPIsFields on ProjectAllowedAPI {
  id
  projectId
  apiId
  api { id name slugifiedName }
  apiVersionId
  status
}
""".strip()

GET_FULL_API_ENDPOINT = """
query getFullApiEndpoint($id: ID!) {
  endpoint(id: $id) { ...FullEndpointInfo }
}
fragment FullEndpointInfo on Endpoint {
  id
  index
  createdAt
  group
  method
  name
  route
  description
  isGraphQL
  params { parameters }
  responsePayloads { id name format body description type statusCode examples schema }
  requestPayloads { id name format body description type statusCode examples schema }
}
""".strip()

GET_PLAYGROUND_GATEWAYS = """
query getPlaygroundGateways {
  getGateways { ...GetGatewayFields }
  tenant { ...TenantFields }
}
fragment GetGatewayFields on Gateway {
  id
  dns
  serviceStatus
  type
  status
  isDefault
  gatewayTemplate { ...GatewayTemplateFields }
}
fragment GatewayTemplateFields on GatewayTemplate {
  name
  urlPattern
  headers { ...HeaderFields }
}
fragment HeaderFields on Header { paramName paramValue paramDescription id }
fragment TenantFields on Tenant { id domain name slugifiedKey }
""".strip()

ACTIVE_USER = """
query activeUser {
  activeUser { id name email username entity thumbnail billingType }
}
""".strip()

# Реальные цены + лимиты подписки на API (по apiId + entityId).
GET_API_SUBSCRIBER = """
query getApiSubscriber($apiId: ID!, $entityId: ID!) {
  subscriber: entityById(id: $entityId) {
    id
    type
    subscription: activeSubscriptionByApiId(apiId: $apiId) {
      id
      status
      type
      billingPlanVersion { ...BillingPlanVersionInfo }
    }
  }
}
fragment BillingPlanVersionInfo on BillingPlanVersion {
  id
  name
  period
  price
  currency
  pricing
  localePrice { price symbol }
  billinglimits {
    period
    amount
    unlimited
    overageprice
    billingitem { name displayName type }
  }
  rateLimit { enabled unit unitName amount }
}
""".strip()

# Мутация подписки. ВНИМАНИЕ: requires recaptchaToken (Google reCAPTCHA v3),
# который выпускается ТОЛЬКО в браузере, одноразовый и живёт ~2 мин.
CREATE_API_SUBSCRIPTION = """
mutation createApiSubscription($input: CreateApiSubscriptionInput!) {
  createApiSubscription(input: $input) {
    subscriptionId
    clientSecret
    paymentStatus
  }
}
""".strip()


# --------------------------------------------------------------------------- #
#  Обёртки
# --------------------------------------------------------------------------- #


def active_user(creds: Creds) -> dict:
    return (graphql(creds, ACTIVE_USER, operation="activeUser") or {}).get("activeUser") or {}


def projects(creds: Creds, entity_id: Optional[str] = None) -> list[dict]:
    """Список проектов пользователя с ключом и подписанными API.

    Возвращает [{ project_id, name, key, apis: [{name, slug, status}] }].
    key (xMashapeKey) — это твой X-RapidAPI-Key.
    """
    eid = entity_id or creds.entity_id
    data = graphql(creds, GET_ENTITY_PROJECTS, {"entityID": eid}, "getEntityProjects")
    entity = data.get("entityById") or {}
    out = []
    for acl in entity.get("projectAcls") or []:
        p = acl.get("Project") or {}
        apis = []
        for a in p.get("projectAllowedAPIs") or []:
            api = a.get("api") or {}
            apis.append({"name": api.get("name"), "slug": api.get("slugifiedName"),
                         "status": a.get("status")})
        out.append({
            "project_id": p.get("id"),
            "name": p.get("name"),
            "key": p.get("xMashapeKey"),
            "apis": apis,
        })
    return out


def endpoint(creds: Creds, endpoint_id: str) -> dict:
    data = graphql(creds, GET_FULL_API_ENDPOINT, {"id": endpoint_id}, "getFullApiEndpoint")
    return data.get("endpoint") or {}


def gateways(creds: Creds) -> list[dict]:
    data = graphql(creds, GET_PLAYGROUND_GATEWAYS, operation="getPlaygroundGateways")
    return data.get("getGateways") or []


def subscription(creds: Creds, api_id: str, entity_id: Optional[str] = None) -> dict:
    """Активная подписка на API + РЕАЛЬНЫЕ цены/лимиты плана (или {} если не подписан).

    api_id — 'api_...' из результатов поиска (поле id).
    """
    eid = entity_id or creds.entity_id
    data = graphql(creds, GET_API_SUBSCRIBER, {"apiId": api_id, "entityId": eid}, "getApiSubscriber")
    sub = (data.get("subscriber") or {}).get("subscription")
    if isinstance(sub, list):  # activeSubscriptionByApiId может вернуть список
        sub = sub[0] if sub else {}
    return sub or {}


def find_api(creds: Creds, slug: str, term: Optional[str] = None) -> Optional[dict]:
    """Найти API по slug через поиск: вернуть {api_id, owner_id, username, url}."""
    for node in hub.iter_nodes(creds, term or slug.replace("-", " "), first=50):
        if node.get("slugifiedName") == slug:
            u = node.get("user") or {}
            return {
                "api_id": node.get("id"),
                "owner_id": str(u.get("id")) if u.get("id") is not None else None,
                "username": u.get("username"),
                "url": f"https://rapidapi.com/{u.get('username')}/api/{slug}",
            }
    return None


def plans_from_pricing(creds: Creds, username: str, slug: str) -> list[dict]:
    """Снять планы (name/price/pricing/version_id) со страницы pricing (SSR).

    Даёт billingPlanVersionId для КАЖДОГО плана, включая ещё не подписанные — то, чего
    не отдаёт getApiSubscriber. Нужно, чтобы подписаться на конкретный план.
    """
    url = f"https://rapidapi.com/{username}/api/{slug}/pricing"
    headers = {"user-agent": creds.user_agent or "Mozilla/5.0",
               "cookie": creds.cookie, "accept": "text/html"}
    t = requests.get(url, headers=headers, timeout=30).text
    plans: dict[str, dict] = {}
    for m in re.finditer(r"billingplanversion_[0-9a-f\-]{36}", t):
        vid = m.group(0)
        i = m.start()
        back, fwd = t[max(0, i - 260):i], t[i:i + 320]
        name = re.findall(r'\\"name\\":\\"([A-Z][A-Z ]*)\\"', back)
        price = re.findall(r'\\"price\\":([0-9.]+|null)', fwd)
        pricing = re.findall(r'\\"pricing\\":\\"([A-Z]+)\\"', fwd)
        plans[vid] = {
            "plan": name[-1] if name else "?",
            "price": price[0] if price else None,
            "pricing": pricing[0] if pricing else None,
            "version_id": vid,
        }
    return list(plans.values())


def subscribe(creds: Creds, api_id: str, billing_plan_version_id: str,
              owner_id: str, recaptcha_token: str) -> dict:
    """Подписаться на план API (мутация createApiSubscription).

    ТРЕБУЕТ свежий recaptcha_token из браузера (reCAPTCHA v3, одноразовый, ~2 мин).
    Без валидного токена сервер отклонит запрос. Полностью headless НЕ работает — это
    намеренный анти-бот барьер RapidAPI. Гварды ($0-план, подтверждение) — на стороне CLI.
    """
    variables = {"input": {
        "apiId": api_id,
        "billingPlanVersionId": billing_plan_version_id,
        "ownerId": owner_id,
        "recaptchaToken": recaptcha_token,
    }}
    data = graphql(creds, CREATE_API_SUBSCRIPTION, variables, "createApiSubscription")
    return data.get("createApiSubscription") or {}
