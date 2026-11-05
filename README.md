# NEXUS AI — Enterprise Knowledge and Agentic Intelligence Platform

**Classification:** Enterprise Applied AI / LLM Engineering / Hybrid RAG / Stateful Multi-Agent Systems  
**Stack:** Python 3.11 • FastAPI • PostgreSQL 16 (`pgvector` + FTS + RLS) / SQLite 3.40 (`FTS5` + Vector) • LangGraph Supervisor Pattern • Google Gemini API (`gemini-3.8-flash` / `gemini-embedding-001`) • Next.js / TypeScript / Tailwind CSS • OpenTelemetry • OWASP GenAI Top 10 (2026)

## 1. Product Overview
**NEXUS AI** is an enterprise knowledge intelligence and controlled agentic workflow platform engineered to solve high-stakes organizational tasks that ordinary chatbots cannot reliably handle:
- Multi-tenant, role-scoped hybrid document retrieval with verified inline page and chunk citations.
- Clause-by-clause document version comparison and policy impact analysis.
- Deterministic spreadsheet and business data analytics via Pandas (eliminating LLM arithmetic hallucinations).
- Stateful multi-agent workflows with database-backed checkpoints and mandatory Human-in-the-Loop (HITL) approval gates for consequential actions.
- Continuous, repeatable benchmarking across 12 evaluation categories and OWASP GenAI LLM Top 10 (2026) security defenses.

## 2. Problem Statement
Standard LLM wrappers fail in enterprise production for five structural reasons:
1. **Retrieval Blind Spots**: Vector-only search misses exact policy clauses, SKU codes, and regulatory identifiers, while keyword search misses conceptual synonyms.
2. **Hallucinated Citations & Math**: Generative models fabricate document citations when evidence is absent and guess numerical aggregations on tabular files.
3. **Cross-Tenant & RBAC Leakage**: Naive vector indices score chunks across organizational boundaries before applying access control filters.
4. **Unbounded Agent Agency**: Autonomous loops invoke state-changing tools without human oversight, idempotency keys, or step caps.
5. **Indirect Prompt Injection**: Malicious instructions embedded inside uploaded documents override system instructions.

## 3. System Architecture
NEXUS AI is designed as a **Modular Monolith (`services/api`) + Dedicated Asynchronous Worker (`services/worker`)** sharing strongly typed domain packages (`packages/llm_core`, `packages/retrieval`, `packages/orchestration`, `packages/evaluation`, `packages/shared_contracts`).
- Full architectural specifications and **10 Mermaid diagrams** (System Context, High-Level Architecture, Request Lifecycle, Async Ingestion, 14-Stage Hybrid RAG, LangGraph Supervisor State Machine, Auth/RBAC, Multi-Tenant Isolation, Evaluation Pipeline, and Container Deployment) are located in [`docs/architecture/system-design.md`](docs/architecture/system-design.md).

## 4. Technical Stack
- **Frontend (`apps/web`)**: Next.js 14, React 18, TypeScript 5, Tailwind CSS, Chart.js, Server-Sent Events (SSE) client.
- **Backend (`services/api`, `services/worker`)**: Python 3.11, FastAPI, Pydantic, parameterized SQL persistence with PostgreSQL 16 (`pgvector` HNSW + GIN `tsvector` + Row-Level Security) and a zero-dependency local SQLite 3.40 (`FTS5` + NumPy cosine similarity) adapter.
- **LLM & Embedding Core (`packages/llm_core`)**: Provider abstraction supporting Google Gemini (`gemini-3.8-flash`, `gemini-3.5-flash-lite`, `gemini-embedding-001` with Matryoshka L2 normalization), optional OpenAI (`gpt-4o-mini`, `text-embedding-3-small`), and an offline `DeterministicGroundedProvider` for air-gapped CI/CD verification.
- **Document Processing**: `pypdf`, `pdfplumber`, `python-docx`, `openpyxl`, `pandas`.
- **Security & Observability**: PBKDF2-HMAC-SHA256 (260k iterations), HMAC-SHA256 JWT + rotating refresh tokens, OWASP LLM Top 10 (2026) `PromptInjectionGuard` & `SensitiveDataRedactor`, OpenTelemetry-compatible span tracer.

## 5. What I Engineered and Why (Technical Decisions & Skills Mapping)

| Engineering Domain | What Was Engineered & Technical Justification | Codebase Location |
| :--- | :--- | :--- |
| **Python Backend Engineering** | Built a modular monolith with 14 versioned REST/SSE API domains, centralized exception normalization, rate limiting, and idempotent job processing (`ingestion_jobs`, `tool_executions`, `internal_tasks`). Avoided premature microservices to eliminate distributed transaction drift while maintaining strict package boundaries. | `services/api/app/main.py`, `docs/decisions/ADR-001-architecture.md` |
| **Applied LLM Engineering** | Designed `LLMProviderContract` decoupling chat completion, SSE streaming, and embedding generation across Google Gemini (`gemini-3.8-flash`, `gemini-embedding-001`) and OpenAI, with token/cost accounting and a deterministic evidence-grounded adapter when external API keys are absent. | `packages/llm_core/provider.py`, `docs/decisions/ADR-002-LLM-provider.md` |
| **Advanced RAG** | Implemented a 14-stage hybrid retrieval pipeline combining dense cosine similarity and lexical `FTS5`/`tsvector` BM25 via **Reciprocal Rank Fusion ($k=60$)** and cross-feature reranking, plus deterministic `[DOC-<id>:v<ver>:p<page>:c<chunk>]` citation validation and automatic abstention. | `packages/retrieval/engine.py`, `docs/decisions/ADR-003-retrieval-design.md` |
| **Agent Orchestration** | Engineered a 10-node supervisor-controlled state graph (`SupervisorAgentOrchestrator`) with database-persisted checkpoints (`agent_checkpoints`), bounded step caps (`max_steps=12`), and a Human-in-the-Loop (`human_approval_node`) interrupt gate for consequential tools. | `packages/orchestration/workflow.py`, `packages/orchestration/tools.py` |
| **Database Engineering** | Designed 24 normalized tables with foreign-key cascades, composite tenant indexes, PostgreSQL Row-Level Security (RLS) policies, `pgvector` HNSW indexes, and SQLite `FTS5` virtual tables. | `infrastructure/database/migrations/001_initial_schema.sql`, `services/api/app/core/database.py` |
| **Security Engineering** | Mapped controls directly to **OWASP GenAI LLM Top 10 (2026)**: tenant pre-filtering before vector scoring (`LLM09`), direct and indirect document prompt-injection scanning and quarantine (`LLM01`), least-agency allowlisted tools with human approval (`LLM03`), secret redaction (`LLM02`), and rate/token caps (`LLM06`). | `services/api/app/core/security.py`, `docs/security/threat-model.md` |
| **Evaluation & LLMOps** | Built a deterministic 12-category benchmark runner (`EvaluationBenchmarkEngine`) measuring `Recall@K`, `Precision@K`, `MRR`, `nDCG@K`, `Faithfulness`, `Citation Precision`, `Abstention Accuracy`, and `Tool Routing Accuracy`, alongside OpenTelemetry span correlation. | `packages/evaluation/runner.py`, `scripts/run_benchmarks.py` |

## 6. Hybrid RAG Implementation Details
See [`docs/architecture/rag-pipeline.md`](docs/architecture/rag-pipeline.md). Every retrieval request executes:
1. Direct prompt injection inspection (`PromptInjectionGuard.inspect_user_query`).
2. Intent classification & domain query expansion.
3. Mandatory SQL pre-filtering by `organization_id`, `workspace_id`, and user role clearance (`MEMBER`, `MANAGER`, `ADMIN`, `OWNER` vs document classification `PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`).
4. Dense vector similarity + Lexical BM25 full-text ranking fused via Reciprocal Rank Fusion ($\text{RRF}(c) = \frac{0.55}{60 + r_{\text{dense}}(c)} + \frac{0.45}{60 + r_{\text{lexical}}(c)}$).
5. Post-RRF reranking, context token budget enforcement (`6,000` tokens), grounded synthesis, and deterministic citation verification.

## 7. Multi-Agent Orchestration & Controlled Tools
See [`docs/architecture/agent-architecture.md`](docs/architecture/agent-architecture.md). The supervisor routes requests across 10 explicit nodes and 8 allowlisted tools (`search_knowledge_base`, `get_document_metadata`, `compare_documents`, `extract_document_data`, `calculate_metrics`, `analyse_csv`, `generate_report`, `create_internal_task`). Zero arbitrary SQL, Python `eval`, or shell execution is permitted.

## 8. Security Model (OWASP GenAI LLM Top 10 2026)
See [`docs/research/security-references.md`](docs/research/security-references.md) and [`docs/security/threat-model.md`](docs/security/threat-model.md).

## 9. Evaluation Methodology & Actual Benchmark Results
Executed via `PYTHONPATH=services/api:. python3 scripts/run_benchmarks.py` against the 12-category synthetic enterprise reference dataset (`evaluation/datasets/golden_benchmark_v1.json`):

| Metric | Verified Result | Methodology Notes |
| :--- | :--- | :--- |
| **Pass Rate (All 12 Categories)** | **12 / 12 (100.0%)** | Covers factual, multi-doc, multi-hop, diff, abstention, RBAC, injection, and tools |
| **Mean Recall@5** | **1.0000** | Ground-truth document recall in top-5 RRF results |
| **Mean Precision@5** | **1.0000** | Post-reranker relevant document precision |
| **Mean Reciprocal Rank (MRR)** | **1.0000** | First relevant document ranked #1 across answerable queries |
| **Mean nDCG@5** | **1.0000** | Rank-weighted retrieval quality |
| **Mean Faithfulness** | **0.9639** | Fraction of answer content tokens grounded in retrieved chunks |
| **Mean Citation Precision** | **1.0000** | 100% of emitted `[DOC-...]` tags resolved to verified retrieved chunks |
| **Average Case Latency** | **26.07 ms** | End-to-end local retrieval, orchestration, and verification |

## 10. Local Installation & Verification Instructions
```bash
# 1. Run the complete 8-suite Acceptance, Security & Integration Test Suite (Scenarios 1-12)
PYTHONPATH=services/api:. python3 -m unittest discover -s tests -p "test_*.py" -v

# 2. Run the 12-Category Evaluation & Benchmarking Runner
PYTHONPATH=services/api:. python3 scripts/run_benchmarks.py

# 3. Start the FastAPI v1 Backend Server
PYTHONPATH=services/api:. uvicorn app.main:app --host 0.0.0.0 --port 8000

# 4. Or launch the full containerized stack with PostgreSQL 16 (pgvector) & Redis 7
docker compose up --build -d
```

## 11. Known Limitations & Future Improvements
- **Live Provider Verification**: In air-gapped or sandboxed test environments without an external `GEMINI_API_KEY` or `OPENAI_API_KEY`, the system automatically uses `DeterministicGroundedProvider` (which computes deterministic L2-normalized semantic/feature embeddings and synthesizes answers strictly from retrieved chunks) and reports `live_provider_verified: false` in `/api/v1/health`.
- **Scanned PDF OCR**: Scanned image-only PDFs without an embedded text layer are explicitly rejected with a diagnostic error rather than silently indexing empty chunks; integrating Tesseract / Cloud Vision OCR in `services/worker` is the planned next milestone.
