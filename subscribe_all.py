"""Batch-subscribe the free BASIC plan on every YouTube-email target.

Guard: only subscribes plans whose BASIC price == 0. Records subscriptionId,
paymentStatus, and the free quota into subscribe_results.json.
"""
import json, sys, time
import rapidapi_hub as hub
import rapidapi_meta as meta
import rapidapi_captcha as captcha

creds = hub.Creds.from_curl("curl.txt")
rep = {r["slug"]: r for r in json.load(open("plans_report.json", encoding="utf-8"))}

# targets to subscribe (slug -> username). All have a $0 BASIC plan.
targets = [(r["provider"], r["slug"], r["name"]) for r in json.load(open("yt_targets.json", encoding="utf-8"))]

# skip ones already subscribed (re-run safety): read existing results
try:
    prior = {r["slug"]: r for r in json.load(open("subscribe_results.json", encoding="utf-8"))}
except FileNotFoundError:
    prior = {}

results = []
for prov, slug, name in targets:
    if slug in prior and prior[slug].get("ok"):
        print(f"= SKIP (already) {slug}")
        results.append(prior[slug]); continue
    rec = {"slug": slug, "provider": prov, "name": name, "ok": False}
    plans = rep.get(slug, {}).get("plans", [])
    basic = next((p for p in plans if p.get("plan") == "BASIC"), None)
    if not basic:
        rec["error"] = "no BASIC plan"; results.append(rec); print("x", slug, rec["error"]); continue
    if str(basic.get("price")) not in ("0", "0.0", "None", "null", "0.00"):
        rec["error"] = f"BASIC not free (price={basic.get('price')})"; results.append(rec); print("x", slug, rec["error"]); continue
    rec["free_quota"] = f"{basic.get('requests')}/{basic.get('period')}"
    rec["version_id"] = basic.get("version_id")
    print(f"\n>>> {name}  ({prov}/{slug})  free={rec['free_quota']}")
    try:
        info = meta.find_api(creds, slug)
        if not info or not info.get("api_id"):
            rec["error"] = "find_api failed (not surfaced in search)"; results.append(rec); print("  x", rec["error"]); continue
        rec["api_id"] = info["api_id"]; rec["owner_id"] = info["owner_id"]
        print(f"  apiId={info['api_id']} ownerId={info['owner_id']} — solving captcha...")
        token = captcha.solve_recaptcha_v3(
            website_url=info["url"] + "/pricing",
            website_key=meta.RECAPTCHA_V3_SITE_KEY,
            page_action="", min_score=0.3, is_enterprise=False)
        print(f"  captcha ok ({len(token)} chars) — subscribing...")
        res = meta.subscribe(creds, info["api_id"], basic["version_id"], info["owner_id"], token)
        rec["result"] = res
        rec["ok"] = bool(res.get("subscriptionId"))
        print(f"  -> {res}")
    except Exception as e:
        rec["error"] = f"{type(e).__name__}: {e}"
        print("  x", rec["error"])
    results.append(rec)
    json.dump(results, open("subscribe_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)

json.dump(results, open("subscribe_results.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
ok = [r for r in results if r.get("ok")]
print(f"\n===== DONE: {len(ok)}/{len(results)} subscribed =====")
for r in results:
    tag = "OK " if r.get("ok") else "FAIL"
    print(f"  [{tag}] {r['slug']:44} {r.get('free_quota','?'):16} {r.get('error','')}")
