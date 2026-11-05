# NEXUS AI — Deployment & Production Engineering Architecture

## Local & Containerized Topology
- **`docker-compose.yml`**: Orchestrates `nexus-web` (Next.js frontend), `nexus-api` (FastAPI backend), `nexus-worker` (background ingestion & evaluation worker), `postgres` (`pgvector/pgvector:pg16`), and `redis` (`redis:7-alpine`) with container health checks and resource limits.
- **Zero-Cloud Local Execution**: When running in constrained or air-gapped local environments without Docker daemons, `NEXUS_DB_URL` seamlessly supports local SQLite 3.40+ with `FTS5` and in-process worker execution while maintaining identical API contracts and schema semantics.
- **Cloud Production Target**: AWS ECS Fargate / Google Cloud Run for stateless `nexus-api` and `nexus-worker` containers, Amazon RDS for PostgreSQL (with `pgvector` and RLS enabled), Amazon ElastiCache for Redis, and S3 / Cloud Storage with server-side KMS encryption for raw document blobs.
