# NEXUS AI — AI / LLM Engineer Job Requirements Mapping

**Access Date:** 2026-11-05  
**Sources Analysed:**
1. [Senior AI Engineer Agentic AI / Generative AI / LLM - Dice](https://www.dice.com/job-detail/effed283-6567-45ac-8539-63661ec14454) (Published 2026-11-04)
2. [AI Engineer Skills 2026: GenAI, RAG & Deployment - Technovids](https://technovids.com/ai-engineer-skills) (Published 2026-10-25)
3. [Applied AI Engineer | Roles, Skills & Career Path 2026 - Scaler](https://www.scaler.com/topics/what-is-applied-ai-engineer-role-skills-career-path/) (Published 2026-10-03)
4. [AI Engineer Job Description Template (2026) - AY Automate](https://www.ayautomate.com/blog/ai-engineer-job-description-template) (Published 2026-06-04)
5. [AI Engineer: LLMs, Generative AI and Salary - Hoorya](https://hoorya.eu/en/professions/ai-engineer/) (Accessed 2026-11-05)

## Skills-to-Implementation Traceability Matrix

| Target Engineering Role | Recurring Industry Requirement | Concrete NEXUS AI Implementation Evidence | Verification Artifact / Test |
| :--- | :--- | :--- | :--- |
| **Applied AI / LLM Engineer** | Multi-provider LLM abstraction, structured outputs, streaming, token & cost accounting | `packages/llm_core/provider.py` implementing `LLMProviderContract` with `GeminiProvider` (`gemini-3.8-flash`, `gemini-2.5-flash`, `gemini-embedding-001`), `OpenAIProvider`, and `DeterministicGroundedProvider` | `tests/test_acceptance_scenarios.py::test_provider_abstraction_and_streaming` |
| **RAG Specialist** | Hybrid search (dense vector + lexical FTS), Reciprocal Rank Fusion (RRF), reranking, metadata/RBAC pre-filtering, citation verification | `packages/retrieval/engine.py` implementing 14-stage pipeline: query preprocessing, intent classification, query expansion, dense cosine search, FTS5/tsvector BM25 search, tenant pre-filtering, RRF ($k=60$), cross-feature reranker, token-budget context builder, and citation validator | `tests/test_acceptance_scenarios.py::test_scenario_3_grounded_rag_with_citations` |
| **Agentic AI Engineer** | Stateful multi-agent workflows (LangGraph pattern), supervisor routing, durable checkpoints, human-in-the-loop (HITL) approval interrupts, bounded retries | `packages/orchestration/workflow.py` implementing 10-node supervisor graph with database-backed `AgentCheckpointStore`, step caps (`max_steps=12`), and pause/resume approval gates | `tests/test_acceptance_scenarios.py::test_scenario_6_and_7_agent_workflow_and_hitl_approval` |
| **Python Backend Engineer** | FastAPI, Pydantic validation, normalized SQL schema, migrations, async background worker, idempotency | `services/api/app/main.py` (14 versioned REST/SSE routers), `services/worker/app/worker.py` (idempotent SHA-256 ingestion pipeline), `infrastructure/database/migrations/001_initial_schema.sql` (24 normalized tables) | `tests/test_acceptance_scenarios.py::test_scenario_1_and_2_org_and_idempotent_ingestion` |
| **Application Security Engineer** | OWASP LLM Top 10 2026 defenses: prompt injection & indirect document injection guards, strict multi-tenant isolation, least-privilege tool registry | `services/api/app/core/security.py`, `packages/orchestration/tools.py` (8 allowlisted tools, no `eval`/`exec`/raw SQL), tenant-scoped queries + PostgreSQL RLS | `tests/test_acceptance_scenarios.py::test_scenario_8_and_9_security_and_prompt_injection` |
| **LLMOps & Evaluation Engineer** | Golden datasets, deterministic retrieval & faithfulness metrics (Recall@K, MRR, nDCG, Faithfulness, Citation Precision), OpenTelemetry tracing | `packages/evaluation/runner.py`, `evaluation/datasets/golden_benchmark_v1.json` (12 categories), `evaluation/reports/latest_benchmark_report.json`, `services/api/app/observability/tracer.py` | `tests/test_acceptance_scenarios.py::test_scenario_10_and_11_evaluation_and_observability` |
