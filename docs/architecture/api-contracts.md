# NEXUS AI — Versioned REST & SSE API Contracts (`/api/v1`)

All endpoints use a standardized envelope (`ApiResponse[T]` with `success`, `data`, `meta`, `trace_id`) and standardized error payload (`ApiError` with `error_code`, `message`, `details`, `trace_id`).

## Endpoint Catalog
1. **Health & Readiness**: `GET /api/v1/health`, `GET /api/v1/ready`
2. **Authentication (`/api/v1/auth`)**: `POST /register`, `POST /login`, `POST /refresh`, `GET /me`
3. **Organizations & Workspaces (`/api/v1/organizations`)**: `POST /`, `GET /`, `POST /{org_id}/workspaces`, `GET /{org_id}/workspaces`, `POST /{org_id}/invitations`, `GET /{org_id}/members`, `PATCH /{org_id}/members/{user_id}`
4. **Documents & Ingestion (`/api/v1/documents`)**: `POST /upload`, `GET /`, `GET /{doc_id}`, `GET /{doc_id}/versions`, `GET /{doc_id}/chunks`, `DELETE /{doc_id}`, `POST /{doc_id}/reindex`, `GET /ingestion-jobs`
5. **Advanced Retrieval (`/api/v1/retrieval`)**: `POST /search`, `GET /citations/{citation_id}`
6. **Conversations & Streaming (`/api/v1/conversations`)**: `POST /`, `GET /`, `GET /{conv_id}`, `POST /{conv_id}/messages`, `GET /{conv_id}/stream` (SSE), `POST /messages/{msg_id}/feedback`, `DELETE /{conv_id}`
7. **Multi-Agent Workflows & Approvals (`/api/v1/agents`)**: `POST /run`, `GET /runs`, `GET /runs/{run_id}`, `GET /approvals`, `POST /approvals/{approval_id}/decide`
8. **Data Analytics (`/api/v1/analytics`)**: `GET /datasets`, `POST /datasets/{dataset_id}/query`, `GET /datasets/{dataset_id}/profile`
9. **Document Comparison & Reports (`/api/v1/reports`)**: `POST /compare`, `POST /generate`, `GET /`
10. **Evaluation & Benchmarking (`/api/v1/evaluation`)**: `POST /runs`, `GET /runs`, `GET /runs/{run_id}`
11. **Observability & Audit (`/api/v1/observability`, `/api/v1/audit`)**: `GET /observability/metrics`, `GET /observability/traces`, `GET /audit/logs`
