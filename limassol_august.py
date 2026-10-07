"""Аренда в Лимасоле: сбор + детали (телефоны) + пометка "подходит с 29 августа".

FB не отдаёт дату заезда структурно — ищем упоминания в описании (august/αύγουστο/short term/monthly).
Запуск: python limassol_august.py
"""
import json, csv, re, time
import rapidapi_call as rc, rapidapi_hub as hub, rapidapi_meta as meta

HOST = "facebook-marketplace-scraper-api.p.rapidapi.com"
LAT, LNG = "34.675", "33.0333"
MAX_PRICE = 2000
QUERIES = ["apartment for rent", "flat for rent", "monthly rental", "short term rent",
           "apartment august", "studio for rent", "ενοικίαση διαμέρισμα"]
PAGES = 4
BUDGET = 150          # предохранитель по квоте (осталось ~199)
ENRICH_MAX = 90       # сколько объявлений добить деталями

AUG = re.compile(r"(august|αύγουστ|avgoust|29[./ ]?08|29[./ ]?aug|1[./ ]?9|september|σεπτ)", re.I)
SHORT = re.compile(r"(short[- ]?term|monthly|per month|month(?:ly)? rent|βραχυχρ|μηνιαί)", re.I)
LONG = re.compile(r"(long[- ]?term|μακροχρ|year|annual|12 month)", re.I)
HOUSING = re.compile(r"(bed|studio|apartment|flat|house|maisonette|penthouse|condo|"
                     r"διαμερ|σπιτ|υπνοδ|κατοικ|ενοικ)", re.I)
JUNK = re.compile(r"(\bcar\b|αυτοκιν|\bbike\b|for sale|προς πωλη|warehouse|αποθηκ|"
                  r"\boffice\b|γραφει|business for)", re.I)
LIMASSOL = re.compile(r"(limassol|λεμεσ|lemesos|germasog|mesa geitonia|ypsonas|polemid|"
                      r"zakaki|kapsalos|agios athanas|agios tychon|parekklisia|mouttagiaka)", re.I)
BAD_CITY = re.compile(r"(nicosia|λευκωσ|paphos|p[áa]fos|larnaca|λαρνακ|kyrenia|κερυνει)", re.I)
PHONE = re.compile(r"(?:\+?357[\s-]?)?([2579]\d{7})")


def safe(path, params=None, key=None, tries=3):
    for _ in range(tries):
        try:
            return rc.call(HOST, path, params=params, key=key, timeout=60)
        except Exception:
            time.sleep(2)
    return None


def main():
    key = meta.projects(hub.Creds.from_curl("curl.txt"))[0]["key"]
    used = 0
    items = {}

    for q in QUERIES:
        cursor = None
        for _ in range(PAGES):
            if used >= BUDGET:
                break
            p = {"query": q, "filter_location_latitude": LAT, "filter_location_longitude": LNG,
                 "filter_radius_km": "25", "filter_price_upper_bound": str(MAX_PRICE),
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
        print(f"  [{q}] уникальных: {len(items)}  запросов: {used}")

    # фильтр: Лимасол + жильё
    cands = []
    for it in items.values():
        if it.get("is_sold") or it.get("is_pending"):
            continue
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
        cands.append({"id": it["id"], "title": title, "price_eur": price,
                      "formatted": lp.get("formatted_amount"), "city": city,
                      "url": it.get("listingUrl")})
    cands.sort(key=lambda r: r["price_eur"])
    print(f"\nЖильё в Лимасоле <= EUR{MAX_PRICE}: {len(cands)}  (потрачено {used})")

    # детали -> телефон + признаки срока
    out = []
    for i, c in enumerate(cands[:ENRICH_MAX], 1):
        if used >= BUDGET + ENRICH_MAX:
            break
        r = safe("/get_listing_item_details", {"listing_id": c["id"]}, key)
        used += 1
        desc = cat = ""
        if r and r.status_code == 200:
            det = (r.json().get("data") or {}).get("item_details") or {}
            desc = ((det.get("redacted_description") or {}).get("text")) or ""
            cat = det.get("marketplace_listing_category_name") or ""
        txt = f"{c['title']} {desc}"
        c.update(category=cat,
                 phone=", ".join(dict.fromkeys(PHONE.findall(re.sub(r"(?<=\d)[\s\-.](?=\d)", "", txt)))),
                 mentions_august=bool(AUG.search(txt)),
                 short_term=bool(SHORT.search(txt)),
                 long_term=bool(LONG.search(txt)),
                 description=desc.replace("\n", " ").strip())
        out.append(c)
        print(f"  [{i}/{min(len(cands), ENRICH_MAX)}] EUR{int(c['price_eur']):<5} tel={c['phone'] or '-':12} "
              f"{'AUG' if c['mentions_august'] else '   '} {'SHORT' if c['short_term'] else '     '} {c['title'][:38]}")

    with open("limassol_august.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    with open("limassol_august.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["price_eur", "formatted", "phone", "mentions_august", "short_term",
                                          "long_term", "title", "category", "city", "url", "description", "id"],
                           extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    with_phone = [r for r in out if r["phone"]]
    print(f"\n=== ИТОГ (потрачено {used} запросов) ===")
    print(f"Всего собрано: {len(out)} | с телефоном: {len(with_phone)} | "
          f"упоминают август/сентябрь: {sum(r['mentions_august'] for r in out)} | "
          f"кратко/помесячно: {sum(r['short_term'] for r in out)}")
    print("Файлы: limassol_august.csv / .json")
    print("\n--- С ТЕЛЕФОНОМ (можно торговаться) ---")
    for r in with_phone:
        tags = ("AUG " if r["mentions_august"] else "") + ("SHORT " if r["short_term"] else "") + ("LONG" if r["long_term"] else "")
        print(f"  EUR{int(r['price_eur']):<5} {r['phone']:<22} {tags:<12} {r['title'][:42]}")
        print(f"        {r['url']}")


if __name__ == "__main__":
    main()
