# NEXUS AI — Operations Troubleshooting Guide

## 1. Document Ingestion Stuck in `PROCESSING` or `FAILED`
- **Symptom**: Document status shows `FAILED` or `QUARANTINED` in Document Processing Monitor.
- **Root Causes & Resolution**:
  1. **Scanned PDF without extractable text**: NEXUS AI detects 0 characters extracted across pages and sets `error_message = "Scanned PDF detected: no extractable text layer found and OCR is disabled in current environment."` Re-upload a text-layer PDF or enable OCR preprocessing.
  2. **Duplicate Upload**: If an identical SHA-256 payload is uploaded to the same workspace, the idempotent ingestion pipeline links to the existing version rather than duplicating chunks.
  3. **Retry Execution**: Trigger `POST /api/v1/documents/{doc_id}/reindex` with a fresh idempotency key.

## 2. High Abstention Rate in RAG Queries
- **Symptom**: Assistant replies that verified evidence is unavailable in the knowledge base.
- **Diagnostic Steps**:
  1. Inspect the retrieval trace in the **Observability Dashboard** (`/api/v1/observability/traces`).
  2. Check whether candidate documents have `min_role_required` higher than the querying user's role (`MEMBER` vs `ADMIN`).
  3. Verify `Recall@K` and `RRF` fusion weights in the **Evaluation Dashboard**.

## 3. Agent Workflow Paused in `WAITING_APPROVAL`
- **Symptom**: Agent run does not complete immediately when executing action requests.
- **Resolution**: This is expected secure-by-default behavior for consequential tools (`create_internal_task`). Navigate to the **Agent Workflow Monitor** (`GET /api/v1/agents/approvals`) as a `MANAGER`, `ADMIN`, or `OWNER` and approve or reject the checkpointed request.
