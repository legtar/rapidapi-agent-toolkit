"""rapidapi_provider — управление своим API на RapidAPI из кода (provider-dashboard GraphQL).

Переиспользует парсер cURL из rapidapi_hub (cookie/csrf/entity). Сложи свежий cURL
любого запроса provider-дашборда в provider_curl.txt (Copy as cURL из DevTools) — при
протухании cf_clearance пересними.

Пример:
    import rapidapi_provider as pv
    c = pv.creds()                      # из provider_curl.txt
    print(pv.api_full(c))               # состояние API + тарифы
    print(pv.traffic_summary(c))        # трафик
    print(pv.health_status(c))          # статус healthcheck
    # применить целевые тарифы (сохраняет остальные billingLimits):
    pv.apply_target_plans(c, dry_run=True)
"""
from __future__ import annotations
import json
import requests
import rapidapi_hub as hub

GQL = "https://rapidapi.com/gateway/graphql"

API = "api_e242a636-cdf0-46ba-b46b-b153fbfa6f0f"
API_VERSION = "apiversion_b0993ce2-616c-4f76-a6b1-d520136f4840"
API_VERSION_NAME = "1.0.0"
API_NAME = "LinkedIn Jobs API"
PROVIDER_NAME = "Alexey Kuznetsov"
REQUESTS_ITEM = "billingitem_42141932-b92b-459d-9c93-5564725f5794"
PLAN_IDS = {
    "BASIC": "billingplan_71bf11e5-6149-4718-9fc0-bec0c27429c2",
    "PRO": "billingplan_890f1350-cec9-4e72-8934-89f39ec14b5b",
    "ULTRA": "billingplan_6805f08d-9b3d-446d-a41e-f24a8e893b01",
    # MEGA — доловить: api_full()["billingPlans"] содержит name+id
}

# Целевая конфигурация (щадящие rate limits; править по желанию)
TARGET = {
    "BASIC": {"price": 0, "requests": 25, "rate": (5, "minute"), "recommended": False, "approval": False},
    "PRO": {"price": 19, "requests": 1000, "rate": (10, "minute"), "recommended": True, "approval": False},
    "ULTRA": {"price": 49, "requests": 5000, "rate": (20, "minute"), "recommended": False, "approval": False},
    "MEGA": {"price": 99, "requests": 15000, "rate": (30, "minute"), "recommended": False, "approval": True},
}


def creds(path: str = "provider_curl.txt") -> hub.Creds:
    return hub.Creds.from_curl(path)


def gql(c: hub.Creds, query: str, variables: dict, operation: str,
        client: str = "provider-dashboard-service") -> dict:
    h = {
        "content-type": "application/json", "accept": "application/json",
        "origin": "https://rapidapi.com", "referer": "https://rapidapi.com/",
        "rapid-client": client, "x-entity-id": c.entity_id or "",
        "csrf-token": c.csrf_token or "", "cookie": c.cookie,
        "user-agent": c.user_agent or "Mozilla/5.0",
    }
    r = requests.post(GQL, headers=h, json={"operationName": operation, "query": query,
                                            "variables": variables}, timeout=40)
    try:
        data = r.json()
    except Exception:
        raise hub.RapidApiError(f"HTTP {r.status_code}: {r.text[:200]}")
    if isinstance(data, dict) and data.get("errors"):
        raise hub.RapidApiError("GraphQL errors: " + json.dumps(data["errors"])[:400])
    return data.get("data") or {}


# ---------------- read ----------------
_API_FULL_Q = """
query api($id: ID!) {
  api(id: $id) {
    id name visibility subscriptionsCount pricing gateways
    security { rapidapiProxySecret }
    targetGroups { targetUrls { url } }
    endpoints(pagingArgs: {limit: -1}) { method route status }
    billingPlans(pagingArgs: {limit: -1}) {
      name id visibility recommended shouldRequestApproval
      version { id price period pricing
        rateLimit { enabled amount unit unitName }
        billinglimits { amount period unlimited overageprice limitType
          billingitem { id name } } }
    }
  }
}""".strip()


def api_full(c: hub.Creds) -> dict:
    return gql(c, _API_FULL_Q, {"id": API}, "api")["api"]


def plan_ids(c: hub.Creds) -> dict:
    return {p["name"]: p["id"] for p in api_full(c).get("billingPlans", [])}


_TRAFFIC_Q = ("query s($w: AnalyticsStatsInput!){apiTrafficAnalyticsSummary(where:$w)"
              "{requests{total avg rps} errors{total} latency{avg median}}}")


def traffic_summary(c: hub.Creds, from_date: str, to_date: str) -> dict:
    v = {"w": {"apiIds": [API], "fromDate": from_date, "toDate": to_date,
               "timeOffset": 0, "resolution": "DAYS"}}
    return gql(c, _TRAFFIC_Q, v, "s")["apiTrafficAnalyticsSummary"]


_HEALTH_Q = ("query h($apiId: ID!){api(id:$apiId){apiHealthCheck{healthcheckStatus"
             "{status lastExecution}}}}")


def health_status(c: hub.Creds) -> dict:
    return gql(c, _HEALTH_Q, {"apiId": API}, "h")["api"]["apiHealthCheck"]["healthcheckStatus"]


_KEY_Q = ("query getEntityApis{activeEntity{id name projectAcls{Project"
          "{xRapidKey:xMashapeKey}} apis{name slugifiedName visibility pricing}}}")


def entity_key(c: hub.Creds) -> dict:
    e = gql(c, _KEY_Q, {}, "getEntityApis")["activeEntity"]
    keys = [p["Project"]["xRapidKey"] for p in (e.get("projectAcls") or []) if p.get("Project", {}).get("xRapidKey")]
    return {"key": keys[0] if keys else None,
            "apis": [(a["name"], a["visibility"], a.get("pricing")) for a in (e.get("apis") or [])]}


# ---------------- write ----------------
_UPD_M = """
mutation updateBillingPlan($updateExtendedInput: BillingPlanExtendedUpdateInput!, $updateMetadataInput: BillingPlanMetadataUpdateInput!) {
  updateBillingPlanMetadata(billingPlan: $updateMetadataInput) { id }
  updateBillingPlanExtended(billingPlan: $updateExtendedInput) {
    id name recommended shouldRequestApproval
    version { price rateLimit { enabled amount unitName } billinglimits { amount period billingitem { id name } } }
  }
}""".strip()


def _limits_from_plan(plan: dict, new_requests: int) -> list:
    """Сохранить все существующие billingLimits, поменять только Requests-amount."""
    out = []
    for l in (plan.get("version", {}).get("billinglimits") or []):
        item = (l.get("billingitem") or {}).get("id")
        amount = new_requests if item == REQUESTS_ITEM else l.get("amount")
        out.append({"amount": amount, "item": item,
                    "limitType": l.get("limitType") or "hard",
                    "overagePrice": l.get("overageprice") or 0,
                    "period": l.get("period") or "MONTHLY",
                    "perusagePrice": 0, "unlimited": bool(l.get("unlimited"))})
    if not any(x["item"] == REQUESTS_ITEM for x in out):
        out.append({"amount": new_requests, "item": REQUESTS_ITEM, "limitType": "hard",
                    "overagePrice": 0, "period": "MONTHLY", "perusagePrice": 0, "unlimited": False})
    return out


def update_plan(c: hub.Creds, name: str, plan_id: str, plan: dict, cfg: dict) -> dict:
    ext = {
        "api": API, "apiName": API_NAME, "apiVersion": API_VERSION,
        "apiVersionName": API_VERSION_NAME, "providerName": PROVIDER_NAME,
        "billingPlanId": plan_id, "isStudent": (False if name == "BASIC" else None),
        "isPrivatePlan": False, "legalAccountId": "", "legalDocumentId": "",
        "name": name, "targetGroup": "",
        "billingLimits": _limits_from_plan(plan, cfg["requests"]),
        "enableBillingFeatures": [], "price": cfg["price"], "type": "MONTHLY",
        "shouldRequestApproval": cfg["approval"], "requestApprovalQuestion": "",
    }
    if cfg.get("rate"):
        amt, unit = cfg["rate"]
        ext["rateLimit"] = {"amount": amt, "enabled": True, "unit": 1, "unitName": unit}
    meta = {"billingPlanId": plan_id, "recommended": cfg["recommended"],
            "legalDocumentId": "", "legalAccountId": ""}
    return gql(c, _UPD_M, {"updateExtendedInput": ext, "updateMetadataInput": meta}, "updateBillingPlan")


def apply_target_plans(c: hub.Creds, target: dict = None, dry_run: bool = True) -> list:
    """Применить TARGET ко всем планам, сохраняя прочие billingLimits."""
    target = target or TARGET
    full = api_full(c)
    plans = {p["name"]: p for p in full.get("billingPlans", [])}
    ids = {p["name"]: p["id"] for p in full.get("billingPlans", [])}
    results = []
    for name, cfg in target.items():
        pid = ids.get(name)
        plan = plans.get(name)
        if not pid or not plan:
            results.append((name, "SKIP: plan not found")); continue
        if dry_run:
            results.append((name, f"WOULD set price={cfg['price']} requests={cfg['requests']} "
                                  f"rate={cfg.get('rate')} recommended={cfg['recommended']} "
                                  f"limits={[ (x['billingitem']['name'], x['amount']) for x in (plan['version'].get('billinglimits') or []) ]}"))
        else:
            try:
                update_plan(c, name, pid, plan, cfg)
                results.append((name, "OK"))
            except Exception as e:
                results.append((name, f"FAIL: {e}"))
    return results


if __name__ == "__main__":
    c = creds()
    a = api_full(c)
    print("API:", a["name"], a["visibility"], "subs", a["subscriptionsCount"])
    print("plans:", [(p["name"], p["version"]["price"], p["version"].get("rateLimit")) for p in a["billingPlans"]])
    print("\nDRY-RUN apply_target_plans:")
    for n, r in apply_target_plans(c, dry_run=True):
        print(" ", n, r)
