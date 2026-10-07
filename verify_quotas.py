"""Retry youtube362, then verify REAL active-plan quotas for every subscription
via getApiSubscriber (ground truth after subscribing)."""
import json
import rapidapi_hub as hub
import rapidapi_meta as meta
import rapidapi_captcha as captcha

creds = hub.Creds.from_curl("curl.txt")
results = json.load(open("subscribe_results.json", encoding="utf-8"))
byslug = {r["slug"]: r for r in results}

# --- 1) retry youtube362 with resolved ids ---
yt = byslug.get("youtube362")
if yt and not yt.get("ok"):
    api_id = "api_17030a0a-610d-49db-8937-3dfeaa229fc8"
    owner_id = "6921437"
    ver = next((p["version_id"] for p in json.load(open("plans_report.json", encoding="utf-8"))
                if p["slug"] == "youtube362" for p in [next(x for x in p["plans"] if x["plan"] == "BASIC")]), None)
    # simpler: reload version id
    rep = {r["slug"]: r for r in json.load(open("plans_report.json", encoding="utf-8"))}
    basic = next(p for p in rep["youtube362"]["plans"] if p["plan"] == "BASIC")
    print(f"Retry youtube362: apiId={api_id} ownerId={owner_id} ver={basic['version_id']} — captcha...")
    try:
        token = captcha.solve_recaptcha_v3(
            website_url="https://rapidapi.com/alexanderxbx/api/youtube362/pricing",
            website_key=meta.RECAPTCHA_V3_SITE_KEY, page_action="", min_score=0.3)
        res = meta.subscribe(creds, api_id, basic["version_id"], owner_id, token)
        yt.update({"api_id": api_id, "owner_id": owner_id, "result": res,
                   "ok": bool(res.get("subscriptionId")), "error": None})
        print("  ->", res)
    except Exception as e:
        yt["error"] = f"{type(e).__name__}: {e}"
        print("  x", yt["error"])
    json.dump(results, open("subscribe_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# --- 2) verify real quotas via getApiSubscriber ---
print("\n===== REAL active-plan quotas (getApiSubscriber) =====")
verified = []
for r in results:
    if not r.get("ok") or not r.get("api_id"):
        continue
    try:
        sub = meta.subscription(creds, r["api_id"])
    except Exception as e:
        print(f"  {r['slug']}: verify error {e}"); continue
    plan = sub.get("billingPlanVersion") or {}
    reqs = None; period = None; unlimited = False
    for lim in plan.get("billinglimits") or []:
        bi = lim.get("billingitem") or {}
        if (bi.get("name") or "").lower() == "requests":
            reqs = lim.get("amount"); period = lim.get("period"); unlimited = lim.get("unlimited")
    rl = plan.get("rateLimit") or {}
    rate = f"{rl.get('amount')}/{rl.get('unitName') or rl.get('unit')}" if rl.get("enabled") else "-"
    row = {"slug": r["slug"], "name": r["name"], "status": sub.get("status"),
           "plan": plan.get("name"), "price": plan.get("price"),
           "reqs": "unlimited" if unlimited else reqs, "period": period, "rate": rate}
    verified.append(row)
    print(f"  {r['slug'][:44]:44} plan={str(plan.get('name'))[:8]:8} "
          f"quota={str(row['reqs']):9}/{str(period):8} rate={rate:12} status={sub.get('status')}")

json.dump(verified, open("verified_quotas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# --- 3) totals ---
def monthly(reqs, period):
    if reqs in (None, "unlimited"):
        return None
    try: n = float(reqs)
    except: return None
    return int(n * 30) if period == "DAILY" else int(n)
tot = 0; unknown = []
for row in verified:
    m = monthly(row["reqs"], row["period"])
    if m is None: unknown.append(row["slug"])
    else: tot += m
print(f"\nVerified free-tier total = {tot:,} requests/month  (unknown quota: {unknown})")
