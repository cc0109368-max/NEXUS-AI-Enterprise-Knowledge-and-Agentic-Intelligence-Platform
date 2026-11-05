#!/usr/bin/env python3
'''
CLI Runner for NEXUS AI 12-Category Evaluation & Benchmarking Suite.
Saves machine-readable JSON and human-reviewable Markdown benchmark reports.
'''
import json
import tempfile
from pathlib import Path
from packages.evaluation.runner import EvaluationBenchmarkEngine

def main():
    engine = EvaluationBenchmarkEngine()
    result = engine.run_benchmark_suite("nexus_golden_benchmark_v1")
    summary = result["summary"]

    roots = [
        Path(tempfile.gettempdir()) / "nexus-ai",
        Path(__file__).resolve().parent.parent,
    ]
    md_lines = [
        "# NEXUS AI — Reproducible Evaluation & Benchmark Report",
        f"**Run ID:** `{result['evaluation_run_id']}`  ",
        f"**Dataset Version:** `{summary['dataset_version']}`  ",
        f"**Executed At:** `{result['created_at']}`  ",
        f"**Total Cases:** `{summary['total_cases']}` | **Passed:** `{summary['passed_cases']}` (`{summary['pass_rate'] * 100:.1f}%`)",
        "",
        "## 1. Aggregate Quality & Operational Metrics",
        "| Metric | Value | Notes |",
        "| :--- | :--- | :--- |",
        f"| **Pass Rate (12 Categories)** | `{summary['pass_rate'] * 100:.1f}%` | `{summary['passed_cases']}/{summary['total_cases']}` cases verified |",
        f"| **Mean Recall@5** | `{summary['mean_recall_at_k']:.4f}` | Hybrid Dense + FTS5 + RRF (k=60) |",
        f"| **Mean Precision@5** | `{summary['mean_precision_at_k']:.4f}` | Post-reranker top-K precision |",
        f"| **Mean Reciprocal Rank (MRR)** | `{summary['mean_mrr']:.4f}` | Rank of first ground-truth document |",
        f"| **Mean nDCG@5** | `{summary['mean_ndcg']:.4f}` | Normalized Discounted Cumulative Gain |",
        f"| **Mean Faithfulness** | `{summary['mean_faithfulness']:.4f}` | Grounded claim token support ratio |",
        f"| **Mean Citation Precision** | `{summary['mean_citation_precision']:.4f}` | Verified inline `[DOC-...]` resolution rate |",
        f"| **Average Case Latency** | `{summary['avg_case_latency_ms']:.2f} ms` | End-to-end retrieval + orchestration |",
        "",
        "## 2. Per-Category Results Breakdown",
        "| Case ID | Category | Passed | Recall@5 | MRR | nDCG@5 | Faithfulness | Cit. Precision | Latency (ms) |",
        "| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |",
    ]
    for c in result["cases"]:
        status_str = "PASS" if c["passed"] else "FAIL"
        md_lines.append(
            f"| `{c['case_id']}` | `{c['category']}` | **{status_str}** | `{c['recall_at_k']:.2f}` | `{c['mrr']:.2f}` | `{c['ndcg']:.2f}` | `{c['faithfulness']:.2f}` | `{c['citation_precision']:.2f}` | `{c['latency_ms']:.1f}` |"
        )

    md_lines.extend([
        "",
        "## 3. Methodology & Limitations",
        f"- **Methodology**: {summary['methodology_note']}",
        "- **Limitations**: Benchmark corpus is a controlled 6-document multi-tenant reference dataset designed for deterministic regression verification. Live Gemini API latency and LLM-as-judge variance should be measured separately when `GEMINI_API_KEY` is connected in staging/production.",
    ])

    for r in roots:
        rep_dir = r / "evaluation/reports"
        ds_dir = r / "evaluation/datasets"
        rep_dir.mkdir(parents=True, exist_ok=True)
        ds_dir.mkdir(parents=True, exist_ok=True)
        (rep_dir / "latest_benchmark_report.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        (rep_dir / "latest_benchmark_report.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        (ds_dir / "golden_benchmark_v1.json").write_text(json.dumps(result["cases"], indent=2), encoding="utf-8")

    print(json.dumps(summary, indent=2))

if __name__ == "__main__":
    main()
