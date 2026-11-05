# NEXUS AI — Production Deployment & Operations Runbook

## 1. Local & Docker Compose Startup
```bash
# 1. Copy environment template
cp .env.example .env

# 2. Start full stack via Docker Compose (PostgreSQL 16 + pgvector, Redis 7, API, Worker, Web)
docker compose up --build -d

# 3. Verify health & readiness checks
curl -fsS http://localhost:8000/api/v1/health
curl -fsS http://localhost:8000/api/v1/ready
```

## 2. Standalone Local Execution (Without Docker Daemon)
```bash
# Install runtime & test dependencies
python3 -m pip install --upgrade pip
pip install -r requirements-dev.txt

# Run automated verification & acceptance suite (uses local SQLite FTS5 + Vector adapter)
PYTHONPATH=services/api:. python3 -m unittest discover -s tests -p "test_*.py" -v

# Run repeatable evaluation benchmark suite
PYTHONPATH=services/api:. python3 scripts/run_benchmarks.py

# Start FastAPI server locally
PYTHONPATH=services/api:. uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 3. Database Migrations
- Production PostgreSQL schema and RLS policies: `infrastructure/database/migrations/001_initial_schema.sql`.
- Local automatic schema initialization: `services/api/app/core/database.py` (`init_db()`).

## 4. Key Environment Variables
- `NEXUS_ENV`: `development` | `test` | `production`
- `NEXUS_DB_URL`: PostgreSQL DSN or `sqlite:///./nexus_ai.db`
- `NEXUS_JWT_SECRET`: 32+ byte cryptographic secret key
- `GEMINI_API_KEY`: Google Gemini API key (uses `gemini-3.8-flash` and `gemini-embedding-001`)
- `OPENAI_API_KEY`: Optional OpenAI fallback key
