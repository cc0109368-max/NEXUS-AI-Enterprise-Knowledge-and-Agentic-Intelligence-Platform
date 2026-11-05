# NEXUS AI — Database Architecture & Schema Design

## Core Entities (24 Normalized Tables)
1. `users`: `id`, `email` (UNIQUE), `password_hash`, `full_name`, `is_active`, `created_at`, `updated_at`
2. `organizations`: `id`, `name`, `slug` (UNIQUE), `plan_tier`, `max_monthly_tokens`, `created_at`
3. `organization_members`: `id`, `organization_id` (FK), `user_id` (FK), `role` (`OWNER`, `ADMIN`, `MANAGER`, `MEMBER`), `joined_at` — UNIQUE(`organization_id`, `user_id`)
4. `workspaces`: `id`, `organization_id` (FK), `name`, `description`, `access_level`, `created_by`, `created_at`
5. `invitations`: `id`, `organization_id` (FK), `email`, `role`, `token_hash` (UNIQUE), `status`, `expires_at`, `created_by`
6. `documents`: `id`, `organization_id` (FK), `workspace_id` (FK), `title`, `filename`, `mime_type`, `file_size_bytes`, `sha256_hash`, `current_version`, `classification` (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`), `min_role_required`, `status`, `uploaded_by`, `created_at`, `updated_at`
7. `document_versions`: `id`, `document_id` (FK), `organization_id` (FK), `version_number`, `sha256_hash`, `storage_path`, `page_count`, `word_count`, `parser_used`, `change_summary`, `created_by`, `created_at`
8. `document_chunks`: `id`, `document_id` (FK), `document_version_id` (FK), `organization_id` (FK), `workspace_id` (FK), `chunk_index`, `page_number`, `section_title`, `content`, `token_count`, `char_start`, `char_end`, `metadata_json`, `is_Quarantined_injection`, `created_at`
9. `document_embeddings`: `id`, `chunk_id` (FK UNIQUE), `organization_id` (FK), `embedding_model`, `dimensions`, `vector_json` / `embedding vector(768)`, `created_at`
10. `ingestion_jobs`: `id`, `organization_id` (FK), `document_id` (FK), `document_version_id` (FK), `idempotency_key` (UNIQUE), `status` (`QUEUED`, `PROCESSING`, `COMPLETED`, `FAILED`), `attempt_count`, `max_attempts`, `error_message`, `started_at`, `completed_at`, `created_at`
11. `conversations`: `id`, `organization_id` (FK), `workspace_id` (FK), `user_id` (FK), `title`, `is_archived`, `created_at`, `updated_at`
12. `messages`: `id`, `conversation_id` (FK), `organization_id` (FK), `role` (`user`, `assistant`, `system`), `content`, `abstained`, `abstention_reason`, `faithfulness_score`, `prompt_tokens`, `completion_tokens`, `latency_ms`, `trace_id`, `feedback_rating`, `feedback_comment`, `created_at`
13. `citations`: `id`, `message_id` (FK), `organization_id` (FK), `document_id` (FK), `document_version_id` (FK), `chunk_id` (FK), `citation_key`, `page_number`, `section_title`, `excerpt`, `relevance_score`, `verified`
14. `agent_runs`: `id`, `organization_id` (FK), `workspace_id` (FK), `user_id` (FK), `conversation_id` (FK), `intent`, `status` (`RUNNING`, `WAITING_APPROVAL`, `COMPLETED`, `FAILED`, `CANCELLED`), `current_node`, `step_count`, `max_steps`, `input_query`, `final_output`, `error_message`, `trace_id`, `started_at`, `completed_at`
15. `agent_checkpoints`: `id`, `agent_run_id` (FK), `organization_id` (FK), `step_number`, `node_name`, `state_json`, `created_at`
16. `tool_executions`: `id`, `agent_run_id` (FK), `organization_id` (FK), `tool_name`, `idempotency_key`, `arguments_json`, `result_json`, `status`, `duration_ms`, `requires_approval`, `approved_by`, `created_at`
17. `approval_requests`: `id`, `organization_id` (FK), `agent_run_id` (FK), `tool_name`, `action_summary`, `payload_json`, `requested_by`, `status` (`PENDING`, `APPROVED`, `REJECTED`), `reviewed_by`, `review_note`, `created_at`, `resolved_at`
18. `datasets`: `id`, `organization_id` (FK), `workspace_id` (FK), `document_id` (FK), `name`, `row_count`, `column_count`, `schema_json`, `summary_stats_json`, `created_at`
19. `evaluation_runs`: `id`, `organization_id` (FK), `suite_name`, `dataset_version`, `total_cases`, `passed_cases`, `metrics_summary_json`, `status`, `duration_ms`, `created_at`
20. `evaluation_cases`: `id`, `category`, `query`, `expected_doc_ids_json`, `expected_answer_keywords_json`, `expect_abstention`, `expect_security_block`, `expected_tool`, `created_at`
21. `evaluation_results`: `id`, `evaluation_run_id` (FK), `case_id` (FK), `passed`, `recall_at_k`, `precision_at_k`, `mrr`, `ndcg`, `faithfulness`, `citation_precision`, `actual_output`, `latency_ms`, `details_json`
22. `model_usage`: `id`, `organization_id` (FK), `user_id` (FK), `trace_id`, `provider`, `model_name`, `operation_type`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `estimated_cost_usd`, `latency_ms`, `created_at`
23. `audit_logs`: `id`, `organization_id` (FK), `actor_user_id`, `event_type`, `resource_type`, `resource_id`, `action`, `status`, `ip_address`, `metadata_json`, `created_at`
24. `internal_tasks`: `id`, `organization_id` (FK), `workspace_id` (FK), `title`, `description`, `priority`, `assignee_email`, `status`, `created_by_agent_run_id`, `idempotency_key` (UNIQUE), `created_at`

## Tenant Isolation & Indexing Strategy
- Every tenant-owned table carries a mandatory `organization_id` foreign key and composite B-Tree index `(organization_id, id)` or `(organization_id, created_at DESC)`.
- In PostgreSQL (`infrastructure/database/migrations/001_initial_schema.sql`), Row-Level Security (`ENABLE ROW LEVEL SECURITY`) is configured with `USING (organization_id = current_setting('app.current_org_id', true))`.
- For vector search, HNSW indexing on `document_embeddings` is paired with mandatory pre-filtering on `organization_id` and `min_role_required` so approximate nearest-neighbor traversal never leaks across tenants.
