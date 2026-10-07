"""Лос-Анджелес: студия/1BR краткосрок 17 окт -> 31 окт / 7 ноя.

FB Marketplace (oussemaf через RapidAPI) + Craigslist sublets (прямой HTML, бесплатно).
Срок определяется по описанию: явный краткосрок/саблет/даты окт-ноя, минус "12 month lease".
Запуск: python la_short.py  -> la_short.csv
"""
import csv, re, time, requests
import rapidapi_call as rc, rapidapi_hub as hub, rapidapi_meta as meta

HOST = "facebook-marketplace-scraper-api.p.rapidapi.com"
LAT, LNG = "34.0522", "-118.2437"
QUERIES = ["sublet studio", "sublet 1 bedroom", "short term rental", "furnished studio monthly",
           "sublease apartment", "month to month studio"]
PAGES, BUDGET, ENRICH = 2, 16, 30
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

SHORT = re.compile(r"(sublet|sublease|short[- ]?term|month[- ]to[- ]month|weekly|per night|furnished|"
                   r"2 weeks|two weeks|3 weeks|1 month|one month|flexible dates|travel nurse)", re.I)
DATES = re.compile(r"\b(oct(?:ober)?\.?\s*\d{1,2}|nov(?:ember)?\.?\s*\d{1,2}|10/\d{1,2}|11/\d{1,2}|"
                   r"mid[- ]october|end of october|early november)\b", re.I)
LONG = re.compile(r"(12[- ]month lease|1[- ]year lease|one year lease|minimum (?:of )?(?:6|12) months|"
                  r"lease term: ?12|long[- ]term only)", re.I)
TYPE_OK = re.compile(r"(studio|1 ?b(?:d|r|ed)|one bed|1 bedroom|bachelor|apartment|apt|guest ?house|casita|adu|condo)", re.I)
TYPE_BAD = re.compile(r"(\b[2-9] ?b(?:d|r|ed)|\b[2-9] bedroom|room for rent|private room|shared|roommate|"
                      r"\broom\b|parking|garage|office|storage|for sale|car\b)", re.I)
PHONE = re.compile(r"\(?\b([2-9]\d{2})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})\b")


def phones(t):
    return ", ".join(dict.fromkeys("-".join(m) for m in PHONE.findall(t)))


def classify(txt):
    if LONG.search(txt):
        return "long"
    return "short" if SHORT.search(txt) or DATES.search(txt) else "?"


def fb():
    try:
        key = meta.projects(hub.Creds.from_curl("curl.txt"))[0]["key"]
    except Exception as e:
        print("FB: нет ключа RapidAPI:", e); return []
    items, used = {}, 0
    for q in QUERIES:
        cur = None
        for _ in range(PAGES):
            if used >= BUDGET:
                break
            p = {"query": q, "filter_location_latitude": LAT, "filter_location_longitude": LNG,
                 "filter_radius_km": "40", "filter_price_upper_bound": "5000",
                 "commerce_search_sort_by": "CREATION_TIME_DESCEND"}
            if cur:
                p["end_cursor"] = cur
            try:
                r = rc.call(HOST, "/get_facebook_marketplace_items_listing", params=p, key=key, timeout=60)
            except Exception:
                break
            used += 1
            if r.status_code != 200:
                print("  FB", r.status_code, r.text[:120]); break
            d = r.json().get("data") or {}
            for it in d.get("items") or []:
                items[it.get("id")] = it
            pi = d.get("page_info") or {}
            cur = pi.get("end_cursor")
            if not pi.get("has_next"):
                break
        print(f"  FB [{q}] {len(items)} уник. / {used} зап.")

    cands = []
    for it in items.values():
        t = it.get("marketplace_listing_title") or ""
        if TYPE_BAD.search(t):
            continue
        try:
            price = float((it.get("listing_price") or {}).get("amount"))
        except (TypeError, ValueError):
            continue
        rg = (it.get("location") or {}).get("reverse_geocode") or {}
        cands.append({"src": "facebook", "id": it["id"], "title": t, "price": price,
                      "area": rg.get("city") or "", "url": f"https://www.facebook.com/marketplace/item/{it['id']}/"})
    cands.sort(key=lambda c: c["price"])
    for c in cands[:ENRICH]:
        try:
            r = rc.call(HOST, "/get_listing_item_details", params={"listing_id": c["id"]}, key=key, timeout=60)
            desc = (((r.json().get("data") or {}).get("item_details") or {})
                    .get("redacted_description") or {}).get("text") or ""
        except Exception:
            desc = ""
        c["desc"] = desc.replace("\n", " ")
    return cands[:ENRICH]


def craigslist():
    base = "https://losangeles.craigslist.org/search/sub"
    html = requests.get(base, params={"max_bedrooms": 1}, headers=UA, timeout=30).text
    rows = re.findall(r'<li class="cl-static-search-result" title="([^"]*)">\s*<a href="([^"]+)">(.*?)</li>', html, re.S)
    print(f"  CL: {len(rows)} объявлений в выдаче")
    out = []
    for title, url, body in rows:
        pm = re.search(r'class="price">\$([\d,]+)', body)
        loc = re.search(r'class="location">\s*([^<]*)', body)
        out.append({"src": "craigslist", "id": url.rsplit("/", 1)[-1].split(".")[0], "title": title,
                    "price": float(pm.group(1).replace(",", "")) if pm else 0,
                    "area": (loc.group(1).strip() if loc else ""), "url": url})
    for c in out:
        try:
            h = requests.get(c["url"], headers=UA, timeout=20).text
            body = re.search(r'<section id="postingbody">(.*?)</section>', h, re.S)
            attrs = " ".join(re.findall(r'<span class="attr[^"]*"[^>]*>(.*?)</span>', h, re.S)) + " " + \
                " ".join(re.findall(r'class="housing_movein_now[^"]*"[^>]*>(.*?)<', h, re.S))
            txt = re.sub(r"<[^>]+>", " ", (body.group(1) if body else "") + " " + attrs)
            c["desc"] = re.sub(r"\s+", " ", txt).replace("QR Code Link to This Post", "").strip()
        except Exception:
            c["desc"] = ""
        time.sleep(0.5)
    return out


def main():
    res = []
    for fn in (fb, craigslist):
        try:
            res += fn()
        except Exception as e:
            print(fn.__name__, "упал:", e)
    for c in res:
        txt = f"{c['title']} {c.get('desc', '')}"
        c["type_ok"] = bool(TYPE_OK.search(txt)) and not TYPE_BAD.search(c["title"])
        c["term"] = classify(txt)
        c["dates"] = ", ".join(dict.fromkeys(m.lower() for m in DATES.findall(txt)))
        c["phone"] = phones(txt)
    res = [c for c in res if c["type_ok"] and c["term"] != "long" and c["price"] > 100]
    res.sort(key=lambda c: (c["term"] != "short", not c["dates"], c["price"]))
    with open("la_short.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["src", "price", "term", "dates", "phone", "title", "area", "url", "desc", "id"],
                           extrasaction="ignore")
        w.writeheader(); w.writerows(res)
    print(f"\nПодходящих: {len(res)} -> la_short.csv")
    for c in res[:40]:
        print(f"{c['src'][:2]} ${int(c['price']):<5} {c['term']:<5} {c['dates'][:28]:<28} {c['title'][:50]}\n   {c['url']}")


if __name__ == "__main__":
    main()
