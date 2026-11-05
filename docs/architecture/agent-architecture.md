# NEXUS AI — Multi-Agent Orchestration & Controlled Tool System

## Supervisor State Machine (LangGraph Architecture)
NEXUS AI uses a deterministic **Supervisor StateGraph** (`packages/orchestration/workflow.py`) rather than unconstrained autonomous loops.

### Workflow State Schema (`AgentWorkflowState`)
- `run_id`: Unique execution identifier
- `organization_id`, `workspace_id`, `user_id`, `user_role`: Immutable tenant & RBAC context
- `query`: Original user request
- `intent`: Classified workflow path (`knowledge_qa`, `compare_docs`, `analyze_data`, `action_workflow`)
- `plan`: Ordered list of planned steps
- `retrieved_chunks`: Verified evidence chunks from Hybrid RAG
- `comparison_result`: Structured diff output from Document Comparison Engine
- `analytics_result`: Deterministic Pandas computation output
- `pending_tool_calls` & `executed_tool_calls`: Tool invocation records
- `approval_request_id` & `approval_status`: Human-in-the-Loop checkpoint state
- `evidence_verified`: Boolean grounding check result
- `final_response` & `citations`: Grounded output
- `step_count`, `max_steps` (default `12`), `status`, `error`

### Controlled Tool Registry (Module F)
All 8 enterprise tools enforce strict JSON input validation, role permissions, timeouts, and audit logging:
1. `search_knowledge_base`: Hybrid RRF retrieval across tenant documents (`MEMBER+`).
2. `get_document_metadata`: Retrieves version history, SHA-256 hashes, and section structure (`MEMBER+`).
3. `compare_documents`: Runs clause-by-clause diff between two document versions (`MEMBER+`).
4. `extract_document_data`: Extracts structured key-value fields from a document with page citations (`MEMBER+`).
5. `calculate_metrics`: Evaluates allowlisted deterministic financial/operational formulas (`MEMBER+`).
6. `analyse_csv`: Runs deterministic Pandas aggregations, filtering, and descriptive statistics on an ingested dataset (`MEMBER+`).
7. `generate_report`: Compiles an evidence-backed Markdown/PDF compliance or executive report (`MANAGER+`).
8. `create_internal_task`: Creates an audited compliance or operational follow-up task (`MANAGER+`, **requires Human Approval checkpoint**).
