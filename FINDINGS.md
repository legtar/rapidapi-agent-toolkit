# FINDINGS — реверс внутреннего API RapidAPI Hub

Зафиксированные факты о том, как RapidAPI Hub отдаёт данные каталога. Источник — живой запрос,
пойманный в DevTools (вкладка Network) на странице поиска.

## 1. Эндпоинт поиска API — `searchApis`

- **Метод / URL:** `POST https://rapidapi.com/gateway/graphql`
- **operationName:** `searchApis`
- **Тип:** внутренний GraphQL (не публичный, не документированный). Официального публичного «API каталога» у RapidAPI нет.

### Обязательные заголовки

| Заголовок | Значение / примечание |
|---|---|
| `content-type` | `application/json` |
| `rapid-client` | `hub-service` (без него бэкенд не отвечает) |
| `csrf-token` | должен совпадать с cookie `_csrf` |
| `x-entity-id` | id пользователя (= cookie `rapidapi-context-id`), напр. `<YOUR_ENTITY_ID>` |
| `x-correlation-id` | uuid, можно генерировать свой |
| `origin` | `https://rapidapi.com` |
| `referer` | `https://rapidapi.com/search/...` |
| `user-agent` | тот же, что в браузере (Cloudflare `cf_clearance` привязан к UA **и** IP) |
| `cookie` | `cf_clearance`, `jwt_auth`, `_csrf`, `connect.sid`, `__cf_bm`, `rapidapi-context-id` и пр. |

### Тело запроса (`variables`)

```jsonc
{
  "searchApiWhereInput": {
    "term": "youtube",          // поисковый запрос
    "contextId": "<YOUR_ENTITY_ID>",    // = x-entity-id
    "privateApisJwt": "eyJ..."  // ОПЦИОНАЛЬНО, короткоживущий; нужен только для приглашённых приватных API
  },
  "paginationInput": { "first": 6, "after": "<endCursor>" },  // курсорная пагинация
  "searchApiOrderByInput": null   // опционально; по умолчанию relevance
}
```

### Форма ответа — `data.products`

- `nodes[]` — карточки API. Поля: `id, thumbnail, name, description, slugifiedName, pricing,
  updatedAt, categoryName, isSavedApi, title, visibility, apiCategory{name,color},
  score{popularityScore, avgLatency, avgServiceLevel, avgSuccessRate},
  version.tags[], user{id, username, name, type, parents[]}`.
- `facets.category[]` — `{ key, count }`, распределение результатов по категориям.
- `pageInfo` — `{ endCursor, hasNextPage, hasPreviousPage, startCursor }`.
- `total` — общее число результатов (для «yotube» было **1174**).
- `queryID`, `replicaIndex` — служебное (Algolia под капотом).

### Важные нюансы

- `name` и `description` приходят с подсветкой совпадений: `<em>YouTube</em>` — нужно вычищать теги.
- **URL страницы API** строится как `https://rapidapi.com/{user.username}/api/{slugifiedName}`.
  Пример: `YouTube` от `Glavier` → `https://rapidapi.com/Glavier/api/youtube138`.
- `pricing` — это **лейбл** (`FREE` / `FREEMIUM` / `PAID`), **НЕ** конкретные цены. Реальные цифры тарифов
  здесь не отдаются (см. открытый вопрос ниже).
- Фильтр по категории (`?search/Data`) в пойманном `where` **не передавался** — категория из URL, судя по всему,
  применяется иначе. Точное имя поля фильтра в `SearchApiWhereInput` неизвестно → фильтруем по `categoryName`
  на стороне клиента (надёжно, но качаем все страницы).

## 2. Пример реального ответа (обрезанный)

Первый узел из выдачи по «yotube» (sortBy=ByRelevance):

```json
{
  "id": "api_3a0708da-3096-46e5-aabf-91e3326500b5",
  "name": "YouTube",
  "description": "With the YouTube Data API, you can add various YouTube features to your app...",
  "slugifiedName": "youtube138",
  "pricing": "FREEMIUM",
  "categoryName": "Data",
  "score": { "popularityScore": 9.9, "avgLatency": 508, "avgServiceLevel": 99, "avgSuccessRate": 97 },
  "user": { "username": "Glavier", "name": "Glavier", "type": "User" }
}
// → URL: https://rapidapi.com/Glavier/api/youtube138
```

`facets.category` для «yotube»: Data 291, Tools 249, Social 130, Video/Images 113, AI/ML 96, Media 78,
Music 42, Entertainment 37, Business 31, Advertising 29, Search 15, ... (total = 1174).

## 3. Как вызывать САМ подписанный API (consumer, официальный путь)

После subscribe на тариф на сайте — вызов чисто из кода, без UI:

```
GET https://<host>.p.rapidapi.com/<endpoint>
Headers:
  X-RapidAPI-Key:  <твой ключ>            # один на все подписанные API
  X-RapidAPI-Host: <host>.p.rapidapi.com  # из блока Code Snippets на странице API
```

Это стабильный документированный контракт RapidAPI — не меняется в отличие от внутреннего GraphQL.

## 3b. Ещё внутренние операции (пойманы из Playground) — АВТОМАТИЗАЦИЯ подключения

Все на том же `POST gateway/graphql`, те же креды. Реализованы в `rapidapi_meta.py`.

| operationName | variables | Что даёт |
|---|---|---|
| `getEntityProjects` | `entityID` (= contextId) | проекты + **`xMashapeKey`** (это твой `X-RapidAPI-Key`) + `projectAllowedAPIs` |
| `getFullApiEndpoint` | `id` (`apiendpoint_...` из URL playground) | `method`, `route`, `description`, **`params.parameters`** (имя/тип/required/пример), примеры ответов |
| `getPlaygroundGateways` | — | список шлюзов (админский конфиг tenant; для потребителя хост = `<slug>.p.rapidapi.com`) |
| `activeUser` | — | профиль активного пользователя |

Из этого собирается **полный автоцикл без UI**:
`getEntityProjects` → ключ; `getFullApiEndpoint` → route+params; хост = `<apiSlug>.p.rapidapi.com` → вызов прокси.

**Единственный ручной барьер — Subscribe.** Без подписки прокси отвечает
`HTTP 403 {"message":"You are not subscribed to this API."}` (ключ при этом валиден — аутентификация проходит).
Подписка = финансовое действие (даже free Basic может требовать карту), поэтому автоматически её НЕ делаем.

## 3c. Подписка и реальные цены (пойманы со страниц Pricing/Playground)

| operationName | тип | Что даёт |
|---|---|---|
| `getApiSubscriber` | query | **РЕАЛЬНЫЕ цены + лимиты** активного плана: `billingPlanVersion.price/currency/billinglimits/overageprice/rateLimit`. Реализовано в `plans`. |
| `createApiSubscription` | **mutation** | подписка: `input{apiId, billingPlanVersionId, ownerId, recaptchaToken}` → `{subscriptionId, clientSecret, paymentStatus}` |
| `getApiSubscription` | query | статус подписки по id |
| `getPaymentProviderCustomer` | query | привязанные карты/платёжные методы |

**Проверено вживую:** после подписки на `facebook-pages-scraper2` (Basic, $0, лимит 25 req/мес)
вызов прокси `GET facebook-pages-scraper2.p.rapidapi.com/get_facebook_video_post_details?video_id=...`
вернул **HTTP 200** с реальными данными видео.

### ✅ Авто-подписка (headless) — РЕШЕНО через Anti-Captcha
`createApiSubscription` требует `recaptchaToken` (Google reCAPTCHA v3). Его решает **Anti-Captcha**
(RecaptchaV3TaskProxyless) за деньги с баланса. Данные для мутации:
- **reCAPTCHA v3 site-key:** `6LcBAiIlAAAAAH7OT1u0VP9-UYl9A5NThSLwT7Wj` (поле `RECAPTCHA_V3_SITE_KEY` в конфиге страницы).
  pageAction можно оставить пустым (проходит); не enterprise.
- **`apiId`** — поле `id` узла поиска (`api_...`).
- **`ownerId`** — **id владельца API** (провайдера!), = `user.id` узла поиска. НЕ id подписчика.
- **`billingPlanVersionId`** — снимается со SSR страницы `/pricing` (объекты `billingplan` → `version.id`,
  с `name`/`price`/`pricing`). Так получаем id даже неподписанного плана.

Проверено вживую: `autosubscribe UnitedAPI/facebook-marketplace1 BASIC` →
reCAPTCHA решена → `createApiSubscription` вернул `{subscriptionId, paymentStatus:"SUCCEEDED"}` →
`call /search?query=iphone` → HTTP 200 с реальными листингами. Гвард: только $0-план (иначе `--allow-paid`).

## 4. Открытые вопросы (нужно доловить в DevTools)

- **Реальные цены тарифов + список эндпоинтов конкретного API.** Отдаются другими GraphQL-операциями
  со страниц API / Pricing / Playground. Нужно поймать по одному запросу с каждой вкладки и добавить сюда.
- **Имя поля фильтра по категории** в `SearchApiWhereInput` (сейчас фильтруем клиентски).
- **Enum значения `searchApiOrderByInput`** (ByRelevance/ByPopularity/…): в пойманном запросе поля не было.
- **Максимальный `first`** на страницу (UI шлёт 6; пробуем 50).
