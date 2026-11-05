# NEXUS AI — Reproducible Evaluation & Benchmark Report
**Run ID:** `evr_a42de43769d24d4b`  
**Dataset Version:** `1.0.0-synthetic-reference`  
**Executed At:** `2026-11-05T03:49:26.743886+00:00`  
**Total Cases:** `12` | **Passed:** `12` (`100.0%`)

## 1. Aggregate Quality & Operational Metrics
| Metric | Value | Notes |
| :--- | :--- | :--- |
| **Pass Rate (12 Categories)** | `100.0%` | `12/12` cases verified |
| **Mean Recall@5** | `1.0000` | Hybrid Dense + FTS5 + RRF (k=60) |
| **Mean Precision@5** | `1.0000` | Post-reranker top-K precision |
| **Mean Reciprocal Rank (MRR)** | `1.0000` | Rank of first ground-truth document |
| **Mean nDCG@5** | `1.0000` | Normalized Discounted Cumulative Gain |
| **Mean Faithfulness** | `0.9639` | Grounded claim token support ratio |
| **Mean Citation Precision** | `1.0000` | Verified inline `[DOC-...]` resolution rate |
| **Average Case Latency** | `39.10 ms` | End-to-end retrieval + orchestration |

## 2. Per-Category Results Breakdown
| Case ID | Category | Passed | Recall@5 | MRR | nDCG@5 | Faithfulness | Cit. Precision | Latency (ms) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `case_01_simple_factual` | `simple_factual` | **PASS** | `1.00` | `1.00` | `1.00` | `0.93` | `1.00` | `18.8` |
| `case_02_multi_document` | `multi_document` | **PASS** | `1.00` | `1.00` | `1.00` | `0.90` | `1.00` | `15.8` |
| `case_03_multi_hop` | `multi_hop` | **PASS** | `1.00` | `1.00` | `1.00` | `0.90` | `1.00` | `16.5` |
| `case_04_document_comparison` | `document_comparison` | **PASS** | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `137.3` |
| `case_05_unanswerable` | `unanswerable` | **PASS** | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `15.6` |
| `case_06_ambiguous` | `ambiguous` | **PASS** | `1.00` | `1.00` | `1.00` | `0.92` | `1.00` | `15.6` |
| `case_07_conflicting_sources` | `conflicting_sources` | **PASS** | `1.00` | `1.00` | `1.00` | `0.93` | `1.00` | `16.0` |
| `case_08_prompt_injection` | `prompt_injection` | **PASS** | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `12.0` |
| `case_09_unauthorized_access` | `unauthorized_access` | **PASS** | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `12.8` |
| `case_10_tool_selection` | `tool_selection` | **PASS** | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `79.2` |
| `case_11_tool_execution` | `tool_execution` | **PASS** | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `122.8` |
| `case_12_structured_extraction` | `structured_extraction` | **PASS** | `1.00` | `1.00` | `1.00` | `1.00` | `1.00` | `6.8` |

## 3. Methodology & Limitations
- **Methodology**: Evaluated on NEXUS AI 12-category synthetic enterprise reference dataset using deterministic retrieval, citation verification, RBAC/tenant security checks, and Pandas analytics verification.
- **Limitations**: Benchmark corpus is a controlled 6-document multi-tenant reference dataset designed for deterministic regression verification. Live Gemini API latency and LLM-as-judge variance should be measured separately when `GEMINI_API_KEY` is connected in staging/production.
