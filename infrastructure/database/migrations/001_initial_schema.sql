-- NEXUS AI — Enterprise Knowledge & Agentic Intelligence Platform
-- Migration 001: Core 24 Normalized Entities, pgvector HNSW, Full-Text GIN, and Row-Level Security (RLS)

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS organizations (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    slug TEXT UNIQUE NOT NULL,
    plan_tier TEXT NOT NULL DEFAULT 'ENTERPRISE',
    max_monthly_tokens BIGINT NOT NULL DEFAULT 10000000,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS organization_members (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'MANAGER', 'MEMBER')),
    joined_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (organization_id, user_id)
);

CREATE TABLE IF NOT EXISTS workspaces (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    access_level TEXT NOT NULL DEFAULT 'ORG_WIDE',
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS invitations (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('OWNER', 'ADMIN', 'MANAGER', 'MEMBER')),
    token_hash TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'PENDING',
    expires_at TIMESTAMPTZ NOT NULL,
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    file_size_bytes BIGINT NOT NULL,
    sha256_hash TEXT NOT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    classification TEXT NOT NULL DEFAULT 'INTERNAL' CHECK (classification IN ('PUBLIC', 'INTERNAL', 'CONFIDENTIAL', 'RESTRICTED')),
    min_role_required TEXT NOT NULL DEFAULT 'MEMBER' CHECK (min_role_required IN ('MEMBER', 'MANAGER', 'ADMIN', 'OWNER')),
    status TEXT NOT NULL DEFAULT 'PENDING',
    uploaded_by TEXT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_versions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    storage_path TEXT NOT NULL,
    page_count INTEGER NOT NULL DEFAULT 1,
    word_count INTEGER NOT NULL DEFAULT 0,
    parser_used TEXT NOT NULL,
    change_summary TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, version_number)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    page_number INTEGER NOT NULL DEFAULT 1,
    section_title TEXT NOT NULL DEFAULT 'General',
    content TEXT NOT NULL,
    content_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    token_count INTEGER NOT NULL,
    char_start INTEGER NOT NULL DEFAULT 0,
    char_end INTEGER NOT NULL DEFAULT 0,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_quarantined_injection BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS document_embeddings (
    id TEXT PRIMARY KEY,
    chunk_id TEXT UNIQUE NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL DEFAULT 'gemini-embedding-001',
    dimensions INTEGER NOT NULL DEFAULT 768,
    embedding vector(768) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    idempotency_key TEXT UNIQUE NOT NULL,
    status TEXT NOT NULL DEFAULT 'QUEUED',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    error_message TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    abstained BOOLEAN NOT NULL DEFAULT FALSE,
    abstention_reason TEXT,
    faithfulness_score DOUBLE PRECISION DEFAULT 1.0,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    trace_id TEXT,
    feedback_rating INTEGER,
    feedback_comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS citations (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    document_version_id TEXT NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    chunk_id TEXT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
    citation_key TEXT NOT NULL,
    page_number INTEGER NOT NULL,
    section_title TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    relevance_score DOUBLE PRECISION NOT NULL,
    verified BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_id TEXT,
    intent TEXT NOT NULL,
    status TEXT NOT NULL,
    current_node TEXT NOT NULL,
    step_count INTEGER NOT NULL DEFAULT 0,
    max_steps INTEGER NOT NULL DEFAULT 12,
    input_query TEXT NOT NULL,
    final_output TEXT,
    error_message TEXT,
    trace_id TEXT NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id TEXT PRIMARY KEY,
    agent_run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    step_number INTEGER NOT NULL,
    node_name TEXT NOT NULL,
    state_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tool_executions (
    id TEXT PRIMARY KEY,
    agent_run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    arguments_json JSONB NOT NULL,
    result_json JSONB,
    status TEXT NOT NULL,
    duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    requires_approval BOOLEAN NOT NULL DEFAULT FALSE,
    approved_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS approval_requests (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    agent_run_id TEXT NOT NULL REFERENCES agent_runs(id) ON DELETE CASCADE,
    tool_name TEXT NOT NULL,
    action_summary TEXT NOT NULL,
    payload_json JSONB NOT NULL,
    requested_by TEXT NOT NULL REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING', 'APPROVED', 'REJECTED')),
    reviewed_by TEXT REFERENCES users(id),
    review_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS datasets (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    column_count INTEGER NOT NULL,
    schema_json JSONB NOT NULL,
    summary_stats_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluation_runs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    suite_name TEXT NOT NULL,
    dataset_version TEXT NOT NULL,
    total_cases INTEGER NOT NULL,
    passed_cases INTEGER NOT NULL,
    metrics_summary_json JSONB NOT NULL,
    status TEXT NOT NULL,
    duration_ms DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluation_cases (
    id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    query TEXT NOT NULL,
    expected_doc_ids_json JSONB NOT NULL,
    expected_answer_keywords_json JSONB NOT NULL,
    expect_abstention BOOLEAN NOT NULL DEFAULT FALSE,
    expect_security_block BOOLEAN NOT NULL DEFAULT FALSE,
    expected_tool TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS evaluation_results (
    id TEXT PRIMARY KEY,
    evaluation_run_id TEXT NOT NULL REFERENCES evaluation_runs(id) ON DELETE CASCADE,
    case_id TEXT NOT NULL REFERENCES evaluation_cases(id) ON DELETE CASCADE,
    passed BOOLEAN NOT NULL,
    recall_at_k DOUBLE PRECISION NOT NULL,
    precision_at_k DOUBLE PRECISION NOT NULL,
    mrr DOUBLE PRECISION NOT NULL,
    ndcg DOUBLE PRECISION NOT NULL,
    faithfulness DOUBLE PRECISION NOT NULL,
    citation_precision DOUBLE PRECISION NOT NULL,
    actual_output TEXT NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    details_json JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS model_usage (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id TEXT NOT NULL REFERENCES users(id),
    trace_id TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_name TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    prompt_tokens INTEGER NOT NULL,
    completion_tokens INTEGER NOT NULL,
    total_tokens INTEGER NOT NULL,
    estimated_cost_usd DOUBLE PRECISION NOT NULL,
    latency_ms DOUBLE PRECISION NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    actor_user_id TEXT,
    event_type TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    action TEXT NOT NULL,
    status TEXT NOT NULL,
    ip_address TEXT NOT NULL DEFAULT '127.0.0.1',
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS internal_tasks (
    id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    workspace_id TEXT NOT NULL REFERENCES workspaces(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    priority TEXT NOT NULL DEFAULT 'HIGH',
    assignee_email TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_by_agent_run_id TEXT REFERENCES agent_runs(id),
    idempotency_key TEXT UNIQUE NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes for Tenant Scoping, Full-Text Search, and pgvector HNSW
CREATE INDEX IF NOT EXISTS idx_documents_org_ws ON documents(organization_id, workspace_id);
CREATE INDEX IF NOT EXISTS idx_chunks_org_doc ON document_chunks(organization_id, document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_tsv ON document_chunks USING GIN (content_tsv);
CREATE INDEX IF NOT EXISTS idx_embeddings_hnsw ON document_embeddings USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_audit_org_created ON audit_logs(organization_id, created_at DESC);

-- PostgreSQL Row-Level Security (RLS) Policies for Defense-in-Depth Tenant Isolation
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_embeddings ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation_documents ON documents
    USING (organization_id = current_setting('app.current_org_id', true));
CREATE POLICY tenant_isolation_chunks ON document_chunks
    USING (organization_id = current_setting('app.current_org_id', true));
CREATE POLICY tenant_isolation_embeddings ON document_embeddings
    USING (organization_id = current_setting('app.current_org_id', true));
