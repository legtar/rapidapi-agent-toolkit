"""Fetch pricing pages for all free-tier LinkedIn APIs; extract the $0 plan quota + rate limit."""
import sys, json, time, re
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import requests
import rapidapi_hub as hub
from parse_plans import parse_plans

c = hub.Creds.from_curl("provider_curl.txt")
rows = json.load(open("li_all_cat.json", encoding="utf-8"))
free = [r for r in rows if (r.get("pricing") or "") in ("FREE", "FREEMIUM") and r.get("url")]
print("free-tier APIs to fetch:", len(free))

H = {"user-agent": c.user_agent or "Mozilla/5.0", "cookie": c.cookie, "accept": "text/html"}


def one(r):
    url = r["url"].rstrip("/") + "/pricing"
    try:
        t = requests.get(url, headers=H, timeout=35).text
        plans = parse_plans(t)
    except Exception as e:
        return {**pick(r), "error": str(e)[:60], "plans": []}
    pub = [p for p in plans if p.get("visibility") != "PRIVATE"]
    # the free plan = price 0 (or pricing FREE) among public plans
    freeplans = [p for p in pub if (p.get("price") in (0, 0.0, None) and p.get("pricing") in ("FREE", "FREEMIUM"))]
    fp = None
    for p in freeplans:
        if p.get("price") in (0, 0.0):
            fp = p; break
    if fp is None and freeplans:
        fp = freeplans[0]
    return {**pick(r), "n_public_plans": len(pub), "free_plan": fp,
            "all_plan_prices": sorted({p.get("price") for p in pub if p.get("price") is not None})}


def pick(r):
    return {"name": r.get("name"), "provider": r.get("provider"), "cat": r.get("_cat"),
            "pricing": r.get("pricing"), "pop": r.get("popularity"), "url": r.get("url")}


out, done = [], 0
with ThreadPoolExecutor(max_workers=10) as ex:
    futs = {ex.submit(one, r): r for r in free}
    for f in as_completed(futs):
        out.append(f.result())
        done += 1
        if done % 25 == 0:
            print(f"  {done}/{len(free)}")
            json.dump(out, open("li_free_quotas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)

json.dump(out, open("li_free_quotas.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
ok = [o for o in out if o.get("free_plan")]
print("DONE. parsed free plan for", len(ok), "of", len(out))
