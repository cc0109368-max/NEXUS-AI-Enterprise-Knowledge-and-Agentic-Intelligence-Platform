# ADR-004: Defense-in-Depth Multi-Tenant Isolation (Application Pre-Filtering + PostgreSQL RLS)

- **Status:** Accepted
- **Date:** 2026-11-05

## Context
In a multi-tenant enterprise RAG platform, a single missing `WHERE organization_id = ...` filter or an approximate vector index post-filter bug could leak confidential policy chunks across organizations.

## Options Considered
1. **Application-level filtering only**.
2. **Separate physical database per tenant**.
3. **Shared schema with mandatory `organization_id` foreign keys on all 24 tables, application-enforced `TenantContext` pre-filtering prior to vector/FTS scoring, and PostgreSQL Row-Level Security (RLS) policies**.

## Decision
Adopt Option 3.

## Technical Justification
- Every table (`documents`, `document_chunks`, `document_embeddings`, `conversations`, `messages`, `citations`, `agent_runs`, `audit_logs`, etc.) carries a non-nullable `organization_id` column.
- Vector similarity and full-text queries filter candidate rows by `organization_id` and role clearance (`min_role_required`) **before** computing similarity ranks or RRF fusion, preventing both data leakage and HNSW post-filter starvation.
- PostgreSQL RLS policies (`USING (organization_id = current_setting('app.current_org_id', true))`) act as a database-enforced backstop.

## Trade-offs & Consequences
- Requires every repository method and background worker job to pass an explicit `TenantContext`.
