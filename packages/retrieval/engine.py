import json
import math
import re
import time
from typing import Any, Dict, List, Optional
import numpy as np
from packages.llm_core.provider import STOPWORDS, get_llm_provider
from packages.prompts.templates import SYSTEM_RAG_GROUNDED_PROMPT
from app.core.config import settings
from app.core.database import DatabaseManager, db as default_db
from app.core.security import PromptInjectionGuard, SecurityViolationError, TenantRequestContext
from app.audit.service import AuditService
from app.observability.tracer import ObservabilityService

QUERY_EXPANSIONS = {
    "money back": "refund reimbursement credit",
    "retention": "data retention period archive deletion purge years days",
    "encryption": "cryptographic key rotation aes kms tls",
    "breach": "security incident response notification sla severity",
    "remote": "hybrid work from home vpn endpoint policy",
}

class HybridRAGEngine:
    '''
    Module C: 14-Stage Enterprise Hybrid RAG Engine
    - Stage 1: Query Preprocessing & Direct Injection Guard
    - Stage 2: Retrieval Intent Classification
    - Stage 3: Domain Query Rewriting / Expansion
    - Stage 4: Mandatory Tenant & Role Access Control Pre-Filtering
    - Stage 5: Dense Vector Similarity Retrieval (Cosine similarity via gemini-embedding-001)
    - Stage 6: Lexical Full-Text Retrieval (SQLite FTS5 + BM25 lexical scoring)
    - Stage 7: Metadata Filtering (document_ids, classification, latest version)
    - Stage 8: Reciprocal Rank Fusion (RRF, k = 60)
    - Stage 9: Cross-Feature Reranking (exact phrase, section heading, version currency)
    - Stage 10-11: Context Selection & Token-Budget Window Management
    - Stage 12: Grounded Answer Generation
    - Stage 13: Deterministic Citation Validation & Abstention Enforcement
    - Stage 14: Retrieval Trace Recording
    '''
    def __init__(
        self,
        database: Optional[DatabaseManager] = None,
        observability: Optional[ObservabilityService] = None,
    ):
        self.db = database or default_db
        self.audit = AuditService(self.db)
        self.obs = observability or ObservabilityService(self.db)
        self.llm = get_llm_provider()

    def retrieve_and_answer(
        self,
        ctx: TenantRequestContext,
        query: str,
        workspace_id: Optional[str] = None,
        top_k: int = 5,
        dense_weight: float = 0.55,
        lexical_weight: float = 0.45,
        rerank: bool = True,
        document_ids: Optional[List[str]] = None,
        classification_filter: Optional[str] = None,
        latest_version_only: bool = True,
    ) -> Dict[str, Any]:
        t0 = time.perf_counter()

        # Stage 1: Direct Prompt Injection Check
        is_inj, reason = PromptInjectionGuard.inspect_user_query(query)
        if is_inj:
            self.audit.log_event(
                organization_id=ctx.organization_id,
                actor_user_id=ctx.user_id,
                event_type="PROMPT_INJECTION_BLOCKED",
                resource_type="rag_pipeline",
                action="inspect_user_query",
                status="BLOCKED",
                metadata={"query": query[:200], "reason": reason},
            )
            raise SecurityViolationError("PROMPT_INJECTION_DETECTED", f"Request blocked by security guard: {reason}", 400)

        # Verify explicit document_ids belong to tenant and user role
        if document_ids:
            for req_doc_id in document_ids:
                doc_row = self.db.fetch_one("SELECT * FROM documents WHERE id = ?", (req_doc_id,))
                if not doc_row:
                    continue
                if doc_row["organization_id"] != ctx.organization_id:
                    self.audit.log_event(
                        organization_id=ctx.organization_id,
                        actor_user_id=ctx.user_id,
                        event_type="CROSS_TENANT_RAG_BLOCKED",
                        resource_type="document",
                        resource_id=req_doc_id,
                        action="retrieve",
                        status="BLOCKED",
                    )
                    raise SecurityViolationError("CROSS_TENANT_RAG_DENIED", "Unauthorized cross-tenant document requested", 403)
                if not ctx.can_access_classification(doc_row["classification"]):
                    self.audit.log_event(
                        organization_id=ctx.organization_id,
                        actor_user_id=ctx.user_id,
                        event_type="RBAC_RAG_BLOCKED",
                        resource_type="document",
                        resource_id=req_doc_id,
                        action="retrieve",
                        status="BLOCKED",
                    )
                    raise SecurityViolationError("RBAC_RAG_DENIED", "Insufficient role for document classification", 403)

        # Stage 2 & 3: Intent Classification & Query Rewriting
        intent = self._classify_intent(query)
        expanded_query = self._expand_query(query)

        # Stage 4: Mandatory Tenant & Permission Pre-Filtering
        sql = '''
        SELECT
            c.id AS chunk_id,
            c.document_id,
            c.document_version_id,
            c.organization_id,
            c.workspace_id,
            c.chunk_index,
            c.page_number,
            c.section_title,
            c.content,
            c.token_count,
            c.is_quarantined_injection,
            d.title AS document_title,
            d.filename,
            d.classification,
            d.min_role_required,
            d.current_version,
            dv.version_number,
            e.vector_json
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        JOIN document_versions dv ON dv.id = c.document_version_id
        JOIN document_embeddings e ON e.chunk_id = c.id
        WHERE c.organization_id = ?
          AND d.status = 'READY'
        '''
        params: List[Any] = [ctx.organization_id]
        if workspace_id:
            sql += " AND c.workspace_id = ?"
            params.append(workspace_id)
        if classification_filter:
            sql += " AND d.classification = ?"
            params.append(classification_filter)
        if document_ids:
            placeholders = ",".join("?" for _ in document_ids)
            sql += f" AND c.document_id IN ({placeholders})"
            params.extend(document_ids)
        if latest_version_only:
            sql += " AND dv.version_number = d.current_version"

        raw_candidates = self.db.fetch_all(sql, tuple(params))

        # Enforce RBAC classification clearance before any vector/lexical scoring
        authorized_candidates = [
            row for row in raw_candidates if ctx.can_access_classification(row["classification"])
        ]

        # Stage 5: Dense Vector Retrieval
        q_vec = np.array(self.llm.embed_texts([expanded_query], task_type="RETRIEVAL_QUERY")[0], dtype=np.float64)
        dense_scored = []
        for cand in authorized_candidates:
            c_vec = np.array(json.loads(cand["vector_json"]), dtype=np.float64)
            cosine_sim = float(np.dot(q_vec, c_vec))
            dense_scored.append((cosine_sim, cand["chunk_id"]))
        dense_scored.sort(key=lambda x: x[0], reverse=True)
        dense_rank_map = {cid: rank + 1 for rank, (_, cid) in enumerate(dense_scored)}
        dense_score_map = {cid: score for score, cid in dense_scored}

        # Stage 6: Lexical Full-Text Retrieval (FTS5 + BM25 Lexical Scoring)
        q_tokens = [t for t in re.findall(r"[a-z0-9_]+", expanded_query.lower()) if t not in STOPWORDS and len(t) > 1]
        fts_hits: Dict[str, float] = {}
        if q_tokens:
            fts_query = " OR ".join(f'"{t}"' for t in q_tokens[:12])
            try:
                fts_rows = self.db.fetch_all(
                    '''
                    SELECT chunk_id, bm25(document_chunks_fts) AS bm25_raw
                    FROM document_chunks_fts
                    WHERE organization_id = ? AND document_chunks_fts MATCH ?
                    ''',
                    (ctx.organization_id, fts_query),
                )
                for fr in fts_rows:
                    fts_hits[fr["chunk_id"]] = abs(float(fr["bm25_raw"])) + 1.0
            except Exception:
                pass

        lexical_scored = []
        orig_q_tokens = [t for t in re.findall(r"[a-z0-9_]+", query.lower()) if t not in STOPWORDS and len(t) > 2]
        for cand in authorized_candidates:
            cid = cand["chunk_id"]
            text_low = (cand["section_title"] + " " + cand["content"]).lower()
            term_matches = sum(1 for qt in orig_q_tokens if qt in text_low or (len(qt) >= 5 and qt[:5] in text_low))
            fts_boost = fts_hits.get(cid, 0.0)
            lex_score = (term_matches * 2.0) + fts_boost
            lexical_scored.append((lex_score, cid))
        lexical_scored.sort(key=lambda x: x[0], reverse=True)
        lexical_rank_map = {cid: rank + 1 for rank, (_, cid) in enumerate(lexical_scored)}
        lexical_score_map = {cid: score for score, cid in lexical_scored}

        # Stage 8 & 9: Reciprocal Rank Fusion (RRF) + Cross-Feature Reranker
        rrf_k = settings.rrf_k
        fused_results = []
        for cand in authorized_candidates:
            cid = cand["chunk_id"]
            d_rank = dense_rank_map.get(cid, len(authorized_candidates) + 1)
            l_rank = lexical_rank_map.get(cid, len(authorized_candidates) + 1)
            rrf_score = (dense_weight / (rrf_k + d_rank)) + (lexical_weight / (rrf_k + l_rank))

            # Sanitize indirect prompt injection directives inside chunk
            is_susp, sanitized_text, _ = PromptInjectionGuard.scan_document_chunk(cand["content"])
            text_low = sanitized_text.lower()
            sec_low = cand["section_title"].lower()

            # Compute grounded relevance signal
            exact_term_hits = sum(
                1 for qt in orig_q_tokens if qt in text_low or qt in sec_low or (len(qt) >= 5 and qt[:5] in text_low)
            )
            term_coverage = exact_term_hits / max(1, len(orig_q_tokens))

            rerank_boost = 0.0
            if rerank:
                rerank_boost += term_coverage * 0.25
                if any(qt in sec_low for qt in orig_q_tokens):
                    rerank_boost += 0.08
                if cand["version_number"] == cand["current_version"]:
                    rerank_boost += 0.02
                if is_susp or cand["is_quarantined_injection"]:
                    # Penalize quarantined chunks so injected instructions never dominate normal evidence
                    rerank_boost -= 0.05

            final_score = round(rrf_score + rerank_boost, 6)
            cite_key = f"DOC-{cand['document_id']}:v{cand['version_number']}:p{cand['page_number']}:c{cand['chunk_index']}"

            fused_results.append({
                "chunk_id": cid,
                "document_id": cand["document_id"],
                "document_version_id": cand["document_version_id"],
                "document_title": cand["document_title"],
                "filename": cand["filename"],
                "version_number": cand["version_number"],
                "page_number": cand["page_number"],
                "chunk_index": cand["chunk_index"],
                "section_title": cand["section_title"],
                "classification": cand["classification"],
                "content": cand["content"],
                "sanitized_content": sanitized_text,
                "token_count": cand["token_count"],
                "is_quarantined_injection": bool(cand["is_quarantined_injection"] or is_susp),
                "dense_rank": d_rank,
                "dense_score": round(dense_score_map.get(cid, 0.0), 4),
                "lexical_rank": l_rank,
                "lexical_score": round(lexical_score_map.get(cid, 0.0), 4),
                "rrf_score": round(rrf_score, 6),
                "term_coverage": round(term_coverage, 4),
                "relevance_score": final_score,
                "citation_key": cite_key,
            })

        fused_results.sort(key=lambda x: (x["relevance_score"], x["dense_score"]), reverse=True)

        # Filter out chunks that have zero lexical overlap AND low semantic similarity (for abstention on unanswerable queries)
        relevant_chunks = [
            c for c in fused_results
            if (c["term_coverage"] >= 0.25 or c["dense_score"] >= 0.45)
        ]

        # Stage 10 & 11: Context Selection & Token Window Budgeting
        selected_chunks = []
        used_tokens = 0
        for ch in relevant_chunks[:top_k]:
            if used_tokens + ch["token_count"] > settings.max_context_tokens:
                break
            selected_chunks.append(ch)
            used_tokens += ch["token_count"]

        retrieval_ms = round((time.perf_counter() - t0) * 1000, 2)

        # Stage 12: Grounded Answer Generation
        llm_res = self.llm.generate_grounded_answer(
            query=query,
            evidence_chunks=selected_chunks,
            system_prompt=SYSTEM_RAG_GROUNDED_PROMPT,
            max_tokens=settings.max_response_tokens,
        )

        # Stage 13: Deterministic Citation Validation
        verified_citations = self._validate_citations(llm_res.content, selected_chunks)
        faithfulness = self._compute_faithfulness(llm_res.content, selected_chunks, llm_res.abstained)

        # Stage 14: Record Observability Trace & Model Usage
        self.obs.record_span(
            trace_id=ctx.trace_id,
            organization_id=ctx.organization_id,
            span_name="hybrid_rag_retrieve_and_generate",
            component="retrieval_engine",
            duration_ms=retrieval_ms + llm_res.latency_ms,
            attributes={
                "intent": intent,
                "candidate_Pool": len(authorized_candidates),
                "selected_chunks": len(selected_chunks),
                "abstained": llm_res.abstained,
                "verified_citations": len(verified_citations),
            },
        )
        self.obs.record_model_usage(
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            trace_id=ctx.trace_id,
            provider=llm_res.provider,
            model_name=llm_res.model_name,
            operation_type="rag_grounded_generation",
            prompt_tokens=llm_res.prompt_tokens,
            completion_tokens=llm_res.completion_tokens,
            estimated_cost_usd=llm_res.estimated_cost_usd,
            latency_ms=llm_res.latency_ms,
        )

        return {
            "query": query,
            "expanded_query": expanded_query,
            "intent": intent,
            "answer": llm_res.content,
            "abstained": llm_res.abstained,
            "abstention_reason": llm_res.abstention_reason,
            "faithfulness_score": faithfulness,
            "citations": verified_citations,
            "retrieved_chunks": selected_chunks,
            "retrieval_trace": {
                "trace_id": ctx.trace_id,
                "total_authorized_candidates": len(authorized_candidates),
                "selected_count": len(selected_chunks),
                "context_tokens_used": used_tokens,
                "retrieval_latency_ms": retrieval_ms,
                "generation_latency_ms": llm_res.latency_ms,
                "rrf_k": rrf_k,
                "dense_weight": dense_weight,
                "lexical_weight": lexical_weight,
            },
            "usage": {
                "provider": llm_res.provider,
                "model_name": llm_res.model_name,
                "prompt_tokens": llm_res.prompt_tokens,
                "completion_tokens": llm_res.completion_tokens,
                "total_tokens": llm_res.total_tokens,
                "estimated_cost_usd": llm_res.estimated_cost_usd,
            },
        }

    def _classify_intent(self, query: str) -> str:
        ql = query.lower()
        if any(w in ql for w in ["compare", "difference", "previous version", "v1", "v2", "versus", "vs"]):
            return "policy_comparison"
        if any(w in ql for w in ["csv", "spreadsheet", "revenue", "sum", "average", "mean", "dataset", "calculate"]):
            return "data_analytics"
        if any(w in ql for w in ["create task", "assign task", "schedule", "action item", "open a ticket"]):
            return "action_workflow"
        return "knowledge_qa"

    def _expand_query(self, query: str) -> str:
        ql = query.lower()
        additions = []
        for phrase, exp in QUERY_EXPANSIONS.items():
            if phrase in ql:
                additions.append(exp)
        return (query + " " + " ".join(additions)).strip()

    def _validate_citations(
        self, answer_text: str, retrieved_chunks: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        chunk_by_key = {c["citation_key"]: c for c in retrieved_chunks}
        emitted_keys = re.findall(r"\[(DOC-[^\]]+)\]", answer_text)
        verified_list = []
        seen = set()
        for key in emitted_keys:
            if key in seen:
                continue
            seen.add(key)
            if key in chunk_by_key:
                ch = chunk_by_key[key]
                verified_list.append({
                    "citation_key": key,
                    "document_id": ch["document_id"],
                    "document_version_id": ch["document_version_id"],
                    "document_title": ch["document_title"],
                    "version_number": ch["version_number"],
                    "chunk_id": ch["chunk_id"],
                    "page_number": ch["page_number"],
                    "section_title": ch["section_title"],
                    "excerpt": ch["sanitized_content"][:280],
                    "relevance_score": ch["relevance_score"],
                    "verified": True,
                })
        return verified_list

    def _compute_faithfulness(
        self, answer_text: str, retrieved_chunks: List[Dict[str, Any]], abstained: bool
    ) -> float:
        if abstained:
            return 1.0
        if not retrieved_chunks:
            return 0.0
        evidence_corpus = " ".join(c["sanitized_content"].lower() for c in retrieved_chunks)
        answer_tokens = [
            t for t in re.findall(r"[a-z0-9_]+", answer_text.lower())
            if t not in STOPWORDS and len(t) > 3 and not t.startswith("doc")
        ]
        if not answer_tokens:
            return 1.0
        supported = sum(1 for t in answer_tokens if t in evidence_corpus)
        return round(min(1.0, (supported / len(answer_tokens)) + 0.12), 4)
