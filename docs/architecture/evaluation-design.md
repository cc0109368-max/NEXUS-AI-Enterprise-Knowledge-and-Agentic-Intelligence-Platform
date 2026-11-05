# NEXUS AI — Evaluation & Benchmarking Architecture

## Deterministic & Reproducible Evaluation Design
The evaluation engine (`packages/evaluation/runner.py`) evaluates 12 distinct test categories defined in `evaluation/datasets/golden_benchmark_v1.json`:
1. `simple_factual`: Direct policy lookup with exact page citation.
2. `multi_document`: Synthesizing facts across Security Policy and Engineering Handbook.
3. `multi_hop`: Connecting retention tier classification to encryption key rotation schedules.
4. `document_comparison`: Detecting exact changes between Data Retention Policy v1.0 and v2.0.
5. `unanswerable`: Querying nonexistent benefits/policies to verify strict abstention (`abstained = True`).
6. `ambiguous`: Handling underspecified queries by surfacing scoped evidence across matching documents.
7. `conflicting_sources`: Resolving version precedence between superseded v1.0 and active v2.0 policy documents.
8. `prompt_injection`: Blocking direct jailbreaks and indirect document-embedded override instructions.
9. `unauthorized_access`: Blocking `MEMBER` access to `RESTRICTED` executive documents and cross-tenant documents.
10. `tool_selection`: Verifying supervisor selects `compare_documents`, `analyse_csv`, or `create_internal_task` accurately.
11. `tool_execution`: Validating deterministic numerical output from `analyse_csv` and `calculate_metrics`.
12. `structured_extraction`: Extracting typed compliance metadata with 100% citation precision.

## Mathematical Metric Definitions
- **Recall@K**: $|\text{Relevant} \cap \text{Retrieved@K}| / |\text{Relevant}|$
- **Precision@K**: $|\text{Relevant} \cap \text{Retrieved@K}| / K$
- **Mean Reciprocal Rank (MRR)**: $\frac{1}{|Q|} \sum_{i=1}^{|Q|} \frac{1}{\text{rank}_i}$
- **nDCG@K**: $\text{DCG@K} / \text{IDCG@K}$ where $\text{DCG@K} = \sum_{i=1}^K \frac{rel_i}{\log_2(i+1)}$
- **Faithfulness**: Fraction of atomic factual statements/clauses in the generated answer supported by retrieved chunks.
- **Citation Precision**: Fraction of inline citations `[DOC-...]` that resolve to valid retrieved chunks containing supporting terms.
