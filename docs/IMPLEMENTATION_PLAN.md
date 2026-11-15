# AI Expense Manager (MVP) — Implementation Plan

**Goal:** Побудувати локальний single-user MVP вебзастосунок (Modular Monolith: Next.js + FastAPI + Supabase PostgreSQL/Storage + Pydantic AI / OpenRouter ZDR) для обліку щоденних закупок у супермаркетах, розпізнавання чеків, порівняння базових цін між мережами магазинів, контролю бюджетів та ШІ-аналітики витрат.

**Architecture:** Монорепозиторій із двома додатками (`frontend/` та `backend/`). Один процес FastAPI обслуговує REST API (`/api/v1`), SSE-стрімінг чату ШІ, проксі приватних файлів зі Storage, а також внутрішній `asyncio`-воркер черги чеків/інсайтів із PostgreSQL row-level leases (`SELECT ... FOR UPDATE SKIP LOCKED`) та startup/periodic watchdog. Ізоляція даних реалізована за стратегією Option A: привілейована роль БД без RLS + примусовий серверний скоупінг через `BaseRepository` за локальним псевдо-акаунтом (`app_installation` -> `profiles.id`).

**Tech Stack:**
- **Frontend:** Next.js (App Router), React, TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, React Hook Form, Zod, Recharts.
- **Backend:** Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy 2.x (async), Alembic, httpx, tzlocal, pypdfium2/Pillow (in-memory PDF->image), pytest.
- **Database & Storage:** Supabase PostgreSQL, Supabase Storage (private buckets: `receipts`, `avatars`).
- **AI & Observability:** Pydantic AI, OpenRouter API (провайдер-агностично: `anthropic/claude-*`, `openai/gpt-*` та сумісні ZDR-моделі), Logfire або Langfuse.

**Spec:** `Project_Development_Blueprint_Updated.docx` + узгоджені архітектурні рішення та уточнення користувача.

---

## Global Constraints & Agreed Refinements

1. **Без зовнішньої автентифікації та клієнтських ключів Supabase:** Жодних `NEXT_PUBLIC_SUPABASE_*`, `SUPABASE_JWT_SECRET`, `OPENAI_API_KEY`. Ключ `SUPABASE_SECRET_KEY` використовується виключно на бекенді для приватного Storage.
2. **Локальний профіль, таймзона та валюта за замовчуванням:**
   - Таблиця `app_installation(singleton_key BOOL PK DEFAULT TRUE, active_profile_id UUID FK -> profiles.id)` забезпечує рівно 1 активний профіль інсталяції та водночас дозволяє створювати кілька рядків у `profiles` для обов’язкових cross-user тестів `BaseRepository`.
   - Таймзона `profiles.timezone` визначається бекендом автоматично при першому старті (`tzlocal`, fallback `UTC`) з можливістю зміни в Settings.
   - Дефолтна валюта профілю — **`RON`**, із підтримкою зміни на `UAH`, `EUR`, `USD`. Суми в різних валютах ніколи не агрегуються разом.
3. **Невідомі магазини на чеках:**
   - Глобальний довідник `store_chains` є read-only і містить румунські мережі (*Lidl, Kaufland, Carrefour, Auchan, Penny, Mega Image*), українські мережі (*АТБ, Сільпо, Novus, Metro, Varus, Фора, Епіцентр*) та системний fallback **`Other / Independent Store` (`slug='other'`, `is_fallback=true`)**.
   - Якщо користувач завантажує чек із невідомого магазину, бекенд все одно зберігає його назву в БД у `stores.display_name` (прив’язуючи до мережі `'other'`). Користувач може будь-коли відредагувати назву магазину (`PATCH /stores/{id}`) або видалити покупку (`DELETE /purchases/{id}`).
4. **Стандартизація одиниць виміру (`кг` / `л` / `шт.`):**
   - Для харчових та вагових/рідких товарів базова ціна вигоди стандартизується у **валюті за 1 кг** (`g`, `kg` -> `kg`) або **валюті за 1 літр** (`ml`, `l` -> `l`); для суто штучних товарів без ваги/об’єму — за `1 piece` (`pack`, `pair`, `piece`).
5. **Подвійна модель цін товару (Витрати vs Порівняння мереж):**
   - **Аналіз витрат і бюджетів користувача** базується на **`effective_total_price`** — кінцевій фактичній вартості товару після вирахування всіх акцій, рядкових і загальночекових знижок, податків, заставної тари (`SGR`) та округлення (`SUM(purchase_items.effective_total_price) == purchases.amount` з точністю до `0.01`).
   - **Порівняння цін між магазинами / мережами (`store-comparison`)** базується на **`regular_standard_unit_price`** — оригінальній базовій ціні товару **без знижок** у перерахунку на `1 kg` / `1 l` / `1 pc`.
6. **Провайдер-агностичний AI та суворий ZDR:**
   - Жодної прив’язки до SDK конкретного AI-провайдера — вибір між моделями Claude (`anthropic/claude-*`), GPT (`openai/gpt-*`) та іншими здійснюється виключно через змінні середовища OpenRouter.
   - Кожен первинний і fallback-запит містить `provider: {"zdr": true, "data_collection": "deny", "require_parameters": true}` (fail-closed, без переходу на звичайні провайдери).

---

## Project Directory Structure

```text
AI_Expense_Manager/
├── docs/
│   └── IMPLEMENTATION_PLAN.md
├── backend/
│   ├── alembic/
│   ├── app/
│   │   ├── main.py
│   │   ├── core/          # config.py, timezone.py, errors.py, logging.py, rate_limit.py
│   │   ├── db/            # session.py, base.py, seed.py
│   │   ├── models/        # profile.py, store.py, category.py, product.py, purchase.py, receipt.py, budget.py, shopping_list.py, agent.py, insight.py
│   │   ├── repositories/  # base.py (BaseRepository) + domain repositories
│   │   ├── schemas/       # Pydantic v2 request/response & extraction schemas
│   │   ├── services/      # profile, catalog, pricing, purchase, receipt, budget, analytics, insight, shopping_list, agent_action, storage
│   │   ├── workers/       # receipt_worker.py, insight_worker.py, watchdog.py
│   │   ├── ai/
│   │   │   ├── client.py  # Provider-agnostic OpenRouter ZDR adapter + fallbacks
│   │   │   ├── receipt/   # pdf_converter.py, extractor.py, normalizer.py, classifier.py
│   │   │   ├── agents/    # shopping_agent.py
│   │   │   ├── tools/     # read_tools.py (10 tools), write_tools.py (3 proposal tools)
│   │   │   ├── prompts/   # versioned system prompts
│   │   │   └── evaluation/# benchmark fixtures & runners (receipts + agent evals)
│   │   └── api/v1/        # profile, purchases, purchase_items, products, categories, stores, aliases, analytics, budgets, receipts, shopping_lists, agent
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── evals/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── app/(app)/     # dashboard, purchases, receipts, products, price-comparison, budgets, shopping-lists, assistant, settings
│   │   ├── components/    # ui/, layout/, shared/
│   │   ├── features/      # profile, dashboard, purchases, receipts, products, categories, stores, budgets, shopping-lists, ai-assistant
│   │   ├── hooks/
│   │   ├── lib/           # api-client.ts, query-client.ts, formatters.ts
│   │   └── types/
│   └── package.json
├── docker-compose.yml
├── .env.example
└── .github/workflows/
    ├── ci.yml
    └── ai-evals.yml
```

---

## Phased Implementation Roadmap

### Phase 1: Monorepo Initialization, Tooling & CI
- [x] Створити структуру `backend/` (FastAPI, SQLAlchemy 2.x, Alembic, Pydantic Settings, `tzlocal`, `ruff`, `mypy`, `pytest`) та `frontend/` (Next.js App Router, TypeScript, Tailwind CSS, shadcn/ui, TanStack Query, React Hook Form, Zod, Recharts).
- [x] Додати `.env.example` (суворо за розділом 14 специфікації), `docker-compose.yml` (PostgreSQL для локальної розробки й тестів) та GitHub Actions `.github/workflows/ci.yml` (лінтинг, типізація, тести).
- [x] Реалізувати `GET /api/v1/health`, єдиний формат помилок (400, 403, 404, 409, 422, 429, 500, 503) та локальний CORS (`localhost`).
- [x] Верифікація: проходження лінтерів, типізації та базового тесту `/api/v1/health`.

### Phase 2: Database Migrations, Seeds, `BaseRepository` & Local Profile
- [x] Описати SQLAlchemy 2.x моделі всіх таблиць MVP та згенерувати початкову міграцію Alembic (включно з `CHECK`, `UNIQUE`, FK `RESTRICT`/`SET NULL` та індексами з розділу 5.3).
- [x] Реалізувати ідемпотентний `app/db/seed.py`: дворівневе дерево системних категорій із полем `macro_group ('food' | 'household')` + глобальний каталог `store_chains` (румунські, українські мережі та fallback `'other'`).
- [x] Реалізувати `BaseRepository` із жорсткою ін’єкцією серверного `user_id` для всіх операцій читання/запису та перевіркою власності зв’язаних сутностей.
- [x] Реалізувати ідемпотентний бутстрап локального профілю через `app_installation` з автовизначенням таймзони сервера (`tzlocal`) і валютою `RON`.
- [x] Реалізувати сервіс приватного Supabase Storage та роутер профілю: `GET /profile`, `PATCH /profile` (включно з `preferences`), `POST /profile/avatar`, `GET /profile/avatar` (потоковий проксі), `DELETE /profile/avatar`.
- [x] Верифікація: інтеграційні cross-user тести `BaseRepository` (`user_a` vs `user_b`) для всіх користувацьких моделей; тест конкурентного першого старту профілю.

### Phase 3: Core Catalog (Categories, Stores, Products, Aliases) & Manual Purchases
- [x] Реалізувати детермінований сервіс одиниць виміру та подвійного ціноутворення (`pricing.py`):
  - нормалізація `g -> kg`, `ml -> l`;
  - обчислення `effective_total_price` (точний розподіл знижок, SGR/тари й округлення до `purchases.amount`);
  - обчислення `regular_standard_unit_price` (без знижок — для порівняння магазинів) та `paid_standard_unit_price` (зі знижками — для витрат).
- [x] Реалізувати API `/categories`, `/store-chains`, `/stores` (із редагованим `display_name` та soft-archive `is_active=false`), `/products` (пошук, фільтри, soft-archive), `/product-aliases` (`confirm`/`reject`).
- [x] Реалізувати API `/purchases` та `/purchase-items` (CRUD, ідемпотентність створення, snapshot-поля категорії/батьківської категорії/одиниць; при `DELETE /purchases/{id}` — скидання `receipts.purchase_id = NULL` та повернення чека у `needs_review`).
- [x] Верифікація: юніт- та інтеграційні тести математичної точності подвійних цін, незмінності історичних snapshot-полів та захисту системних довідників.

### Phase 4: Timezone-Aware Budgets, Analytics & Cached Insights
- [ ] Реалізувати `/budgets` (`GET`, `POST`, `PATCH`, `DELETE`, `GET /status`) із границями місяців у `profiles.timezone`, фільтрацією за валютою бюджету та порогами попереджень.
- [ ] Реалізувати `/analytics/*` (`summary` із розбивкою `food_spending` vs `household_spending`, `categories`, `stores`, `trends`, `top-products`, `price-changes`, `household-spending`) виключно за підтвердженими покупками (`effective_total_price`, згруповано за `currency`).
- [ ] Реалізувати `GET /dashboard/insights` (читання виключно з кешу `dashboard_insights`) та механізм інвалідації `data_version` з фоновим оновленням у воркері (debounce 20 с) після змін покупок.
- [ ] Верифікація: тести часових поясів на межі місяця, ізоляції різних валют та відсутності викликів LLM під час `GET /dashboard/insights`.

### Phase 5: Provider-Agnostic OpenRouter Client & Async Receipt Scanner Pipeline
- [ ] Реалізувати `app/ai/client.py` (Pydantic AI + OpenRouter): підтримка будь-яких сумісних моделей (`anthropic/claude-*`, `openai/gpt-*`) через `.env`, примусова передача `provider: {zdr: true, data_collection: "deny", require_parameters: true}`, каскад `OPENROUTER_FALLBACK_MODELS`, таймаути та ліміти токенів.
- [ ] Реалізувати ендпоінти життєвого циклу чеків: `POST /receipts/upload`, `GET /receipts`, `GET /receipts/{id}/status`, `GET /receipts/{id}/result`, `GET /receipts/{id}/file` (проксі з приватного Storage), `POST /receipts/{id}/retry`, `POST /receipts/{id}/cancel`, `DELETE /receipts/{id}`.
- [ ] Реалізувати `watchdog.py` та `receipt_worker.py` у `lifespan` FastAPI: атомарне захоплення задач через `SELECT ... FOR UPDATE SKIP LOCKED` із lease, відновлення прострочених leases після сну/рестарту, конвертація PDF у зображення в пам’яті.
- [ ] Реалізувати Vision-екстракцію, пошук підтверджених `product_aliases`, класифікацію категорій, виділення SGR/тари у `container_deposit_total`, детерміновану звірку сум та детекцію дублікатів (`file_hash`, `receipt_fingerprint`) із переведенням у `needs_review` при розбіжностях.
- [ ] Верифікація: тести конкурентних воркерів, відновлення після збою watchdog-ом, арифметичної валідації чеків та ZDR-обмежень клієнта.

### Phase 6: Receipt Draft Review, Confirmation & Store Price Comparison
- [ ] Реалізувати `PATCH /receipts/{id}/draft` (редагування чернетки користувачем із перерахунком попереджень) та `POST /receipts/{id}/confirm` (атомарна ідемпотентна транзакція створення магазину — включно з невідомими магазинами через мережу `'other'` — товарів, аліасів, покупки й позицій).
- [ ] Реалізувати `GET /products/{id}/price-history` (історія і регулярних, і фактично сплачених цін) та `GET /products/{id}/store-comparison` (порівняння оригінальних цін без знижок `regular_standard_unit_price` за `кг`/`л`/`шт.` між мережами/магазинами з датами спостережень та перевіркою достатності даних).
- [ ] Верифікація: тести ідемпотентного підтвердження, збереження/редагування невідомого магазину з чека та коректного порівняння базових цін без викривлення акційними знижками.

### Phase 7: AI Shopping Assistant (Read-Only Tools & SSE Streaming)
- [ ] Реалізувати головного агента (`shopping_agent.py`) та 10 типізованими read-only тулів (`get_purchases`, `get_spending_summary`, `get_category_spending`, `get_budget_status`, `get_product_price_history`, `compare_store_prices`, `get_top_products`, `get_price_changes`, `search_products`, `get_shopping_lists`) із метаданими `period`, `currency`, `observation_count`, `last_observation_date`, `source_record_ids`, `data_sufficiency`.
- [ ] Реалізувати детермінований резолвер дат у `profiles.timezone`, уточнення неоднозначних товарів, збереження `conversations`/`messages` та `POST /agent/chat` зі стрімінгом **SSE**.
- [ ] Верифікація: тести SSE-стрімінгу, обробки `insufficient_data` та відповідності чисел у відповідях результатам тулів.

### Phase 8: Approval-Gated Agent Actions & Shopping Lists
- [ ] Реалізувати CRUD списків покупок (`/shopping-lists`, `/shopping-list-items`) із розрахунком оціночної вартості (`estimated_price`) на основі останніх спостережень.
- [ ] Реалізувати таблицю й сервіс `agent_actions` для рівно 3 write-пропозицій (`create_budget`, `create_shopping_list`, `add_shopping_list_item`) із паузою агента, SSE-подією `action_required` та синхронними ендпоінтами `POST /agent/actions/{id}/approve` і `/reject` (перевірка власника, `expires_at`, `arguments_hash`, `idempotency_key`, запис підсумкового повідомлення в історію без зайвого виклику LLM).
- [ ] Верифікація: тести захисту від несанкціонованих мутацій, прострочених дій, підміни хешу аргументів та повторного підтвердження.

### Phase 9: Next.js Frontend Implementation (All 9 Screens)
- [ ] Побудувати адаптивний layout, API-клієнт та TanStack Query хуки.
- [ ] Реалізувати всі 9 екранів:
  1. **Dashboard** (зведення у вибраній валюті, Food vs Household, графіки Recharts, бюджети, останні чеки, кешовані AI-інсайти).
  2. **Receipt Scanner** (upload, живий статус черги, перегляд оригіналу чека, редагування чернетки з підсвіткою розбіжностей та редагуванням назви магазину, підтвердження).
  3. **Purchases** (список, фільтри, ручне додавання/редагування, деталі покупки з переглядом чека, видалення).
  4. **Products & Categories** (каталог товарів, дерево категорій, управління аліасами, графік історії цін).
  5. **Price Comparison** (пошук товару, порівняння базових цін без знижок у `RON/kg` або `RON/l` по мережах/магазинах, дати та індикатори достатності даних).
  6. **Budgets** (створення/редагування бюджетів, прогрес і попередження).
  7. **Shopping Lists** (списки, позначення куплених позицій, оціночна вартість).
  8. **AI Assistant** (історія діалогів, SSE-чат з індикаторами тулів, джерела даних, картки Approve/Reject для дій).
  9. **Settings** (профіль, аватар, зміна валюти `RON/UAH/EUR/USD`, таймзона, сповіщення та панель ZDR-приватності).
- [ ] Верифікація: `tsc --noEmit`, `eslint`, компонентні тести критичних сценаріїв та production build (`next build`).

### Phase 10: Observability, Hardening & Benchmark Evals
- [ ] Підключити Logfire або Langfuse для трейсингу токенів/вартості/латентності без запису зображень чеків і сирого приватного тексту в логи; додати rate limits і добові ліміти токенів.
- [ ] Створити в репозиторії версіоновані набори оцінювання:
  - 20+ репрезентативних чеків із ground truth;
  - 30+ сценаріїв ШІ-асистента (включно з prompt-injection у назвах товарів чека, неоднозначними продуктами та перевіркою точності всіх чисел).
- [ ] Налаштувати `.github/workflows/ai-evals.yml` для запуску live-evals при змінах у `backend/app/ai/**` або конфігурації моделей, та фіналізувати `README.md` і `docs/`.

---

## Review Focus (Critical Edge Cases Covered by Tests)

1. **Точність подвійної ціни на складних чеках:** чек із рядковою знижкою, загальним купоном, SGR-тарою та округленням дає `SUM(effective_total_price) == purchases.amount` у витратах, а в `store-comparison` використовує чисту базову ціну без знижки за `1 кг` / `1 л`.
2. **Невідомий магазин на чеку:** автоматичне збереження назви в `stores.display_name` (мережа `'other'`), можливість перейменування магазину користувачем та безпечне видалення покупки з поверненням чека у `needs_review`.
3. **Відновлення воркера після збою/сну:** прострочений `processing_lease_expires_at` коректно повертається у `queued` під час старту `watchdog` без дублювання обробки.
4. **Стійкість до Prompt Injection:** інструкції всередині тексту чека не можуть викликати write-тул або обійти серверний ендпоінт `/approve`.
5. **Провайдер-агностичність та ZDR Fail-Closed:** перемикання між моделями Claude та GPT працює лише за конфігурацією `.env` зі збереженням `zdr=true`, `data_collection="deny"`, `require_parameters=true` на всіх спробах.
