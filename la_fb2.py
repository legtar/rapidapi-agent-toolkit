"""Второй проход FB Marketplace по LA: краткосрочные запросы, без уже проверенных id.
Запуск: python la_fb2.py -> la_fb2.csv"""
import csv, re
import rapidapi_call as rc, rapidapi_hub as hub, rapidapi_meta as meta
from la_short import HOST, LAT, LNG, TYPE_BAD, LONG, SHORT, DATES

QUERIES = ["weekly rental", "airbnb", "travel nurse housing", "temporary housing",
           "vacation rental", "furnished short term", "2 weeks rent", "guest house short term"]
SEEN = {r["id"] for r in csv.DictReader(open("la_short.csv", encoding="utf-8"))}
JUNK = re.compile(r"(parking|garage|storage|office|recording|podcast|salon|beauty|work only|studio space|"
                  r"photo studio|event|for sale|\broom\b|shared)", re.I)
key = meta.projects(hub.Creds.from_curl("curl.txt"))[0]["key"]

items, used = {}, 0
for q in QUERIES:
    cur = None
    for _ in range(2):
        p = {"query": q, "filter_location_latitude": LAT, "filter_location_longitude": LNG,
             "filter_radius_km": "40", "filter_price_upper_bound": "3000",
             "commerce_search_sort_by": "CREATION_TIME_DESCEND"}
        if cur: p["end_cursor"] = cur
        try: r = rc.call(HOST, "/get_facebook_marketplace_items_listing", params=p, key=key, timeout=60)
        except Exception: break
        used += 1
        if r.status_code != 200: print(q, r.status_code, r.text[:100]); break
        d = r.json().get("data") or {}
        for it in d.get("items") or []: items[it.get("id")] = it
        pi = d.get("page_info") or {}; cur = pi.get("end_cursor")
        if not pi.get("has_next"): break
    print(f"[{q}] {len(items)} / {used} зап.")

cands = []
for it in items.values():
    t = it.get("marketplace_listing_title") or ""
    if it["id"] in SEEN or TYPE_BAD.search(t) or JUNK.search(t): continue
    try: price = float((it.get("listing_price") or {}).get("amount"))
    except (TypeError, ValueError): continue
    if price < 40: continue
    rg = (it.get("location") or {}).get("reverse_geocode") or {}
    cands.append({"id": it["id"], "title": t, "price": price, "area": rg.get("city") or "",
                  "url": f"https://www.facebook.com/marketplace/item/{it['id']}/"})
print("новых кандидатов:", len(cands))
for c in cands[:40]:
    try:
        r = rc.call(HOST, "/get_listing_item_details", params={"listing_id": c["id"]}, key=key, timeout=60)
        c["desc"] = ((((r.json().get("data") or {}).get("item_details") or {}).get("redacted_description") or {}).get("text") or "").replace("\n", " ")
    except Exception: c["desc"] = ""
    used += 1
    txt = c["title"] + " " + c["desc"]
    c["term"] = "long" if LONG.search(txt) else "short" if SHORT.search(txt) or DATES.search(txt) else "?"
cands = cands[:40]
with open("la_fb2.csv", "w", encoding="utf-8", newline="") as f:
    w = csv.DictWriter(f, fieldnames=["price", "term", "area", "title", "url", "desc", "id"], extrasaction="ignore")
    w.writeheader(); w.writerows(cands)
print("запросов всего:", used)
for c in sorted(cands, key=lambda c: (c["term"] != "short", c["price"])):
    print(f"\n${int(c['price'])} {c['term']} {c['area']} | {c['title'][:50]}\n  {c['url']}\n  ~ {c['desc'][:260]}")
