"""Проверка кандидатов LA: живо ли объявление, полный текст, дата, признаки скама.
+ доп. выдача Craigslist vacation rentals (vac). Запуск: python la_verify.py"""
import re, time, requests, json
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
SCAM = re.compile(r"(out of (the )?country|missionary|wire transfer|western union|zelle before|deposit before|"
                  r"keys? (will be )?(mailed|shipped)|airbnb (will|to) handle|god bless|my husband and i are|abroad)", re.I)
SHORT = ["tXznCvYfktbm5KJCRNvdid","g1w1CrH91EgZjNaEFNr2dX","bs574BCWLRZe8cMyx11E5s","4N44WCtuEfbYq4Zwfy1gKc",
         "3kr6bXEJHEhxsTPndLWg52","9YEjHW3sWQiWRLqbyRpjW8","ubMpzN3ZZUucoFtWWu9Zo9","pmnewBFbd5QmeJ7spnxQS2",
         "5dcFRPQdLHRJxj8obHh4Fe","bC2UpRbkueFLfxATraor9z","aMrW5yywrExgfJ3jXeZ7Aj","fHh7qnPTgSm87wExJ2gA6j",
         "3T1fZPEyKn3XgahdgogspB","a8PuxVN6tq3WXrpUTTzTMw","v4hhqDPUGefz4CJae5SV11","qh5WDWUvBVoHbbht9C5mwb"]

def page(url):
    r = requests.get(url, headers=UA, timeout=25)
    h = r.text
    body = re.search(r'<section id="postingbody">(.*?)</section>', h, re.S)
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body.group(1) if body else "")).replace("QR Code Link to This Post", "").strip()
    attrs = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", " ".join(re.findall(r'<div class="attrgroup">(.*?)</div>', h, re.S))))
    posted = re.findall(r'datetime="([^"]+)"', h)
    title = re.search(r'<span id="titletextonly">(.*?)</span>', h)
    price = re.search(r'<span class="price">([^<]+)', h)
    gone = r.status_code != 200 or "has been deleted" in h or "has expired" in h or "flagged for removal" in h
    return {"url": r.url, "status": "GONE" if gone else "live", "title": title.group(1) if title else "",
            "price": price.group(1) if price else "", "posted": posted[0][:10] if posted else "",
            "updated": posted[-1][:10] if posted else "", "attrs": attrs.strip(), "text": txt,
            "scam": ", ".join(sorted({m.group(0).lower() for m in SCAM.finditer(txt)}))}

out = {}
# доп. выдача: vacation rentals + саблеты без фильтра спален (у части нет атрибута)
for cat in ("vac", "sub"):
    h = requests.get(f"https://losangeles.craigslist.org/search/{cat}", headers=UA, timeout=30).text
    rows = re.findall(r'<li class="cl-static-search-result" title="([^"]*)">\s*<a href="([^"]+)">', h)
    print(cat, len(rows))
    for t, u in rows:
        if cat == "vac" or re.search(r"studio|1 ?b|one bed|bungalow|cottage|casita|guest ?house|adu", t, re.I):
            out[u.rsplit("/",1)[-1]] = u
for s in SHORT:
    out.setdefault(s, f"https://www.craigslist.org/view/d/x/{s}")
res = []
for k, u in out.items():
    try:
        res.append(page(u))
    except Exception as e:
        res.append({"url": u, "status": f"ERR {e}"})
    time.sleep(0.4)
json.dump(res, open("la_verify.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("checked", len(res), "gone", sum(r["status"] != "live" for r in res))
