"""Отфильтровать собранные объявления до: Лимасол + жильё. Читает limassol_rentals.json,
пишет limassol_housing.csv/json. Без обращений к API."""
import json, csv, re

# другие районы — исключаем
OTHER_DISTRICT = re.compile(r"(nicosia|λευκωσ|paphos|p[áa]fos|larnaca|λαρνακ|kyrenia|κερυνει|"
                            r"famagusta|ammochostos|strovolos|lakatamia|latsia|aglangia|egkomi|"
                            r"aradippou|voroklini|livadia|perivolia|kiti|xylophaghou|gönyeli|"
                            r"lapithos|karmi|tala|pegeia|chlorak|mesogi|emba|polemi\b|kathikas|konia|agios dometios)", re.I)
# Лимасольский район: по суффиксу или по имени пригорода
LIMASSOL_SUFFIX = re.compile(r"(limassol|λεμεσ|lemesos)", re.I)
LIMASSOL_SUBURBS = {
    "germasogeia", "germasoyia", "mesa geitonia", "ypsonas", "agios athanasios",
    "agios tychon", "agios tychonas", "parekklisia", "lofou", "mouttagiaka",
    "kato polemidhia", "pano polemidia", "polemidhia", "polemidia", "fasoula",
    "palodia", "souni", "pissouri", "pentakomo", "moni", "monagroulli", "kolossi",
    "erimi", "akrotiri", "trachoni", "kantou", "zakaki", "kapsalos", "linopetra",
    "agia fyla", "columbia", "potamos germasogeias", "apesia", "episkopi",
}


def in_limassol(city: str) -> bool:
    c = (city or "").strip().lower()
    if OTHER_DISTRICT.search(c):
        return False
    if LIMASSOL_SUFFIX.search(c):
        return True
    bare = c.split(",")[0].strip()
    return bare in LIMASSOL_SUBURBS
INCLUDE = re.compile(r"(bed|bedroom|studio|apartment|flat|house|maisonette|penthouse|condo|bungalow|"
                     r"διαμερ|σπιτ|υπνοδ|κατοικ|ενοικ|roof|room)", re.I)
EXCLUDE = re.compile(r"(\bcar\b|αυτοκιν|electric bike|\bbike\b|business for|for sale|προς πωλη|\bdeed\b|"
                     r"warehouse|αποθηκ|\boffice\b|γραφει|φροντιστ|shop|κατασ|μηχαν)", re.I)

with open("limassol_rentals.json", encoding="utf-8") as fh:
    rows = json.load(fh)

kept = []
for r in rows:
    title = r.get("title") or ""
    if not in_limassol(r.get("city")):
        continue
    if EXCLUDE.search(title):
        continue
    if not INCLUDE.search(title):
        continue
    kept.append(r)

kept.sort(key=lambda r: r["price_eur"])
ideal = [r for r in kept if 1000 <= r["price_eur"] <= 1300]

with open("limassol_housing.json", "w", encoding="utf-8") as fh:
    json.dump(kept, fh, ensure_ascii=False, indent=2)
with open("limassol_housing.csv", "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=["price_eur", "formatted", "ideal", "title", "city", "url", "id", "photo"])
    w.writeheader()
    for r in kept:
        w.writerow(r)

print(f"Лимасол, только жильё, <=EUR1500: {len(kept)}")
print(f"  из них EUR1000-1300 (идеал): {len(ideal)}")
print(f"  <EUR1000: {sum(1 for r in kept if r['price_eur'] < 1000)}")
print(f"  EUR1301-1500: {sum(1 for r in kept if 1301 <= r['price_eur'] <= 1500)}")
print(f"Файлы: limassol_housing.csv / .json\n")
print("--- ИДЕАЛ EUR1000-1300, Лимасол, жильё ---")
for r in ideal:
    print(f"  EUR{int(r['price_eur']):<5} {(r['title'] or '')[:52]:<52} {r['url']}")
