# NEXUS AI — System Architecture & Mermaid Diagrams

## 1. System Context Diagram
```mermaid
flowchart TB
    User["Enterprise User (Owner / Admin / Manager / Member)"]
    Web["NEXUS AI Web App (Next.js / TypeScript / Canvas UI)"]
    API["NEXUS AI Backend API (FastAPI Modular Monolith)"]
    Worker["Async Ingestion & Eval Worker"]
    DB[("PostgreSQL + pgvector + FTS / Local SQLite FTS5+Vector")]
    Cache[("Redis Cache & Rate Limiter")]
    Gemini["Google Gemini API (gemini-3.8-flash / gemini-embedding-001)"]
    OpenAI["OpenAI API (Optional Fallback Provider)"]
    OTel["Observability & Audit Telemetry (OpenTelemetry / JSON Traces)"]

    User -->|HTTPS / REST & SSE| Web
    Web -->|JWT Auth + Org Scope| API
    API -->|Read/Write + RLS| DB
    API -->|Rate Limits & Job Queue| Cache
    Worker -->|Poll & Process Jobs| DB
    API -->|LLM & Embeddings| Gemini
    Worker -->|Batch Embeddings| Gemini
    API -.->|Optional Provider| OpenAI
    API -->|Structured Spans & Metrics| OTel
    Worker -->|Ingestion Spans| OTel
```

## 2. High-Level Modular Monolith Architecture
```mermaid
flowchart LR
    subgraph Frontend["apps/web (Enterprise UI)"]
        UI_Dash["Dashboard & Knowledge Library"]
        UI_Chat["AI Workspace & Citation Viewer"]
        UI_Agent["Agent Workflow & HITL Monitor"]
        UI_Analytics["Analytics & Report Center"]
        UI_Obs["Eval & Observability Dashboards"]
    end

    subgraph Backend["services/api (FastAPI v1)"]
        AuthMod["Module A: Identity, Auth & RBAC"]
        DocMod["Module B: Document Intelligence"]
        RAGMod["Module C: Advanced Hybrid RAG"]
        ChatMod["Module D: Chat & SSE Streaming"]
        AgentMod["Module E: LangGraph Supervisor"]
        ToolMod["Module F: Controlled Tool Registry"]
        DataMod["Module G: Deterministic Analytics"]
        RepMod["Module H: Doc Comparison & Reports"]
        EvalMod["Module I: Evaluation Engine"]
        ObsMod["Module J: LLM Observability"]
        SecMod["Module K: OWASP 2026 Guardrails"]
    end

    subgraph Shared["packages/*"]
        LLMCore["llm_core (Provider Contract)"]
        RetPkg["retrieval (RRF + Reranker)"]
        OrchPkg["orchestration (StateGraph + Checkpointer)"]
        EvalPkg["evaluation (Deterministic Metrics)"]
    end

    Frontend --> Backend
    Backend --> Shared
```

## 3. Request Lifecycle
```mermaid
sequenceDiagram
    autonumber
    actor U as Authorized User
    participant W as Web Client
    participant G as Security & RBAC Middleware
    participant A as FastAPI Router
    participant O as LangGraph Supervisor
    participant R as Hybrid RAG / Tool Engine
    participant L as LLM Provider (Gemini)
    participant D as Database & Audit Log

    U->>W: Submit Query / Workflow Request
    W->>G: POST /api/v1/conversations/{id}/messages (Bearer JWT)
    G->>G: Verify JWT, Tenant Membership, Rate Limit & Prompt Injection Guard
    G->>A: Authorized RequestContext(user_id, org_id, role, trace_id)
    A->>O: Invoke Stateful Workflow Graph
    O->>R: Execute Tenant-Scoped Retrieval / Tool Call
    R->>D: Query Chunks WHERE organization_id = :org_id
    D-->>R: Ranked Chunks + Metadata
    R-->>O: Verified Evidence Context
    O->>L: Generate Grounded Response with Citations
    L-->>O: Structured Output + Token Usage
    O->>O: Validate Citations & Abstention Rules
    O->>D: Persist Message, Citations, ModelUsage & AuditEvent
    O-->>W: Stream SSE Events (trace, citations, tokens, done)
```

## 4. Asynchronous Document Ingestion Pipeline
```mermaid
flowchart LR
    Upload["1. Secure File Upload (PDF/DOCX/XLSX/CSV/MD/TXT)"] --> Validate["2. MIME, Size & SHA-256 Deduplication"]
    Validate --> Version["3. Document & Version Record Created (PENDING)"]
    Version --> Queue["4. Ingestion Job Enqueued (Idempotency Key)"]
    Queue --> Parse["5. Structural Parser (Pages, Headings, Tables)"]
    Parse --> Sanitize["6. Indirect Prompt Injection & Malicious Pattern Scan"]
    Sanitize --> Chunk["7. Semantic & Structural Chunker (Overlap + Page Anchors)"]
    Chunk --> Embed["8. Embedding Generation (gemini-embedding-001)"]
    Embed --> Index["9. Transactional Vector + FTS Indexing"]
    Index --> Ready["10. Status = READY + Audit Log"]
```

## 5. Advanced Hybrid RAG Retrieval Pipeline
```mermaid
flowchart TB
    Q["User Query + Tenant Context"] --> Pre["1. Query Preprocessing & Injection Check"]
    Pre --> Intent["2. Intent & Retrieval Classification"]
    Intent --> Rewrite["3. Domain Query Expansion"]
    Rewrite --> Dense["4a. Dense Vector Search (Cosine Similarity)"]
    Rewrite --> Lexical["4b. Lexical Full-Text Search (BM25 / FTS)"]
    Dense --> Filter["5. Mandatory Tenant & RBAC Metadata Pre-Filter"]
    Lexical --> Filter
    Filter --> RRF["6. Reciprocal Rank Fusion (k = 60)"]
    RRF --> Rerank["7. Cross-Feature Reranker (Phrase, Heading, Version)"]
    Rerank --> Budget["8. Context Window Token Budget Manager"]
    Budget --> Gen["9. Grounded LLM Answer Generation"]
    Gen --> CiteVal["10. Deterministic Citation & Abstention Validator"]
```

## 6. Supervisor-Controlled Multi-Agent Orchestration (LangGraph Pattern)
```mermaid
stateDiagram-v2
    [*] --> ClassifyRequest
    ClassifyRequest --> PlanTasks
    PlanTasks --> KnowledgeRetrieval: intent == knowledge_qa
    PlanTasks --> DocumentComparison: intent == compare_docs
    PlanTasks --> DataAnalytics: intent == analyze_data
    PlanTasks --> ToolExecution: intent == action_workflow

    KnowledgeRetrieval --> VerifyEvidence
    DocumentComparison --> VerifyEvidence
    DataAnalytics --> VerifyEvidence

    ToolExecution --> HumanApproval: requires_approval == true
    ToolExecution --> VerifyEvidence: requires_approval == false

    HumanApproval -->PausedCheckpoint: Persist State & Await Manager/Admin
    PausedCheckpoint --> ExecuteApprovedTool: Status == APPROVED
    PausedCheckpoint --> WorkflowAborted: Status == REJECTED
    ExecuteApprovedTool --> VerifyEvidence

    VerifyEvidence --> GenerateResponse
    GenerateResponse --> CompleteWorkflow
    WorkflowAborted --> CompleteWorkflow
    CompleteWorkflow --> [*]
```

## 7. Authentication, Session & RBAC Authorization Flow
```mermaid
sequenceDiagram
    actor User
    participant API as Auth Service
    participant DB as Database (Users / OrgMembers)
    participant Resource as Protected Endpoint

    User->>API: POST /api/v1/auth/login (email, password)
    API->>DB: Fetch User + Verify PBKDF2/Argon2 Password Hash
    API->>DB: Issue Access Token (JWT) + Rotating Refresh Token
    API-->>User: Access Token + Refresh Token + Org Memberships
    User->>Resource: Request with Authorization: Bearer <JWT> + X-Organization-Id
    Resource->>DB: Verify User Membership & Role (Owner/Admin/Manager/Member) in Org
    alt Authorized
        Resource-->>User: 200 OK (Tenant-Scoped Payload)
    else Unauthorized / Cross-Tenant Attempt
        Resource->>DB: Write SECURITY_VIOLATION Audit Log
        Resource-->>User: 403 Forbidden (Sanitized Error)
    end
```

## 8. Multi-Tenant Isolation Architecture
```mermaid
flowchart TB
    Req["Incoming API Request"] --> Auth["JWT Signature & Expiration Verification"]
    Auth --> MemberCheck["Verify User Membership in Requested organization_id"]
    MemberCheck -->|Denied| AuditBlock["Log Cross-Tenant Attempt & Return 403"]
    MemberCheck -->|Verified| AppScope["Inject Immutable TenantContext(org_id, workspace_id, role)"]
    AppScope --> SQLFilter["Mandatory WHERE organization_id = :org_id on All Queries"]
    SQLFilter --> PG_RLS["PostgreSQL Row-Level Security Policy (current_setting('app.current_org_id'))"]
    PG_RLS --> VecScope["Vector & FTS Pre-Filtering by organization_id Before RRF"]
```

## 9. Evaluation & Benchmarking Pipeline
```mermaid
flowchart LR
    Dataset["Golden Benchmark Dataset (12 Categories)"] --> Runner["Deterministic Benchmark Runner"]
    Runner --> RAG_Pipeline["Execute Live RAG & Agent Workflows"]
    RAG_Pipeline --> RetMetrics["Retrieval Metrics (Recall@K, Precision@K, MRR, nDCG)"]
    RAG_Pipeline --> GenMetrics["Answer Metrics (Faithfulness, Citation Precision, Abstention)"]
    RAG_Pipeline --> AgentMetrics["Agent & Security Metrics (Routing, Tool Schema, Injection Block)"]
    RetMetrics --> Report["Reproducible JSON & Markdown Report"]
    GenMetrics --> Report
    AgentMetrics --> Report
```

## 10. Container & Cloud Deployment Topology
```mermaid
flowchart TB
    subgraph Cloud["Production / Docker Compose Environment"]
        Ingress["Reverse Proxy / TLS Termination"]
        WebContainer["nexus-web (Next.js App :3000)"]
        APIContainer["nexus-api (FastAPI / Uvicorn :8000)"]
        WorkerContainer["nexus-worker (Async Ingestion & Eval Worker)"]
        PGContainer[("PostgreSQL 16 + pgvector :5432")]
        RedisContainer[("Redis 7 :6379")]
    end

    Ingress --> WebContainer
    Ingress --> APIContainer
    WebContainer --> APIContainer
    APIContainer --> PGContainer
    APIContainer --> RedisContainer
    WorkerContainer --> PGContainer
    WorkerContainer --> RedisContainer
```
