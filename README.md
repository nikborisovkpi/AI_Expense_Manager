# AI Grocery & Household Shopping Expense Manager

Local-first AI-powered web application for tracking, analyzing, and optimizing supermarket and hypermarket shopping expenses.

## Architecture (MVP)

- **Pattern:** Modular Monolith (`frontend/` Next.js App Router + `backend/` FastAPI single process with in-process `asyncio` receipt/insight worker and lease watchdog).
- **Identity & Data Isolation (Option A):** Single local pseudo-account initialized idempotently on first startup (`app_installation` -> `profiles.id`), no external auth/JWT/Supabase Auth. Privileged PostgreSQL connection with mandatory server-side user scoping via `BaseRepository`.
- **Storage:** Private Supabase Storage buckets (`receipts`, `avatars`) accessed exclusively by the backend (`SUPABASE_SECRET_KEY`).
- **Dual Pricing Model:**
  - **Expense & Budget Analytics:** Net effective item cost (`effective_total_price`) after all promotions, line/basket discounts, taxes, SGR deposits, and rounding (`SUM(effective_total_price) == purchases.amount`).
  - **Store Chain Comparison:** Original regular pre-discount unit price (`regular_standard_unit_price`) normalized to `RON/kg`, `RON/l`, or `RON/pc` (with multi-currency support for `RON`, `UAH`, `EUR`, `USD`, never aggregating across currencies).
- **AI & Privacy:** Provider-agnostic Pydantic AI + OpenRouter integration (`anthropic/claude-*`, `openai/gpt-*`, etc.) enforcing strict Zero Data Retention (`zdr=true`, `data_collection="deny"`, `require_parameters=true`) across primary and fallback models.

## Local Development

1. Copy `.env.example` to `.env` and fill in your credentials (`DATABASE_URL`, `SUPABASE_URL`, `SUPABASE_SECRET_KEY`, `OPENROUTER_API_KEY`).
2. Start local PostgreSQL (if not using remote Supabase DB):
   ```bash
   docker compose up -d
   ```
3. Run Backend (`http://127.0.0.1:8000`):
   ```bash
   cd backend
   uv sync --dev
   uv run alembic upgrade head
   uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
   ```
4. Run Frontend (`http://localhost:3000`):
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

See `docs/IMPLEMENTATION_PLAN.md` for the detailed roadmap and architectural specifications.
