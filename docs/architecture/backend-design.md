# NEXUS AI — Backend Architecture Design

## Architectural Style: Modular Monolith + Dedicated Worker
NEXUS AI implements a clean **Modular Monolith** in `services/api` paired with an asynchronous background processor in `services/worker`, sharing domain packages under `packages/`.

### Module Boundaries
- **Module A (`app/auth`, `app/organizations`)**: User registration, PBKDF2-HMAC-SHA256 password hashing with cryptographic salt, JWT access tokens, refresh token rotation, organization/workspace provisioning, invitations, and 4-tier RBAC (`OWNER`, `ADMIN`, `MANAGER`, `MEMBER`).
- **Module B (`app/documents`, `app/ingestion`)**: File validation, SHA-256 deduplication, semantic versioning, multi-format parsing (PDF, DOCX, XLSX, CSV, Markdown, TXT), structural chunking with page/heading preservation, and idempotent background indexing.
- **Module C (`packages/retrieval`, `app/retrieval`)**: 14-stage hybrid RAG engine combining dense cosine similarity, lexical FTS5/tsvector BM25 ranking, tenant metadata pre-filtering, Reciprocal Rank Fusion ($k=60$), cross-feature reranking, context window token budgeting, and deterministic citation validation.
- **Module D (`app/conversations`)**: Multi-conversation management, Server-Sent Events (SSE) token & trace streaming, follow-up query contextualization, citation inspection, and user feedback tracking.
- **Module E (`packages/orchestration`, `app/agents`)**: LangGraph-pattern stateful workflow supervisor with 10 specialized nodes, database-persisted checkpoints (`agent_checkpoints`), step budgets, retry recovery, and human-in-the-loop (HITL) approval pauses.
- **Module F (`packages/orchestration/tools.py`, `app/tools`)**: Controlled Tool Registry with 8 strictly typed, allowlisted enterprise tools, role permission checks, execution timeouts, idempotency keys, and audit logs.
- **Module G (`app/analytics`)**: Deterministic Pandas/NumPy business data analytics engine for CSV/XLSX files (schema profiles, missing value reports, descriptive statistics, group aggregations, time-series trends, and chart-ready series).
- **Module H (`app/reports`)**: Document version comparison, policy clause diff detection, operational risk assessment, and exportable Markdown/PDF executive reports with verified citations.
- **Module I (`packages/evaluation`, `app/evaluation`)**: Automated benchmark runner across 12 evaluation categories computing Recall@K, Precision@K, MRR, nDCG, Faithfulness, Citation Precision, Abstention Accuracy, and Agent Tool Accuracy.
- **Module J (`app/observability`)**: OpenTelemetry-compatible trace & span collector recording latency breakdowns, token usage, provider cost estimates, retrieval traces, and error rates.
- **Module K (`app/core/security.py`)**: OWASP GenAI LLM Top 10 (2026) guardrails including direct/indirect prompt injection detection, sensitive data redaction, cross-tenant isolation enforcement, and token/rate caps.
