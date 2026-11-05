# NEXUS AI — Enterprise Security Architecture

## Defense-in-Depth Model (OWASP GenAI LLM Top 10 2026)
1. **Authentication & Session Security**:
   - Passwords hashed using `PBKDF2-HMAC-SHA256` (260,000 iterations, cryptographic 16-byte salt, constant-time `hmac.compare_digest` verification).
   - Short-lived signed `HMAC-SHA256` JWT access tokens paired with rotating refresh tokens stored as SHA-256 hashes.
2. **Backend-Enforced Multi-Tenant & Role Authorization**:
   - Every request resolves `RequestContext(user_id, organization_id, role)` from the verified JWT and database membership table `organization_members`.
   - Client-supplied `organization_id` headers/params are validated against membership before any query executes.
   - Document classification (`PUBLIC`, `INTERNAL`, `CONFIDENTIAL`, `RESTRICTED`) is mapped to minimum required roles (`MEMBER`, `MANAGER`, `ADMIN`, `OWNER`).
3. **Direct & Indirect Prompt Injection Defense**:
   - User queries are scanned for override patterns (`ignore previous instructions`, `reveal system prompt`, `execute shell`, etc.).
   - Uploaded documents are scanned during ingestion (`PromptInjectionGuard.scan_document_chunk`). Chunks containing adversarial instruction patterns are flagged (`is_quarantined_injection = True`), logged to `audit_logs`, and neutralized so embedded text in a document can never trigger tool calls or override system prompts.
4. **Consequential Action Human-in-the-Loop (HITL) Gate**:
   - Write operations (`create_internal_task`) automatically pause the LangGraph workflow at `HumanApprovalNode`, persist the state checkpoint, and require explicit approval from an authorized `MANAGER`, `ADMIN`, or `OWNER`.
