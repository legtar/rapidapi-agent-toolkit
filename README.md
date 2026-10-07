# RapidAPI Hub без UI

Поиск провайдеров данных на RapidAPI Hub **через код** (внутренний GraphQL, не парсинг HTML)
и вызов **подписанных** API через официальный прокси. Всё из командной строки, без веб-интерфейса.

> Реверс эндпоинта и открытые вопросы — в [`FINDINGS.md`](./FINDINGS.md).
> Как самому стать провайдером (Этап 2) — в [`PROVIDER_GUIDE.md`](./PROVIDER_GUIDE.md).
> Журнал работ — в [`LOG.md`](./LOG.md).

## Установка

```powershell
pip install -r requirements.txt
```

Нужен Python 3.9+. Рекомендуется запускать в **PowerShell** (в Git Bash пути вида `/search`
искажаются MSYS — это не баг кода, а особенность шелла).

## Шаг 1. Получить креды (один раз, потом обновлять при 403)

Поиск требует авторизации через Cloudflare, поэтому берём куки/токены из твоего браузера:

1. Открой <https://rapidapi.com/>, залогинься.
2. `F12` → вкладка **Network** → фильтр **Fetch/XHR**.
3. В поиске набери любой запрос (напр. `youtube`).
4. Найди запрос на `gateway/graphql` с `operationName: searchApis`.
5. ПКМ → **Copy → Copy as cURL** (cmd или bash — оба поддерживаются).
6. Вставь в файл **`curl.txt`** в этой папке (см. образец `curl.example.txt`).

Из cURL автоматически берутся `cookie`, `csrf-token`, `x-entity-id`, `user-agent`, `privateApisJwt`.

> `cf_clearance` / `__cf_bm` живут ~1–2 часа и привязаны к IP+браузеру. Получишь
> `HTTP 403 … обнови curl.txt` — просто пересними cURL и вставь заново.

## Шаг 2. Искать провайдеров

```powershell
# Быстрая проверка кредов: сколько всего и как распределено по категориям
python cli.py categories --term youtube

# Таблица: имя / провайдер / категория / тариф-лейбл / популярность / URL
python cli.py search --term youtube --limit 15
python cli.py search --term youtube --category Data --limit 15

# Массовый сбор в локальный каталог (пагинация по всем страницам)
python cli.py export --term youtube --all --format csv --out youtube_apis.csv
python cli.py export --term youtube --category Data --format json --out youtube_data.json
```

Колонки экспорта: `name, provider, provider_name, provider_type, category, pricing,
popularity, success_rate, latency_ms, service_level, updated_at, url, id, description`.

> `pricing` — это **лейбл** (`FREE`/`FREEMIUM`/`PAID`), не конкретные цены. Реальные цифры тарифов
> и список эндпоинтов отдаёт другой GraphQL-запрос со страницы API/Pricing — его ещё нужно доловить
> в DevTools (см. открытые вопросы в `FINDINGS.md`).

## Шаг 3. Подключить и вызвать API (без UI)

Официальный стабильный путь: на странице нужного API нажимаешь **Subscribe** на тариф (Basic обычно
бесплатный), получаешь один ключ `X-RapidAPI-Key`. Хост (`<...>.p.rapidapi.com`) виден в блоке Code Snippets.

Положи ключ одним из способов: `--key ...`, переменная `RAPIDAPI_KEY`, или файл `keys.json`:

```json
{ "key": "ТВОЙ_RAPIDAPI_KEY" }
```

Затем:

```powershell
# Сгенерировать готовый код вызова
python cli.py snippet --host youtube138.p.rapidapi.com --path /search --param q=music --lang python

# Или сразу вызвать эндпоинт подписанного API
python cli.py call --host youtube138.p.rapidapi.com --path /search --param q=music --param hl=en
```

## Автоматизация подключения (из внутренних операций playground)

Эти команды используют те же креды из `curl.txt`:

```powershell
python cli.py keys                    # твои проекты + X-RapidAPI-Key (авто) + подписанные API
python cli.py endpoint --id apiendpoint_...   # route/method/параметры эндпоинта
python cli.py plans --api-id api_...  # реальные цены + лимиты подписанного плана
python cli.py gateways                # прокси-шлюзы
```

`call` умеет **авто-подставлять ключ** из твоего проекта (ничего вводить не нужно):
```powershell
python cli.py call --host <slug>.p.rapidapi.com --path /<endpoint> --param k=v
```

### Авто-подписка (`autosubscribe`) — полностью без UI
Мутация подписки защищена reCAPTCHA v3; её решает **Anti-Captcha** (ключ в `secrets.json`,
`{"anticaptcha_api_key": "..."}`). Команда сама находит API, снимает free-план и подписывает:

```powershell
python cli.py autosubscribe --api UnitedAPI/facebook-marketplace1 --plan BASIC --yes
# затем сразу данные:
python cli.py call --host facebook-marketplace1.p.rapidapi.com --path /search --param query=iphone --param city=austin
```

Гварды: подписывает только **$0-план** (для платного нужен явный `--allow-paid` — реальные деньги)
и требует `--yes`. Стоит немного баланса Anti-Captcha за каждую капчу.
Есть и ручной `subscribe --recaptcha-token ...` (если токен получен иначе).

## Файлы

| Файл | Назначение |
|---|---|
| `cli.py` | точка входа CLI (`search`, `export`, `categories`, `keys`, `endpoint`, `plans`, `gateways`, `call`, `snippet`, `subscribe`) |
| `rapidapi_hub.py` | клиент внутреннего GraphQL (`searchApis` + универсальный `graphql()`) + парсер cURL |
| `rapidapi_meta.py` | внутренние операции: проекты/ключ, эндпоинты, цены, шлюзы, подписка |
| `rapidapi_call.py` | вызов подписанных API через прокси + генератор сниппетов + replay cURL |
| `rapidapi_captcha.py` | решение reCAPTCHA v3 через Anti-Captcha (для авто-подписки) |
| `curl.txt` | твой свежий cURL (не коммитится — там живые токены) |
| `keys.json` | твой `X-RapidAPI-Key` (не коммитится) |
| `FINDINGS.md` / `LOG.md` / `PROVIDER_GUIDE.md` | реверс / журнал / гайд по публикации |
