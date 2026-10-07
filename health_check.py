"""Health-check subscribed YouTube-email finders end-to-end: discover route, call
with a known channel (MrBeast), report HTTP + whether an email came back."""
import rapidapi_call as cm, rapidapi_meta as meta, rapidapi_hub as hub
import requests, re, json, time

creds = hub.Creds.from_curl("curl.txt")
key = meta.projects(creds)[0]["key"]
H = {"user-agent": creds.user_agent or "Mozilla/5.0", "cookie": creds.cookie, "accept": "text/html"}
S = requests.Session()

MRBEAST_ID = "UCX6OQ3DkcsbYNE6H8uQQuVA"
MRBEAST_HANDLE = "MrBeast"

# core youtube email finders (user/slug)
CORE = [
    ("social-master-social-master-default", "youtube-channel-email-contact-finder1"),
    ("wotokol01", "social-channel-email-finder"),
    ("derekhefley", "youtube-instant-email-scraper"),
    ("gabriel-oefDU7iJA", "youtube-channel-email-socials-finder"),
    ("dataocean", "the-better-youtube-channel-details"),
    ("w18515997", "youtube-email-finder"),
    ("jaroslavvorobey", "find-youtuber-emails-winfluencer"),
    ("alexanderxbx", "youtube362"),
]


def routes_for(user, slug):
    try:
        t = S.get(f"https://rapidapi.com/{user}/api/{slug}", headers=H, timeout=90).text
    except Exception:
        return None, []
    host = next(iter(sorted(set(re.findall(r'([a-z0-9\-]+\.p\.rapidapi\.com)', t)))), f"{slug}.p.rapidapi.com")
    routes = sorted(set(re.findall(r'\\"route\\":\\"(/[^\\"]{0,80})\\"', t)))
    return host, routes


def fill(route):
    return (route
            .replace("{channel_id}", MRBEAST_ID).replace("{channelId}", MRBEAST_ID)
            .replace("{username}", MRBEAST_HANDLE).replace("{handle}", MRBEAST_HANDLE)
            .replace("{id}", MRBEAST_ID))


EMAIL_RE = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
report = []
for user, slug in CORE:
    host, routes = routes_for(user, slug)
    rec = {"slug": slug, "host": host, "routes": routes, "tries": []}
    print(f"\n### {slug}  host={host}\n  routes={routes}")
    # pick simple GET routes first (single-channel lookup)
    getable = [r for r in routes if "{" in r or r.count("/") <= 2]
    for route in getable[:3]:
        path = fill(route)
        # if still has {param}, try as query with channel_id/username
        method = "GET"
        try:
            r = cm.call(host, path, method=method, key=key, timeout=35)
            emails = sorted(set(EMAIL_RE.findall(r.text)))
            emails = [e for e in emails if "rapidapi" not in e and "example" not in e]
            rec["tries"].append({"path": path, "status": r.status_code,
                                 "emails": emails[:5], "n_emails": len(emails),
                                 "snippet": r.text[:160]})
            print(f"  {method} {path} -> {r.status_code}  emails={len(emails)} {emails[:3]}")
            if r.status_code == 200 and emails:
                break
        except Exception as e:
            rec["tries"].append({"path": path, "error": f"{type(e).__name__}"})
            print(f"  {method} {path} -> ERR {type(e).__name__}")
    report.append(rec)

json.dump(report, open("health_report.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("\n\n===== HEALTH SUMMARY =====")
for r in report:
    best = None
    for t in r["tries"]:
        if t.get("status") == 200 and t.get("n_emails"):
            best = t; break
        if t.get("status") == 200 and best is None:
            best = t
    if best and best.get("n_emails"):
        print(f"  LIVE   {r['slug']:44} -> {best['n_emails']} email(s) e.g. {best['emails'][:2]}")
    elif best:
        print(f"  200/no-email {r['slug']:44} ({best.get('snippet','')[:50]})")
    else:
        st = [t.get('status') or t.get('error') for t in r['tries']]
        print(f"  DOWN?  {r['slug']:44} states={st}")
