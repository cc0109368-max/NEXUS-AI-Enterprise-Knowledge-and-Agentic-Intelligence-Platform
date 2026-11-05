# ADR-003: Hybrid Dense + Lexical Retrieval with Reciprocal Rank Fusion (RRF)

- **Status:** Accepted
- **Date:** 2026-11-05

## Context
Enterprise documents contain both conceptual policy prose and exact alphanumeric identifiers (clause numbers like `SEC-4.2`, retention periods like `7 years`, SKU IDs, and regulatory codes). Pure vector similarity frequently ranks semantically similar paragraphs above exact identifier matches, whereas pure keyword search fails on synonyms and conceptual questions.

## Options Considered
1. **Dense Vector Search Only (`pgvector` cosine similarity)**.
2. **Linear Convex Combination of Raw Cosine and BM25 Scores** ($lpha \cdot 	ext{cosine} + (1-lpha) \cdot 	ext{BM25}$).
3. **Hybrid Dense + Lexical Search Combined via Reciprocal Rank Fusion (RRF, $k=60$) Followed by Cross-Feature Reranking**.

## Decision
Adopt Option 3.

## Technical Justification
- Raw cosine similarity ($[-1, 1]$) and unbounded BM25 scores have incompatible distributions that vary wildly per query, making linear score combination brittle without per-corpus calibration.
- Reciprocal Rank Fusion ($\sum rac{w_r}{60 + 	ext{rank}_r}$) is scale-invariant and consistently outperforms single-modality retrieval across both factual and multi-hop queries.
- Post-RRF reranking incorporates exact keyphrase overlap, section heading hits, and document version currency.

## Trade-offs & Consequences
- Executes two indexed sub-queries (dense + lexical) per retrieval call, adding ~4–12 ms of database execution time, which is well within our `<100 ms` retrieval latency target.
