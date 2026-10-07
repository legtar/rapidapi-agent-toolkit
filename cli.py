#!/usr/bin/env python3
"""
CLI над RapidAPI Hub — поиск провайдеров и вызов подписанных API без веб-интерфейса.

Команды:
  categories  — распределение результатов по категориям + total (быстрая проверка кредов)
  search      — таблица найденных API (name / provider / category / pricing / popularity / url)
  export      — массовый сбор с пагинацией в CSV или JSON (локальный каталог)
  call        — вызвать эндпоинт ПОДПИСАННОГО API через прокси (X-RapidAPI-Key)
  snippet     — сгенерировать готовый код вызова API

Креды поиска берутся из cURL-файла (по умолчанию ./curl.txt) — см. README.md.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys

import rapidapi_hub as hub
import rapidapi_call as call_mod
import rapidapi_meta as meta
import rapidapi_captcha as captcha


def _load_creds(path: str) -> hub.Creds:
    try:
        return hub.Creds.from_curl(path)
    except FileNotFoundError:
        sys.exit(f"Не найден файл cURL: {path}. Сохрани запрос searchApis из DevTools "
                 f"(Copy as cURL) в этот файл. См. curl.example.txt / README.md.")
    except ValueError as e:
        sys.exit(str(e))


def _trunc(s, n):
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def cmd_categories(args):
    creds = _load_creds(args.curl)
    try:
        ov = hub.overview(creds, args.term)
    except hub.RapidApiError as e:
        sys.exit(str(e))
    print(f"Запрос: {args.term!r}   total = {ov['total']}\n")
    print(f"{'КАТЕГОРИЯ':<40} {'КОЛ-ВО':>7}")
    print("-" * 48)
    for c in ov["facets"]:
        print(f"{_trunc(c.get('key'), 40):<40} {c.get('count', 0):>7}")


def cmd_search(args):
    creds = _load_creds(args.curl)
    try:
        rows = hub.search_apis(creds, args.term, category=args.category,
                               limit=args.limit, first=args.first)
    except hub.RapidApiError as e:
        sys.exit(str(e))
    if not rows:
        print("Ничего не найдено.")
        return
    print(f"{'NAME':<26} {'PROVIDER':<20} {'CATEGORY':<14} {'PRICING':<9} {'POP':>4}  URL")
    print("-" * 120)
    for r in rows:
        print(f"{_trunc(r['name'], 26):<26} {_trunc(r['provider'], 20):<20} "
              f"{_trunc(r['category'], 14):<14} {_trunc(r['pricing'], 9):<9} "
              f"{_trunc(r['popularity'], 4):>4}  {r['url'] or ''}")
    print(f"\nВсего: {len(rows)}")


def cmd_export(args):
    creds = _load_creds(args.curl)
    limit = None if args.all else args.limit
    try:
        rows = hub.search_apis(creds, args.term, category=args.category,
                               limit=limit, first=args.first)
    except hub.RapidApiError as e:
        sys.exit(str(e))

    out = args.out or f"rapidapi_{args.term}.{args.format}"
    if args.format == "json":
        with open(out, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)
    else:
        with open(out, "w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=hub.FIELDS, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                w.writerow(r)
    print(f"Сохранено {len(rows)} записей -> {out}")


def _resolve_key(args):
    """Ключ: из --key, иначе автоматически из твоего проекта (getEntityProjects)."""
    if args.key:
        return args.key
    try:
        creds = _load_creds(args.curl)
        projs = meta.projects(creds)
        if projs and projs[0].get("key"):
            return projs[0]["key"]
    except (hub.RapidApiError, SystemExit):
        pass
    return None  # дальше call_mod сам поищет env/keys.json


def cmd_call(args):
    key = _resolve_key(args)
    if args.from_curl:
        resp = call_mod.replay_curl(args.from_curl, key_override=key)
    else:
        if not (args.host and args.path):
            sys.exit("Нужно указать --host и --path (или --from-curl FILE).")
        params = dict(p.split("=", 1) for p in args.param) if args.param else None
        body = json.loads(args.json_body) if args.json_body else None
        resp = call_mod.call(args.host, args.path, method=args.method,
                             params=params, json_body=body, key=key)
    print(f"HTTP {resp.status_code}")
    try:
        print(json.dumps(resp.json(), ensure_ascii=False, indent=2)[:4000])
    except json.JSONDecodeError:
        print(resp.text[:4000])


def cmd_keys(args):
    creds = _load_creds(args.curl)
    try:
        projs = meta.projects(creds)
    except hub.RapidApiError as e:
        sys.exit(str(e))
    if not projs:
        print("Проектов не найдено.")
        return
    for p in projs:
        key = p["key"] if args.show_keys else (p["key"][:6] + "…" + p["key"][-4:] if p["key"] else "—")
        print(f"\n■ Проект: {p['name']}  (id {p['project_id']})")
        print(f"  X-RapidAPI-Key: {key}")
        if p["apis"]:
            print("  Подписанные/добавленные API:")
            for a in p["apis"]:
                print(f"    - {_trunc(a['name'], 40):<40} host: {a['slug']}.p.rapidapi.com  [{a['status']}]")
        else:
            print("  (нет подключённых API — подпишись на нужный на сайте кнопкой Subscribe)")
    if not args.show_keys:
        print("\n(ключи скрыты; добавь --show-keys чтобы показать полностью)")


def cmd_endpoint(args):
    creds = _load_creds(args.curl)
    try:
        ep = meta.endpoint(creds, args.id)
    except hub.RapidApiError as e:
        sys.exit(str(e))
    if not ep:
        print("Эндпоинт не найден.")
        return
    print(f"{ep.get('method')} {ep.get('route')}")
    print(f"Название : {ep.get('name')}")
    print(f"Группа   : {ep.get('group')}")
    print(f"Описание : {_trunc(ep.get('description'), 300)}")
    params = ep.get("params") or {}
    print("\nПараметры:")
    print(json.dumps(params.get("parameters"), ensure_ascii=False, indent=2)[:3000])


def cmd_gateways(args):
    creds = _load_creds(args.curl)
    try:
        gws = meta.gateways(creds)
    except hub.RapidApiError as e:
        sys.exit(str(e))
    for g in gws:
        flag = " (default)" if g.get("isDefault") else ""
        print(f"- dns: {g.get('dns'):<40} type: {g.get('type')} status: {g.get('status')}{flag}")


def cmd_plans(args):
    creds = _load_creds(args.curl)
    try:
        sub = meta.subscription(creds, args.api_id)
    except hub.RapidApiError as e:
        sys.exit(str(e))
    if not sub:
        print("Нет активной подписки на этот API (или API не подписан) — реальные цены отдаются "
              "только для подписанного плана. Подпишись, затем повтори.")
        return
    plan = sub.get("billingPlanVersion") or {}
    lp = plan.get("localePrice") or {}
    price = lp.get("price") if lp else plan.get("price")
    symbol = lp.get("symbol", plan.get("currency", ""))
    print(f"Подписка: статус {sub.get('status')}  тип {sub.get('type')}")
    print(f"План    : {plan.get('name')}  цена {price} {symbol} / {plan.get('period')}")
    rl = plan.get("rateLimit") or {}
    if rl.get("enabled"):
        print(f"Rate    : {rl.get('amount')} / {rl.get('unitName') or rl.get('unit')}")
    print("Лимиты:")
    for lim in plan.get("billinglimits") or []:
        it = lim.get("billingitem") or {}
        amt = "∞" if lim.get("unlimited") else lim.get("amount")
        over = lim.get("overageprice")
        over_s = f", overage {over}" if over not in (None, 0, "0") else ""
        print(f"  - {it.get('displayName') or it.get('name')}: {amt} / {lim.get('period')}{over_s}")


def cmd_subscribe(args):
    if not args.recaptcha_token:
        sys.exit(
            "Нужен --recaptcha-token. Подписка защищена Google reCAPTCHA v3: токен выпускается\n"
            "ТОЛЬКО в браузере, одноразовый и живёт ~2 минуты — из скрипта его не получить.\n"
            "Полностью headless-подписка невозможна (намеренный барьер RapidAPI).\n"
            "Варианты: (1) подпишись кнопкой Subscribe на сайте (10 сек);\n"
            "          (2) поймай свежий createApiSubscription в DevTools и передай токен сюда;\n"
            "          (3) автоматизируй кликом через браузер (Playwright), чтобы reCAPTCHA отработала."
        )
    if not args.yes:
        sys.exit("Это реальное действие в аккаунте (подписка/биллинг). Подтверди флагом --yes.")
    creds = _load_creds(args.curl)
    try:
        res = meta.subscribe(creds, args.api_id, args.plan_version_id, args.owner_id, args.recaptcha_token)
    except hub.RapidApiError as e:
        sys.exit(str(e))
    print(f"Подписка создана: {json.dumps(res, ensure_ascii=False)}")


def cmd_autosubscribe(args):
    creds = _load_creds(args.curl)
    if "/" not in args.api:
        sys.exit("--api в формате username/slug (напр. UnitedAPI/facebook-marketplace1)")
    username, slug = args.api.split("/", 1)

    info = meta.find_api(creds, slug)
    if not info or not info.get("api_id"):
        sys.exit(f"API '{slug}' не найден в поиске.")
    plans = meta.plans_from_pricing(creds, username, slug)
    if not plans:
        sys.exit("Не удалось снять планы со страницы pricing.")

    want = args.plan.upper()
    chosen = next((p for p in plans if p["plan"] == want), None)
    if not chosen:
        avail = ", ".join(f"{p['plan']}({p['price']} {p['pricing']})" for p in plans)
        sys.exit(f"План {want} не найден. Доступны: {avail}")

    is_free = chosen["pricing"] == "FREE" or str(chosen["price"]) in ("0", "0.0", "None", "null")
    print(f"API      : {args.api}")
    print(f"apiId    : {info['api_id']}")
    print(f"ownerId  : {info['owner_id']} ({username})")
    print(f"План     : {chosen['plan']}  price={chosen['price']}  pricing={chosen['pricing']}")
    print(f"versionId: {chosen['version_id']}")

    if not is_free and not args.allow_paid:
        sys.exit("Это ПЛАТНЫЙ план — реальные деньги. Для него нужен явный флаг --allow-paid.")
    if not args.yes:
        sys.exit("Это реальное действие в аккаунте (подписка). Подтверди флагом --yes.")

    print("\nРешаю reCAPTCHA v3 через Anti-Captcha (может занять ~10–60с)...")
    token = captcha.solve_recaptcha_v3(
        website_url=info["url"] + "/pricing",
        website_key=meta.RECAPTCHA_V3_SITE_KEY,
        page_action=args.page_action,
        min_score=args.min_score,
        is_enterprise=args.enterprise,
    )
    print(f"Токен reCAPTCHA получен ({len(token)} симв.). Отправляю подписку...")
    res = meta.subscribe(creds, info["api_id"], chosen["version_id"], info["owner_id"], token)
    print("Результат подписки:", json.dumps(res, ensure_ascii=False))
    print("\nПроверь: python cli.py call --host " + slug + ".p.rapidapi.com --path /<endpoint> ...")


def cmd_snippet(args):
    params = dict(p.split("=", 1) for p in args.param) if args.param else None
    print(call_mod.snippet(args.host, args.path, method=args.method,
                           params=params, lang=args.lang))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="RapidAPI Hub без UI: поиск провайдеров и вызов API.")
    p.add_argument("--curl", default="curl.txt", help="файл с сохранённым cURL (по умолчанию ./curl.txt)")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("categories", help="распределение по категориям + total")
    c.add_argument("--term", required=True)
    c.set_defaults(func=cmd_categories)

    s = sub.add_parser("search", help="таблица найденных API")
    s.add_argument("--term", required=True)
    s.add_argument("--category", help="фильтр по категории (напр. Data)")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--first", type=int, default=50, help="размер страницы GraphQL")
    s.set_defaults(func=cmd_search)

    e = sub.add_parser("export", help="массовый сбор в CSV/JSON")
    e.add_argument("--term", required=True)
    e.add_argument("--category")
    e.add_argument("--limit", type=int, default=100)
    e.add_argument("--all", action="store_true", help="собрать все страницы (игнорирует --limit)")
    e.add_argument("--first", type=int, default=50)
    e.add_argument("--format", choices=["csv", "json"], default="csv")
    e.add_argument("--out", help="имя выходного файла")
    e.set_defaults(func=cmd_export)

    ca = sub.add_parser("call", help="вызвать эндпоинт подписанного API через прокси")
    ca.add_argument("--from-curl", dest="from_curl",
                    help="файл с cURL эндпоинта (со страницы API / DevTools) — воспроизвести как есть")
    ca.add_argument("--host", help="напр. youtube138.p.rapidapi.com")
    ca.add_argument("--path", help="напр. /search")
    ca.add_argument("--method", default="GET")
    ca.add_argument("--param", action="append", default=[], help="k=v (можно повторять)")
    ca.add_argument("--json-body", dest="json_body", help="тело запроса JSON-строкой")
    ca.add_argument("--key", help="X-RapidAPI-Key (иначе env RAPIDAPI_KEY / keys.json)")
    ca.set_defaults(func=cmd_call)

    k = sub.add_parser("keys", help="твои проекты + X-RapidAPI-Key + подписанные API")
    k.add_argument("--show-keys", action="store_true", help="показать ключи полностью")
    k.set_defaults(func=cmd_keys)

    ep = sub.add_parser("endpoint", help="описание эндпоинта (route/method/параметры) по id")
    ep.add_argument("--id", required=True, help="apiendpoint_... id (из URL playground)")
    ep.set_defaults(func=cmd_endpoint)

    gw = sub.add_parser("gateways", help="список прокси-шлюзов (*.p.rapidapi.com)")
    gw.set_defaults(func=cmd_gateways)

    pl = sub.add_parser("plans", help="реальные цены/лимиты подписанного плана API")
    pl.add_argument("--api-id", dest="api_id", required=True, help="api_... (поле id из search)")
    pl.set_defaults(func=cmd_plans)

    au = sub.add_parser("autosubscribe", help="авто-подписка: найти API+free-план, решить капчу, подписать")
    au.add_argument("--api", required=True, help="username/slug, напр. UnitedAPI/facebook-marketplace1")
    au.add_argument("--plan", default="BASIC", help="имя плана (по умолчанию BASIC)")
    au.add_argument("--page-action", dest="page_action", default="", help="action для reCAPTCHA v3")
    au.add_argument("--min-score", dest="min_score", type=float, default=0.3)
    au.add_argument("--enterprise", action="store_true", help="reCAPTCHA Enterprise")
    au.add_argument("--allow-paid", action="store_true", help="разрешить НЕ бесплатный план (деньги!)")
    au.add_argument("--yes", action="store_true", help="подтвердить реальное действие")
    au.set_defaults(func=cmd_autosubscribe)

    su = sub.add_parser("subscribe", help="подписаться на план (нужен recaptcha-token из браузера)")
    su.add_argument("--api-id", dest="api_id", required=True)
    su.add_argument("--plan-version-id", dest="plan_version_id", required=True,
                    help="billingplanversion_...")
    su.add_argument("--owner-id", dest="owner_id", required=True)
    su.add_argument("--recaptcha-token", dest="recaptcha_token", help="свежий токен reCAPTCHA v3 из браузера")
    su.add_argument("--yes", action="store_true", help="подтвердить реальное действие (биллинг)")
    su.set_defaults(func=cmd_subscribe)

    sn = sub.add_parser("snippet", help="сгенерировать код вызова API")
    sn.add_argument("--host", required=True)
    sn.add_argument("--path", required=True)
    sn.add_argument("--method", default="GET")
    sn.add_argument("--param", action="append", default=[])
    sn.add_argument("--lang", choices=["python", "curl"], default="python")
    sn.set_defaults(func=cmd_snippet)

    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
