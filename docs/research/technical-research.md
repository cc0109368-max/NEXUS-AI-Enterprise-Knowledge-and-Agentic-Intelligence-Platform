# NEXUS AI — Technical Research Review

**Access Date:** 2026-11-05  
**Classification:** Pre-Engineering Technical Research & Standards Verification

## 1. Enterprise LLM Application Architecture
Modern enterprise AI systems require a modular architecture separating synchronous API orchestration from asynchronous document ingestion and deterministic analytics. Rather than fragile microservices that introduce operational and network overhead early, a **Modular Monolith** with a separate background worker (`services/api` + `services/worker`) sharing strongly typed domain packages (`packages/llm_core`, `packages/retrieval`, `packages/orchestration`, `packages/evaluation`, `packages/shared_contracts`) provides strict boundary isolation while allowing independent horizontal scaling of CPU/IO-intensive ingestion and evaluation jobs.

### Key References
- **Google Gemini API Models & Interactions API** ([Google AI for Developers - Models](https://ai.google.dev/gemini-api/docs/models), accessed 2026-11-05): Verified currently supported production model identifiers:
  - Text & Reasoning: `gemini-3.8-flash` (latest high-efficiency reasoning model replacing `gemini-2.5-pro` effective Dec 1, 2026), `gemini-3.5-flash-lite` (low-latency high-volume model), and `gemini-2.5-flash` (supported for active workflows).
  - Embeddings: `gemini-embedding-001` (supports `task_type` such as `RETRIEVAL_DOCUMENT`, `RETRIEVAL_QUERY`, `QUESTION_ANSWERING`, `FACT_VERIFICATION`, trained with Matryoshka Representation Learning supporting 768, 1536, and 3072 output dimensions) and `gemini-embedding-2` (multimodal embeddings). Note: `text-embedding-004` was officially shut down on January 13, 2026 ([Gemini API Changelog](https://aistudio.google.com/docs/changelog), accessed 2026-11-05).
- **Gemini Embeddings Specification** ([Google AI Studio - Embeddings](https://aistudio.google.com/docs/embeddings), accessed 2026-11-05): Confirms that non-3072 truncated dimensions from `gemini-embedding-001` must be L2-normalized prior to cosine similarity indexing.

## 2. Advanced Retrieval-Augmented Generation (RAG)
Vector-only similarity search struggles on exact identifier lookups (such as policy clauses, SKU codes, error codes, or regulatory citations), while lexical search alone misses semantic paraphrases.

### Technical Findings
1. **Structural & Semantic Chunking**: Documents parsed from PDF (`pypdf` / `pdfplumber` / `PyMuPDF`), DOCX (`python-docx`), Markdown, and spreadsheets must preserve structural boundaries (`page_number`, `section_title`, heading hierarchy, and character offsets) so every retrieved chunk can be deterministically linked to an exact source location.
2. **Hybrid Retrieval & Reciprocal Rank Fusion (RRF)**:
   - Combining dense vector similarity (`pgvector` cosine distance `<=>`) with lexical full-text search (PostgreSQL `tsvector` / `ts_rank_cd` or SQLite `FTS5` BM25) eliminates single-modality blind spots ([Building Hybrid Search for RAG with pgvector and RRF](https://dev.to/lpossamai/building-hybrid-search-for-rag-combining-pgvector-and-full-text-search-with-reciprocal-rank-fusion-6nk), accessed 2026-11-05; [pgEdge BM25 and RRF in PostgreSQL](https://www.pgedge.com/blog/hybrid-search-in-postgresql-bm25-sparse-vectors-and-reciprocal-rank-fusion), accessed 2026-11-05).
   - **RRF Formula**: For a set of rankings $R$, the fused score for chunk $d$ is:
     $$\text{RRF\_Score}(d) = \sum_{r \in R} \frac{w_r}{k + \text{rank}_r(d)}$$
     where $k = 60$ is the standard smoothing constant that prevents outlier raw score magnitudes from dominating fusion ([Rivestack pgvector Hybrid Search RRF + FTS](https://rivestack.io/blog/hybrid-search-pgvector-postgres), accessed 2026-11-05).
3. **Tenant-Scoped Pre-Filtering vs. Post-Filtering**:
   - In `pgvector` HNSW indexes, naive post-filtering can either leak existence timing or return under-populated top-$K$ sets if the tenant owns a small fraction of rows. Enforcing `organization_id` and workspace RBAC predicates **before** candidate scoring and combining partial/partitioned indexing with PostgreSQL Row-Level Security (RLS) guarantees zero cross-tenant leakage ([All You Need to Know about PGVector Hybrid Search](https://medium.com/@aysebilgegunduz/all-you-need-to-know-about-pgvector-part-4-hybrid-search-8a655d3b0087), accessed 2026-11-05).
4. **Reranking & Citation Verification**:
   - After RRF fusion, a cross-encoder / feature-weighted reranker scores query-chunk term overlap, exact phrase matches, heading alignment, and document recency/version status.
   - Grounded generation enforces inline `[DOC-<id>:p<page>:c<chunk>]` citations, which are verified deterministically against the retrieved chunk set before returning the response.

## 3. Agentic Systems & LangGraph Orchestration
Unconstrained autonomous loops lead to unpredictable costs, tool hallucinations, and security risks.
- **Supervisor-Controlled Stateful Graph** ([LangGraph Overview](https://docs.langchain.com/oss/python/langgraph/overview), accessed 2026-11-05; [LangGraph Multi-Agent Supervisor](https://reference.langchain.com/python/langgraph-supervisor), accessed 2026-11-05): Rather than peer-to-peer chatting agents, NEXUS AI uses an explicit state machine (`AgentWorkflowState`) managed by a Supervisor router across 10 deterministic nodes:
  1. `classify_request`
  2. `plan_tasks`
  3. `retrieve_knowledge`
  4. `analyze_documents`
  5. `analyze_data`
  6. `execute_tool`
  7. `verify_evidence`
  8. `human_approval`
  9. `generate_response`
  10. `complete_workflow`
- **Durable Checkpointing & Human-in-the-Loop Interrupts** ([LangGraph Persistence](https://docs.langchain.com/oss/python/langgraph/persistence), accessed 2026-11-05; [LangGraph Interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts), accessed 2026-11-05): When an agent plans a state-changing or consequential tool invocation (such as `create_internal_task` or publishing an official compliance review report), the workflow serializes its full state checkpoint to the database (`agent_checkpoints`), creates an `approval_requests` record, and transitions to `WAITING_APPROVAL`. Execution resumes from the exact checkpoint only after an authorized `Owner`, `Admin`, or `Manager` approves the request.

## 4. LLM & RAG Evaluation Methodology
Convincing prose does not equal factual correctness.
- **Component-Wise Evaluation** ([RAGAS Available Metrics](https://docs.ragas.io/en/stable/concepts/metrics/available_metrics/), accessed 2026-11-05; [Faithfulness, Answer Relevance, and Context Precision in RAGAS](https://levelup.gitconnected.com/rag-evaluation-in-practice-faithfulness-answer-relevance-and-context-precision-in-ragas-ce13b0363cda), accessed 2026-11-05):
  - **Retrieval Metrics**: `Recall@K`, `Precision@K`, `MRR` (Mean Reciprocal Rank), and `nDCG@K` (Normalized Discounted Cumulative Gain).
  - **Generation & Grounding Metrics**: `Faithfulness` (atomic claim verification against retrieved chunks), `Answer Relevance`, `Citation Precision` (fraction of cited chunk IDs that exist in retrieved context and support the claim), `Citation Coverage`, and `Abstention Accuracy` (verifying that unanswerable or unauthorized queries explicitly abstain rather than hallucinating).
  - **Agent & Security Metrics**: Workflow routing accuracy, tool selection accuracy, schema validation pass rate, unauthorized access block rate, and indirect prompt injection resistance rate.
