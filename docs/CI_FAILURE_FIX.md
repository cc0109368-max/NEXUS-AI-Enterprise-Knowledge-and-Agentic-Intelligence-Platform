# NEXUS AI — GitHub Actions CI Failure Root Cause & Resolution Report

**Date:** 2026-11-05  
**Author:** Senior Python Backend & DevOps Engineering  
**Status:** Resolved & Verified  

---

## 1. Executive Summary
A GitHub Actions CI build failure was identified on branch `main` during test execution:
```
ModuleNotFoundError: No module named 'docx'
Location: tests/test_acceptance_scenarios.py, line 7
Code: import docx
```
This failure was caused by the absence of dependency manifests (`requirements.txt`, `pyproject.toml`) and the omission of a dependency installation step in `.github/workflows/ci.yml` following the `actions/setup-python@v5` step.

This issue has been resolved. The canonical runtime and development dependencies were defined, `python-docx` and all required backend packages were specified with compatible constraints, cross-platform path handling was hardened, and the complete test and benchmark suites were executed and verified locally.

---

## 2. Root Cause Analysis
1. **Missing Dependency Manifests:**
   The repository lacked a canonical `requirements.txt`, `requirements-dev.txt`, and `pyproject.toml`.
2. **Missing Dependency Installation Step in CI:**
   The GitHub Actions workflow `.github/workflows/ci.yml` configured Python 3.11 using `actions/setup-python@v5`, but immediately invoked `python3 -m unittest discover ...` without executing `pip install`. In a clean Ubuntu GitHub Actions runner, external libraries (`python-docx`, `pypdf`, `openpyxl`, `pandas`, `fastapi`, `httpx`, `numpy`, `pydantic`) are not pre-installed.
3. **DOCX Parsing as Application Feature:**
   `docx` is imported by `services/api/app/documents/service.py` and `tests/test_acceptance_scenarios.py` to parse `.docx` files during document ingestion. It is provided by the `python-docx` package on PyPI.
4. **Hardcoded Temporary File Paths:**
   Hardcoded `/tmp/nexus-ai` paths in `services/api/app/core/config.py`, `services/api/app/documents/service.py`, and `scripts/run_benchmarks.py` caused Windows `PermissionError: [WinError 5]` when creating directories outside POSIX environments.

---

## 3. Modified & Created Files

| File | Status | Description |
| :--- | :--- | :--- |
| `requirements.txt` | **Created** | Canonical runtime dependencies (`fastapi`, `uvicorn`, `pydantic`, `python-docx`, `pypdf`, `openpyxl`, `pandas`, `numpy`, `httpx`) with compatible version constraints. |
| `requirements-dev.txt` | **Created** | Development/CI dependency manifest referencing `-r requirements.txt` to eliminate duplicate definitions. |
| `pyproject.toml` | **Created** | PEP 621 packaging configuration using dynamic dependencies linked to `requirements.txt`. |
| `.github/workflows/ci.yml` | **Updated** | Added pip dependency caching, `pip install -r requirements-dev.txt`, dependency pre-verification, and adjusted `PYTHONPATH`. |
| `infrastructure/docker/Dockerfile.api` | **Updated** | Added `COPY requirements.txt` and `RUN pip install --no-cache-dir -r requirements.txt`. |
| `infrastructure/docker/Dockerfile.worker` | **Updated** | Added `COPY requirements.txt` and `RUN pip install --no-cache-dir -r requirements.txt`. |
| `services/api/app/core/config.py` | **Updated** | Uses `tempfile.gettempdir()` for cross-platform SQLite default path. |
| `services/api/app/documents/service.py` | **Updated** | Uses `tempfile.gettempdir()` for cross-platform document storage directory. |
| `scripts/run_benchmarks.py` | **Updated** | Uses `tempfile.gettempdir()` and repository root for benchmark outputs. |
| `README.md` | **Updated** | Documented virtual environment setup and dependency installation in Section 10. |
| `docs/operations/deployment-runbook.md` | **Updated** | Added dependency installation commands under Section 2. |
| `docs/CI_FAILURE_FIX.md` | **Created** | This comprehensive diagnostic and verification report. |

---

## 4. Verification & Test Execution Results

### 4.1 Dependency Import Verification
```bash
python -c "import docx; print('python-docx import successful')"
```
**Output:**
```
python-docx import successful
```

```bash
python -c "import openpyxl, pypdf, pandas, numpy, fastapi, httpx; print('all core dependencies import successful')"
```
**Output:**
```
all core dependencies import successful
```

### 4.2 Acceptance & Security Test Suite
```bash
PYTHONPATH=services/api:. python -m unittest discover -s tests -p "test_*.py" -v
```
**Output:**
```
test_01_authentication_refresh_rotation_and_invalid_credentials (test_acceptance_scenarios.TestNexusAIAcceptanceAndSecuritySuite.test_01_authentication_refresh_rotation_and_invalid_credentials)
Tests Scenario 1 Auth + refresh token rotation + invalid credential failure. ... ok
test_02_scenario_1_and_2_multi_format_ingestion_and_idempotency (test_acceptance_scenarios.TestNexusAIAcceptanceAndSecuritySuite.test_02_scenario_1_and_2_multi_format_ingestion_and_idempotency)
Tests Scenario 1 & 2: Upload & parse MD, DOCX, XLSX, CSV, PDF + idempotency + failure modes. ... ok
test_03_scenario_3_grounded_rag_citations_and_abstention (test_acceptance_scenarios.TestNexusAIAcceptanceAndSecuritySuite.test_03_scenario_3_grounded_rag_citations_and_abstention)
Tests Scenario 3: Hybrid RRF retrieval, verified citations, and abstention on unanswerable queries. ... ok
test_04_scenario_4_document_version_comparison_and_report (test_acceptance_scenarios.TestNexusAIAcceptanceAndSecuritySuite.test_04_scenario_4_document_version_comparison_and_report)
Tests Scenario 4: Compare v1 and v2 of Data Retention Policy with source citations. ... ok
test_05_scenario_5_deterministic_spreadsheet_analytics (test_acceptance_scenarios.TestNexusAIAcceptanceAndSecuritySuite.test_05_scenario_5_deterministic_spreadsheet_analytics)
Tests Scenario 5: Deterministic Pandas calculations on ingested XLSX dataset. ... ok
test_06_scenario_6_and_7_langgraph_supervisor_and_hitl_approval_gate (test_acceptance_scenarios.TestNexusAIAcceptanceAndSecuritySuite.test_06_scenario_6_and_7_langgraph_supervisor_and_hitl_approval_gate)
Tests Scenario 6 & 7: Supervisor routing, human approval pause, checkpointing, and resumption. ... ok
test_07_scenario_8_and_9_cross_tenant_isolation_rbac_and_prompt_injection (test_acceptance_scenarios.TestNexusAIAcceptanceAndSecuritySuite.test_07_scenario_8_and_9_cross_tenant_isolation_rbac_and_prompt_injection)
Tests Scenario 8 & 9: Cross-tenant block, RBAC block, and direct/indirect prompt injection. ... ok
test_08_scenario_10_11_12_conversations_sse_observability_and_fastapi_endpoints (test_acceptance_scenarios.TestNexusAIAcceptanceAndSecuritySuite.test_08_scenario_10_11_12_conversations_sse_observability_and_fastapi_endpoints)
Tests Conversation SSE streaming, Observability metrics, Audit logs, and FastAPI HTTP routes. ... ok

----------------------------------------------------------------------
Ran 8 tests in 2.169s

OK
```

### 4.3 Reproducible RAG & Agent Benchmark Suite
```bash
PYTHONPATH=services/api:. python scripts/run_benchmarks.py
```
**Output:**
```json
{
  "suite_name": "nexus_golden_benchmark_v1",
  "dataset_version": "1.0.0-synthetic-reference",
  "total_cases": 12,
  "passed_cases": 12,
  "pass_rate": 1.0,
  "mean_recall_at_k": 1.0,
  "mean_precision_at_k": 1.0,
  "mean_mrr": 1.0,
  "mean_ndcg": 1.0,
  "mean_faithfulness": 0.9639,
  "mean_citation_precision": 1.0,
  "avg_case_latency_ms": 39.1,
  "total_duration_ms": 750.58,
  "methodology_note": "Evaluated on NEXUS AI 12-category synthetic enterprise reference dataset using deterministic retrieval, citation verification, RBAC/tenant security checks, and Pandas analytics verification."
}
```

---

## 5. Security & Integrity Audit
- **Zero Exposed Credentials:** Verified `.env.example`, `.github/workflows/ci.yml`, and codebase contain no active or exposed API keys, private tokens, or secrets.
- **No Mock Degradation:** All test assertions remain intact; no tests were weakened or skipped.
- **Architectural Scope Maintained:** No frontend or unrelated system architectures were modified.
