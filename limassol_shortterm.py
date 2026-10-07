"""Целевой поиск КРАТКОСРОЧНОЙ аренды (от 1 месяца) в Лимасоле.

Отличие от limassol_august.py: запросы заточены под краткосрок, и признак срока
берётся из описания по явным фразам (min 1 month / short term / no contract),
а НЕ по "per month" (это просто цена).
"""
import json, csv, re, time
import rapidapi_call as rc, rapidapi_hub as hub, rapidapi_meta as meta

HOST = "facebook-marketplace-scraper-api.p.rapidapi.com"
LAT, LNG = "34.675", "33.0333"
QUERIES = ["short term rent", "short term rental apartment", "monthly rent no contract",
           "holiday rental apartment", "βραχυχρόνια ενοικίαση", "furnished monthly rental",
           "rent for 1 month", "airbnb apartment"]
PAGES, BUDGET, ENRICH = 3, 40, 40

# ЯВНЫЙ краткосрок (не "per month" — это цена)
SHORT_OK = re.compile(r"(short[- ]?term|short stay|min(?:imum)?\.? ?(?:stay|rental|period)?[^.]{0,20}?"
                      r"(?:1|one) month|from (?:1|one) month|monthly basis|no (?:long[- ]?term )?contract|"
                      r"weekly|holiday|per night|βραχυχρ|για ένα μήνα|εβδομαδ)", re.I)
LONG_BAD = re.compile(r"(min(?:imum)?[^.]{0,25}(?:1|one|2|two|12)[- ]?(?:year|years)|long[- ]?term (?:only|agreement|rent)|"
                      r"[12][- ]?year (?:lease|contract)|ετήσι|μακροχρ)", re.I)
HOUSING = re.compile(r"(bed|studio|apartment|flat|house|maisonette|penthouse|condo|διαμερ|σπιτ|υπνοδ|κατοικ)", re.I)
JUNK = re.compile(r"(\bcar\b|αυτοκιν|\bbike\b|for sale|προς πωλη|warehouse|αποθηκ|\boffice\b|γραφει|αίθουσ)", re.I)
LIMASSOL = re.compile(r"(limassol|λεμεσ|lemesos|germasog|mesa geitonia|ypsonas|polemid|zakaki|kapsalos|"
                      r"agios athanas|agios tychon|parekklisia|mouttagiaka|pissouri|akrotiri)", re.I)
BAD_CITY = re.compile(r"(nicosia|λευκωσ|paphos|p[áa]fos|larnaca|λαρνακ|kyrenia|κερυνει|protaras|ayia napa)", re.I)
PHONE = re.compile(r"(?:\+?357[\s-]?)?([2579]\d{7})")


def safe(path, params, key, tries=3):
    for _ in range(tries):
        try:
            return rc.call(HOST, path, params=params, key=key, timeout=60)
        except Exception:
            time.sleep(2)
    return None


def main():
    key = meta.projects(hub.Creds.from_curl("curl.txt"))[0]["key"]
    items, used = {}, 0
    for q in QUERIES:
        cursor = None
        for _ in range(PAGES):
            if used >= BUDGET:
                break
            p = {"query": q, "filter_location_latitude": LAT, "filter_location_longitude": LNG,
                 "filter_radius_km": "25", "filter_price_upper_bound": "2500",
                 "commerce_search_sort_by": "CREATION_TIME_DESCEND"}
            if cursor:
                p["end_cursor"] = cursor
            r = safe("/get_facebook_marketplace_items_listing", p, key)
            used += 1
            if not r or r.status_code != 200:
                break
            d = r.json().get("data") or {}
            for it in d.get("items") or []:
                if it.get("id"):
                    items[it["id"]] = it
            pi = d.get("page_info") or {}
            cursor = pi.get("end_cursor")
            if not pi.get("has_next"):
                break
        print(f"  [{q}] {len(items)} уник. / {used} зап.")

    cands = []
    for it in items.values():
        title = it.get("marketplace_listing_title") or ""
        rg = (it.get("location") or {}).get("reverse_geocode") or {}
        city = (rg.get("city_page") or {}).get("display_name") or rg.get("city") or ""
        if BAD_CITY.search(city) or not LIMASSOL.search(city):
            continue
        if JUNK.search(title) or not HOUSING.search(title):
            continue
        lp = it.get("listing_price") or {}
        try:
            price = float(lp.get("amount"))
        except (TypeError, ValueError):
            continue
        if price <= 50:
            continue
        cands.append({"id": it["id"], "title": title, "price_eur": price, "city": city,
                      "url": it.get("listingUrl")})
    cands.sort(key=lambda r: r["price_eur"])
    print(f"\nКандидатов (Лимасол, жильё): {len(cands)}  | запросов {used}")

    out = []
    for i, c in enumerate(cands[:ENRICH], 1):
        r = safe("/get_listing_item_details", {"listing_id": c["id"]}, key)
        used += 1
        desc = ""
        if r and r.status_code == 200:
            desc = (((r.json().get("data") or {}).get("item_details") or {})
                    .get("redacted_description") or {}).get("text") or ""
        txt = f"{c['title']} {desc}"
        c.update(phone=", ".join(dict.fromkeys(PHONE.findall(re.sub(r"(?<=\d)[\s\-.](?=\d)", "", txt)))),
                 short_ok=bool(SHORT_OK.search(txt)), long_bad=bool(LONG_BAD.search(txt)),
                 description=desc.replace("\n", " ").strip())
        out.append(c)
        flag = "SHORT-OK" if c["short_ok"] and not c["long_bad"] else ("long" if c["long_bad"] else "?")
        print(f"  [{i}/{min(len(cands), ENRICH)}] EUR{int(c['price_eur']):<5} {flag:<9} {c['title'][:44]}")

    json.dump(out, open("limassol_shortterm.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    with open("limassol_shortterm.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["price_eur", "phone", "short_ok", "long_bad", "title",
                                          "city", "url", "description", "id"], extrasaction="ignore")
        w.writeheader(); w.writerows(out)

    good = [r for r in out if r["short_ok"] and not r["long_bad"]]
    print(f"\n=== ИТОГ (потрачено {used}) ===")
    print(f"Проверено: {len(out)} | ЯВНО краткосрок: {len(good)} | явно длительные: {sum(r['long_bad'] for r in out)}")
    for r in good:
        print(f"\nEUR{int(r['price_eur'])} | {r['phone'] or 'FB msg'} | {r['title'][:60]}")
        print(f"  {r['url']}")
        m = SHORT_OK.search(r["description"])
        if m:
            i = m.start()
            print(f"  ...{r['description'][max(0, i-80):i+140]}...")


if __name__ == "__main__":
    main()
