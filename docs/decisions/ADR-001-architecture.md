# ADR-001: Modular Monolith with Dedicated Async Worker

- **Status:** Accepted
- **Date:** 2026-11-05

## Context
Enterprise AI platforms must handle interactive low-latency API requests (authentication, RBAC, hybrid search, SSE chat streaming) alongside CPU- and IO-intensive workloads (PDF/DOCX/XLSX parsing, chunking, batch embedding generation, and full benchmark suite execution). Prematurely splitting the domain into 8+ microservices introduces distributed transaction complexity, schema synchronization drift, and network serialization overhead.

## Options Considered
1. **Distributed Microservices** (separate Auth, Document, RAG, Agent, Analytics, and Evaluation services).
2. **Single-Process Monolith** (running ingestion and evaluation synchronously in API request threads).
3. **Modular Monolith (`services/api`) + Dedicated Background Worker (`services/worker`) + Shared Domain Packages (`packages/*`)**.

## Decision
Adopt Option 3: A strictly layered **Modular Monolith** with a separate background worker process and shared domain packages.

## Technical Justification
- Enforces clean module boundaries via Python packages (`llm_core`, `retrieval`, `orchestration`, `evaluation`, `shared_contracts`).
- Eliminates network hops between RBAC verification, hybrid retrieval, and agent orchestration.
- Allows `services/worker` to scale independently for heavy document ingestion and evaluation runs using idempotent job queues (`ingestion_jobs`).

## Trade-offs & Consequences
- Requires discipline to prevent cross-module private table coupling (enforced via module service interfaces and code review gates).
- Any module can be extracted into a standalone service later by wrapping its package interface in an RPC/HTTP adapter.
