"""Обогатить идеальные (EUR1000-1300) объявления Лимасола деталями: описание, телефон,
категория. Читает limassol_housing.json, дёргает /get_listing_item_details по каждому.
Пишет limassol_ideal_enriched.csv/json.  Расход: 1 запрос на объявление."""
import os, json, csv, re, time
import rapidapi_call as rc
import rapidapi_hub as hub
import rapidapi_meta as meta

HOST = "facebook-marketplace-scraper-api.p.rapidapi.com"
IDEAL = (1000, 1300)


def safe(host, path, params, key, attempts=3):
    for i in range(attempts):
        try:
            return rc.call(host, path, params=params, key=key, timeout=60)
        except Exception:
            time.sleep(2)
    return None


def phones(text):
    if not text:
        return ""
    compact = re.sub(r"(?<=\d)[\s\-. ](?=\d)", "", text)
    found = [n for n in re.findall(r"(?:\+?357)?([2579]\d{7})", compact)]
    return ", ".join(dict.fromkeys(found))


def main():
    creds = hub.Creds.from_curl("curl.txt")
    key = meta.projects(creds)[0]["key"]
    with open("limassol_housing.json", encoding="utf-8") as fh:
        rows = json.load(fh)
    ideal = [r for r in rows if IDEAL[0] <= r["price_eur"] <= IDEAL[1]]
    print(f"Обогащаю {len(ideal)} объявлений (EUR{IDEAL[0]}-{IDEAL[1]})...")

    out = []
    for i, r in enumerate(ideal, 1):
        resp = safe(HOST, "/get_listing_item_details", {"listing_id": r["id"]}, key)
        desc = cat = ""
        if resp and resp.status_code == 200:
            det = (resp.json().get("data") or {}).get("item_details") or {}
            desc = ((det.get("redacted_description") or {}).get("text")) or ""
            cat = det.get("marketplace_listing_category_name") or ""
        rec = dict(r)
        rec["category"] = cat
        rec["phone"] = phones(desc)
        rec["description"] = desc.replace("\n", " ").strip()
        out.append(rec)
        print(f"  [{i}/{len(ideal)}] EUR{int(r['price_eur'])} {cat or '?':18} tel={rec['phone'] or '-':22} {(r['title'] or '')[:40]}")

    out.sort(key=lambda r: r["price_eur"])
    with open("limassol_ideal_enriched.json", "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    with open("limassol_ideal_enriched.csv", "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["price_eur", "formatted", "title", "category", "phone",
                                           "city", "url", "description", "id"], extrasaction="ignore")
        w.writeheader()
        for r in out:
            w.writerow(r)
    rentals = sum(1 for r in out if "rent" in (r["category"] or "").lower())
    print(f"\nГотово. Обогащено: {len(out)}; подтверждённая категория 'аренда': {rentals}")
    print("Файлы: limassol_ideal_enriched.csv / .json")


if __name__ == "__main__":
    main()
