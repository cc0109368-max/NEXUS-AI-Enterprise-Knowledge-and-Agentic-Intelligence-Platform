# NEXUS AI — Advanced Hybrid RAG Pipeline Architecture

## 14-Stage Retrieval & Grounded Generation Pipeline
1. **Query Preprocessing**: Normalizes whitespace, strips control characters, and runs `PromptInjectionGuard.inspect_query()`.
2. **Intent & Retrieval Classification**: Classifies request into `factual_lookup`, `policy_comparison`, `multi_hop_research`, `data_analytics`, or `action_workflow`.
3. **Query Expansion**: Expands domain terminology and acronyms while preserving exact quoted identifiers.
4. **Permission & Tenant Pre-Filtering**: Builds a strict SQL predicate restricting candidate chunks to `organization_id = :org_id`, authorized `workspace_id`, and user role level $\ge$ `document.min_role_required`. Quarantined prompt-injection chunks are excluded from active instruction synthesis.
5. **Dense Vector Retrieval**: Embeds the query using `gemini-embedding-001` (`task_type="RETRIEVAL_QUERY"`) and computes cosine similarity against normalized chunk embeddings.
6. **Lexical Full-Text Retrieval**: Executes BM25 lexical scoring via PostgreSQL `ts_rank_cd(to_tsvector('english', content), websearch_to_tsquery(:q))` or SQLite `FTS5` virtual table matching.
7. **Metadata Filtering**: Applies optional user filters (`document_ids`, `classification`, `version_number`, `section_title`).
8. **Reciprocal Rank Fusion (RRF)**: Combines dense rank $r_d(c)$ and lexical rank $r_l(c)$ using:
   $$\text{RRF}(c) = \frac{w_{\text{dense}}}{60 + r_d(c)} + \frac{w_{\text{lexical}}}{60 + r_l(c)}$$
9. **Cross-Feature Reranking**: Adjusts fused scores using exact query keyphrase overlap, section heading alignment, and latest-version boost.
10. **Context Selection & Deduplication**: Eliminates near-duplicate chunks and orders evidence by relevance.
11. **Context-Window Token Budgeting**: Enforces `max_context_tokens` (default `6000` tokens), truncating lower-ranked chunks cleanly at chunk boundaries.
12. **Grounded Answer Generation**: Formats evidence inside `<untrusted_document_evidence id="DOC-...">` blocks and instructs the LLM to answer strictly from evidence with inline `[DOC-<doc_id>:v<ver>:p<page>:c<chunk_idx>]` citations.
13. **Citation Validation & Abstention Check**: Parses every emitted citation tag, verifies that the referenced `chunk_id`, `document_id`, and `page_number` exist in the authorized retrieved set, and triggers explicit abstention if evidence is missing or insufficient.
14. **Retrieval Trace Recording**: Persists candidate counts, dense vs. lexical ranks, RRF scores, rerank deltas, and latency in the observability trace.
