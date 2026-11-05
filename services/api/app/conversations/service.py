import json
from typing import Any, Dict, Generator, List, Optional
from packages.retrieval.engine import HybridRAGEngine
from packages.llm_core.provider import get_llm_provider
from app.core.database import DatabaseManager, db as default_db, new_id, utc_now_iso
from app.core.security import SecurityViolationError, TenantRequestContext
from app.audit.service import AuditService
from app.observability.tracer import ObservabilityService

class ConversationService:
    '''
    Module D: Enterprise Chat & Conversation Engine
    Supports multi-conversation management, search, grounded RAG message generation,
    SSE streaming, citation persistence, and user feedback collection.
    '''
    def __init__(
        self,
        database: Optional[DatabaseManager] = None,
        observability: Optional[ObservabilityService] = None,
    ):
        self.db = database or default_db
        self.audit = AuditService(self.db)
        self.obs = observability or ObservabilityService(self.db)
        self.rag = HybridRAGEngine(self.db, self.obs)
        self.llm = get_llm_provider()

    def create_conversation(self, ctx: TenantRequestContext, workspace_id: str, title: str) -> Dict[str, Any]:
        ws = self.db.fetch_one(
            "SELECT id FROM workspaces WHERE id = ? AND organization_id = ?",
            (workspace_id, ctx.organization_id),
        )
        if not ws:
            raise SecurityViolationError("INVALID_WORKSPACE", "Workspace does not belong to organization", 403)
        conv_id = new_id("cnv")
        now = utc_now_iso()
        self.db.execute(
            '''
            INSERT INTO conversations (id, organization_id, workspace_id, user_id, title, is_archived, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 0, ?, ?)
            ''',
            (conv_id, ctx.organization_id, workspace_id, ctx.user_id, title.strip(), now, now),
        )
        return {
            "id": conv_id,
            "organization_id": ctx.organization_id,
            "workspace_id": workspace_id,
            "user_id": ctx.user_id,
            "title": title.strip(),
            "created_at": now,
        }

    def list_conversations(
        self, ctx: TenantRequestContext, workspace_id: Optional[str] = None, search_query: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM conversations WHERE organization_id = ? AND user_id = ?"
        params: List[Any] = [ctx.organization_id, ctx.user_id]
        if workspace_id:
            sql += " AND workspace_id = ?"
            params.append(workspace_id)
        if search_query:
            sql += " AND title LIKE ?"
            params.append(f"%{search_query.strip()}%")
        sql += " ORDER BY updated_at DESC"
        return self.db.fetch_all(sql, tuple(params))

    def get_conversation(self, ctx: TenantRequestContext, conversation_id: str) -> Dict[str, Any]:
        conv = self.db.fetch_one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))
        if not conv:
            raise ValueError(f"Conversation {conversation_id} not found.")
        if conv["organization_id"] != ctx.organization_id:
            raise SecurityViolationError("CROSS_TENANT_CONVERSATION", "Unauthorized conversation access", 403)
        messages = self.db.fetch_all(
            "SELECT * FROM messages WHERE conversation_id = ? AND organization_id = ? ORDER BY created_at ASC",
            (conversation_id, ctx.organization_id),
        )
        for m in messages:
            m["citations"] = self.db.fetch_all(
                "SELECT * FROM citations WHERE message_id = ? AND organization_id = ?",
                (m["id"], ctx.organization_id),
            )
        conv["messages"] = messages
        return conv

    def send_message(
        self, ctx: TenantRequestContext, conversation_id: str, content: str, top_k: int = 5
    ) -> Dict[str, Any]:
        conv = self.get_conversation(ctx, conversation_id)
        user_msg_id = new_id("msg")
        now = utc_now_iso()
        self.db.execute(
            '''
            INSERT INTO messages (
                id, conversation_id, organization_id, role, content, abstained,
                prompt_tokens, completion_tokens, latency_ms, trace_id, created_at
            ) VALUES (?, ?, ?, 'user', ?, 0, 0, 0, 0.0, ?, ?)
            ''',
            (user_msg_id, conversation_id, ctx.organization_id, content.strip(), ctx.trace_id, now),
        )

        rag_out = self.rag.retrieve_and_answer(
            ctx=ctx,
            query=content.strip(),
            workspace_id=conv["workspace_id"],
            top_k=top_k,
        )

        asst_msg_id = new_id("msg")
        asst_now = utc_now_iso()
        with self.db.connection() as conn:
            conn.execute(
                '''
                INSERT INTO messages (
                    id, conversation_id, organization_id, role, content, abstained,
                    abstention_reason, faithfulness_score, prompt_tokens, completion_tokens,
                    latency_ms, trace_id, created_at
                ) VALUES (?, ?, ?, 'assistant', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    asst_msg_id,
                    conversation_id,
                    ctx.organization_id,
                    rag_out["answer"],
                    1 if rag_out["abstained"] else 0,
                    rag_out["abstention_reason"],
                    rag_out["faithfulness_score"],
                    rag_out["usage"]["prompt_tokens"],
                    rag_out["usage"]["completion_tokens"],
                    rag_out["retrieval_trace"]["retrieval_latency_ms"] + rag_out["retrieval_trace"]["generation_latency_ms"],
                    ctx.trace_id,
                    asst_now,
                ),
            )
            persisted_citations = []
            for c in rag_out["citations"]:
                cit_id = new_id("cit")
                conn.execute(
                    '''
                    INSERT INTO citations (
                        id, message_id, organization_id, document_id, document_version_id,
                        chunk_id, citation_key, page_number, section_title, excerpt,
                        relevance_score, verified
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    ''',
                    (
                        cit_id,
                        asst_msg_id,
                        ctx.organization_id,
                        c["document_id"],
                        c["document_version_id"],
                        c["chunk_id"],
                        c["citation_key"],
                        c["page_number"],
                        c["section_title"],
                        c["excerpt"],
                        c["relevance_score"],
                    ),
                )
                persisted_citations.append({**c, "id": cit_id})
            conn.execute(
                "UPDATE conversations SET updated_at = ? WHERE id = ?",
                (asst_now, conversation_id),
            )

        return {
            "conversation_id": conversation_id,
            "user_message_id": user_msg_id,
            "assistant_message_id": asst_msg_id,
            "answer": rag_out["answer"],
            "abstained": rag_out["abstained"],
            "abstention_reason": rag_out["abstention_reason"],
            "faithfulness_score": rag_out["faithfulness_score"],
            "citations": persisted_citations,
            "retrieval_trace": rag_out["retrieval_trace"],
            "usage": rag_out["usage"],
            "follow_up_suggestions": self._generate_follow_ups(content, rag_out["citations"]),
        }

    def stream_message(
        self, ctx: TenantRequestContext, conversation_id: str, content: str, top_k: int = 5
    ) -> Generator[str, None, None]:
        result = self.send_message(ctx, conversation_id, content, top_k=top_k)
        yield f"event: trace\ndata: {json.dumps(result['retrieval_trace'])}\n\n"
        yield f"event: citations\ndata: {json.dumps(result['citations'])}\n\n"
        words = result["answer"].split(" ")
        for i in range(0, len(words), 6):
            chunk = " ".join(words[i : i + 6]) + (" " if i + 6 < len(words) else "")
            yield f"event: token\ndata: {json.dumps({'delta': chunk})}\n\n"
        yield f"event: done\ndata: {json.dumps({'message_id': result['assistant_message_id'], 'usage': result['usage']})}\n\n"

    def record_feedback(
        self, ctx: TenantRequestContext, message_id: str, rating: int, comment: str = ""
    ) -> Dict[str, Any]:
        msg = self.db.fetch_one("SELECT * FROM messages WHERE id = ?", (message_id,))
        if not msg or msg["organization_id"] != ctx.organization_id:
            raise SecurityViolationError("MESSAGE_ACCESS_DENIED", "Message not found in organization", 403)
        self.db.execute(
            "UPDATE messages SET feedback_rating = ?, feedback_comment = ? WHERE id = ?",
            (int(rating), comment.strip(), message_id),
        )
        return {"message_id": message_id, "rating": int(rating), "comment": comment.strip()}

    def delete_conversation(self, ctx: TenantRequestContext, conversation_id: str) -> Dict[str, Any]:
        self.get_conversation(ctx, conversation_id)
        self.db.execute(
            "DELETE FROM conversations WHERE id = ? AND organization_id = ?",
            (conversation_id, ctx.organization_id),
        )
        return {"deleted": True, "conversation_id": conversation_id}

    def _generate_follow_ups(self, query: str, citations: List[Dict[str, Any]]) -> List[str]:
        if not citations:
            return ["Which documents are currently indexed in this workspace?"]
        doc_titles = list({c.get("document_title", "policy") for c in citations})
        return [
            f"What are the operational compliance requirements in {doc_titles[0]}?",
            f"Compare {doc_titles[0]} against its previous version and highlight key changes.",
            "Are there any exceptions or escalation SLAs specified in the cited sections?",
        ]
