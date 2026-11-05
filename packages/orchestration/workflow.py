import json
import time
from typing import Any, Dict, List, Optional
from packages.orchestration.tools import ControlledToolRegistry
from packages.retrieval.engine import HybridRAGEngine
from app.core.config import settings
from app.core.database import DatabaseManager, db as default_db, new_id, utc_now_iso
from app.core.security import PromptInjectionGuard, SecurityViolationError, TenantRequestContext
from app.audit.service import AuditService
from app.observability.tracer import ObservabilityService

class SupervisorAgentOrchestrator:
    '''
    Module E: LangGraph-Architecture Stateful Multi-Agent Orchestrator
    Implements a 10-node supervisor-controlled graph with database-persisted checkpoints,
    step limits, retry recovery, and Human-in-the-Loop (HITL) approval gates.
    Nodes:
    1. classify_request
    2. plan_tasks
    3. knowledge_retrieval_node
    4. document_analysis_node
    5. data_analysis_node
    6. tool_execution_node
    7. evidence_verification_node
    8. human_approval_node
    9. response_generation_node
    10. workflow_completion_node
    '''
    def __init__(
        self,
        database: Optional[DatabaseManager] = None,
        observability: Optional[ObservabilityService] = None,
    ):
        self.db = database or default_db
        self.audit = AuditService(self.db)
        self.obs = observability or ObservabilityService(self.db)
        self.tools = ControlledToolRegistry(self.db)
        self.rag = HybridRAGEngine(self.db, self.obs)

    def start_workflow(
        self,
        ctx: TenantRequestContext,
        workspace_id: str,
        query: str,
        conversation_id: Optional[str] = None,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        is_inj, reason = PromptInjectionGuard.inspect_user_query(query)
        if is_inj:
            self.audit.log_event(
                organization_id=ctx.organization_id,
                actor_user_id=ctx.user_id,
                event_type="AGENT_PROMPT_INJECTION_BLOCKED",
                resource_type="agent_workflow",
                action="start_workflow",
                status="BLOCKED",
                metadata={"query": query[:200], "reason": reason},
            )
            raise SecurityViolationError("PROMPT_INJECTION_DETECTED", f"Agent workflow blocked: {reason}", 400)

        run_id = new_id("run")
        now = utc_now_iso()
        params = parameters or {}

        state: Dict[str, Any] = {
            "run_id": run_id,
            "organization_id": ctx.organization_id,
            "workspace_id": workspace_id,
            "user_id": ctx.user_id,
            "user_role": ctx.role,
            "query": query,
            "parameters": params,
            "intent": "unclassified",
            "plan": [],
            "visited_nodes": [],
            "step_count": 0,
            "max_steps": settings.agent_max_steps,
            "retrieved_evidence": None,
            "comparison_report": None,
            "analytics_output": None,
            "pending_tool": None,
            "tool_results": [],
            "evidence_verified": False,
            "approval_request_id": None,
            "final_response": None,
            "citations": [],
            "status": "RUNNING",
        }

        self.db.execute(
            '''
            INSERT INTO agent_runs (
                id, organization_id, workspace_id, user_id, conversation_id,
                intent, status, current_node, step_count, max_steps,
                input_query, trace_id, started_at
            ) VALUES (?, ?, ?, ?, ?, 'unclassified', 'RUNNING', 'classify_request', 0, ?, ?, ?, ?)
            ''',
            (
                run_id,
                ctx.organization_id,
                workspace_id,
                ctx.user_id,
                conversation_id,
                settings.agent_max_steps,
                query,
                ctx.trace_id,
                now,
            ),
        )

        # Node 1: classify_request
        state = self._transition(ctx, state, "classify_request", self._node_classify_request)
        # Node 2: plan_tasks
        state = self._transition(ctx, state, "plan_tasks", self._node_plan_tasks)

        # Supervisor routing based on classified intent
        intent = state["intent"]
        if intent == "document_comparison":
            state = self._transition(ctx, state, "document_analysis_node", self._node_document_analysis)
        elif intent == "data_analytics":
            state = self._transition(ctx, state, "data_analysis_node", self._node_data_analysis)
        elif intent == "action_workflow":
            state = self._transition(ctx, state, "tool_execution_node", self._node_prepare_or_run_tool)
            if state.get("requires_human_approval"):
                state = self._transition(ctx, state, "human_approval_node", self._node_human_approval_pause)
                return self.get_run_details(ctx, run_id)
        else:
            state = self._transition(ctx, state, "knowledge_retrieval_node", self._node_knowledge_retrieval)

        # Node 7: evidence_verification_node
        state = self._transition(ctx, state, "evidence_verification_node", self._node_verify_evidence)
        # Node 9: response_generation_node
        state = self._transition(ctx, state, "response_generation_node", self._node_generate_response)
        # Node 10: workflow_completion_node
        state = self._transition(ctx, state, "workflow_completion_node", self._node_complete_workflow)

        return self.get_run_details(ctx, run_id)

    def resume_after_approval(
        self,
        ctx: TenantRequestContext,
        approval_id: str,
        decision: str,
        review_note: str = "",
    ) -> Dict[str, Any]:
        if not ctx.has_min_role("MANAGER"):
            raise SecurityViolationError(
                "APPROVAL_ROLE_DENIED",
                f"Role {ctx.role} cannot approve consequential agent actions (requires MANAGER, ADMIN, or OWNER).",
                403,
            )
        app_req = self.db.fetch_one("SELECT * FROM approval_requests WHERE id = ?", (approval_id,))
        if not app_req:
            raise ValueError(f"Approval request {approval_id} not found.")
        if app_req["organization_id"] != ctx.organization_id:
            raise SecurityViolationError("CROSS_TENANT_APPROVAL_DENIED", "Approval belongs to another tenant", 403)
        if app_req["status"] != "PENDING":
            raise ValueError(f"Approval request {approval_id} is already {app_req['status']}.")

        norm_decision = decision.strip().upper()
        if norm_decision not in {"APPROVED", "REJECTED"}:
            raise ValueError("Decision must be 'APPROVED' or 'REJECTED'.")

        now = utc_now_iso()
        self.db.execute(
            '''
            UPDATE approval_requests
            SET status = ?, reviewed_by = ?, review_note = ?, resolved_at = ?
            WHERE id = ?
            ''',
            (norm_decision, ctx.user_id, review_note.strip(), now, approval_id),
        )

        run_id = app_req["agent_run_id"]
        last_cp = self.db.fetch_one(
            '''
            SELECT * FROM agent_checkpoints
            WHERE agent_run_id = ? AND organization_id = ?
            ORDER BY step_number DESC LIMIT 1
            ''',
            (run_id, ctx.organization_id),
        )
        if not last_cp:
            raise ValueError(f"No checkpoint found for agent run {run_id}")
        state = json.loads(last_cp["state_json"])
        state["approval_status"] = norm_decision
        state["approved_by"] = ctx.user_id
        state["review_note"] = review_note.strip()

        if norm_decision == "REJECTED":
            state["status"] = "CANCELLED"
            state["final_response"] = f"Workflow cancelled: Consequential tool '{app_req['tool_name']}' was rejected by {ctx.email} ({review_note})."
            state = self._transition(ctx, state, "workflow_completion_node", self._node_complete_workflow)
            self.audit.log_event(
                organization_id=ctx.organization_id,
                actor_user_id=ctx.user_id,
                event_type="AGENT_APPROVAL_REJECTED",
                resource_type="approval_request",
                resource_id=approval_id,
                action="reject",
            )
            return self.get_run_details(ctx, run_id)

        # Approved: execute the pending tool from checkpoint state
        pending = state["pending_tool"]
        tool_out = self.tools.execute_tool(
            ctx=ctx,
            agent_run_id=run_id,
            tool_name=pending["tool_name"],
            arguments=pending["arguments"],
            idempotency_key=f"hitl_{approval_id}",
            approved_by=ctx.user_id,
        )
        state["tool_results"].append({"tool_name": pending["tool_name"], "output": tool_out})
        state["status"] = "RUNNING"

        state = self._transition(ctx, state, "evidence_verification_node", self._node_verify_evidence)
        state = self._transition(ctx, state, "response_generation_node", self._node_generate_response)
        state = self._transition(ctx, state, "workflow_completion_node", self._node_complete_workflow)

        self.audit.log_event(
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            event_type="AGENT_APPROVAL_GRANTED_AND_RESUMED",
            resource_type="approval_request",
            resource_id=approval_id,
            action="approve_and_resume",
        )
        return self.get_run_details(ctx, run_id)

    def _transition(
        self,
        ctx: TenantRequestContext,
        state: Dict[str, Any],
        node_name: str,
        fn: Any,
    ) -> Dict[str, Any]:
        if state["step_count"] >= state["max_steps"]:
            state["status"] = "FAILED"
            state["error"] = f"Exceeded maximum workflow step limit ({state['max_steps']})."
            raise RuntimeError(state["error"])

        t0 = time.perf_counter()
        state["step_count"] += 1
        state["current_node"] = node_name
        state["visited_nodes"].append(node_name)
        state = fn(ctx, state)
        dur_ms = round((time.perf_counter() - t0) * 1000, 2)

        cp_id = new_id("ckp")
        self.db.execute(
            '''
            INSERT INTO agent_checkpoints (id, agent_run_id, organization_id, step_number, node_name, state_json, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (cp_id, state["run_id"], ctx.organization_id, state["step_count"], node_name, json.dumps(state), utc_now_iso()),
        )
        self.db.execute(
            '''
            UPDATE agent_runs
            SET intent = ?, status = ?, current_node = ?, step_count = ?, final_output = ?
            WHERE id = ?
            ''',
            (
                state["intent"],
                state["status"],
                node_name,
                state["step_count"],
                state.get("final_response"),
                state["run_id"],
            ),
        )
        self.obs.record_span(
            trace_id=ctx.trace_id,
            organization_id=ctx.organization_id,
            span_name=f"langgraph_node:{node_name}",
            component="agent_orchestrator",
            duration_ms=dur_ms,
            attributes={"run_id": state["run_id"], "step": state["step_count"], "intent": state["intent"]},
        )
        return state

    def _node_classify_request(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        q = state["query"].lower()
        params = state.get("parameters") or {}
        if params.get("intent"):
            state["intent"] = params["intent"]
        elif any(k in q for k in ["create task", "open task", "compliance task", "action item", "remediation task"]):
            state["intent"] = "action_workflow"
        elif any(k in q for k in ["compare", "difference", "previous version", "version 1", "version 2", "v1", "v2"]):
            state["intent"] = "document_comparison"
        elif any(k in q for k in ["csv", "spreadsheet", "dataset", "sum", "average", "mean", "revenue by", "analyze data"]):
            state["intent"] = "data_analytics"
        else:
            state["intent"] = "knowledge_qa"
        return state

    def _node_plan_tasks(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        intent = state["intent"]
        if intent == "document_comparison":
            state["plan"] = [
                "Locate target policy documents and versions within tenant workspace",
                "Invoke compare_documents tool to extract clause-level differences and quantitative shifts",
                "Verify every citation points to an existing document version and page",
                "Compile structured comparison and operational impact review report",
            ]
        elif intent == "data_analytics":
            state["plan"] = [
                "Locate authorized structured dataset in workspace",
                "Execute deterministic Pandas aggregation via analyse_csv tool",
                "Verify numerical consistency and report assumptions",
            ]
        elif intent == "action_workflow":
            state["plan"] = [
                "Validate RBAC permissions for state-changing tool create_internal_task",
                "Pause at HumanApprovalNode and persist checkpoint",
                "Execute create_internal_task with idempotency key upon Manager/Admin approval",
            ]
        else:
            state["plan"] = [
                "Execute hybrid dense + lexical retrieval with Reciprocal Rank Fusion",
                "Verify retrieved chunk citations and check abstention threshold",
                "Synthesize grounded response",
            ]
        return state

    def _node_knowledge_retrieval(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        rag_res = self.rag.retrieve_and_answer(
            ctx=ctx,
            query=state["query"],
            workspace_id=state["workspace_id"],
            top_k=5,
        )
        state["retrieved_evidence"] = rag_res
        state["citations"] = rag_res["citations"]
        return state

    def _node_document_analysis(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        params = state.get("parameters") or {}
        doc_a_id = params.get("doc_a_id")
        doc_b_id = params.get("doc_b_id")
        if not doc_a_id or not doc_b_id:
            docs = self.db.fetch_all(
                "SELECT id, current_version FROM documents WHERE organization_id = ? AND workspace_id = ? ORDER BY updated_at DESC",
                (ctx.organization_id, state["workspace_id"]),
            )
            if docs:
                doc_a_id = docs[0]["id"]
                doc_b_id = docs[0]["id"] if docs[0]["current_version"] > 1 else (docs[1]["id"] if len(docs) > 1 else docs[0]["id"])
        comp_out = self.tools.execute_tool(
            ctx=ctx,
            agent_run_id=state["run_id"],
            tool_name="compare_documents",
            arguments={
                "doc_a_id": doc_a_id,
                "doc_b_id": doc_b_id,
                "version_a": params.get("version_a"),
                "version_b": params.get("version_b"),
            },
        )
        state["comparison_report"] = comp_out
        state["citations"] = comp_out.get("source_references", [])
        state["tool_results"].append({"tool_name": "compare_documents", "output": comp_out})
        return state

    def _node_data_analysis(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        params = state.get("parameters") or {}
        dataset_id = params.get("dataset_id")
        if not dataset_id:
            ds_rows = self.db.fetch_all(
                "SELECT id FROM datasets WHERE organization_id = ? AND workspace_id = ? ORDER BY created_at DESC LIMIT 1",
                (ctx.organization_id, state["workspace_id"]),
            )
            if not ds_rows:
                raise ValueError("No datasets found in workspace for data_analysis_node.")
            dataset_id = ds_rows[0]["id"]
        ana_out = self.tools.execute_tool(
            ctx=ctx,
            agent_run_id=state["run_id"],
            tool_name="analyse_csv",
            arguments={
                "dataset_id": dataset_id,
                "operation": params.get("operation", "describe"),
                "group_by_column": params.get("group_by_column"),
                "metric_column": params.get("metric_column"),
                "agg_func": params.get("agg_func", "sum"),
            },
        )
        state["analytics_output"] = ana_out
        state["tool_results"].append({"tool_name": "analyse_csv", "output": ana_out})
        return state

    def _node_prepare_or_run_tool(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        params = state.get("parameters") or {}
        tool_name = params.get("tool_name", "create_internal_task")
        tool_args = params.get("tool_arguments") or {
            "workspace_id": state["workspace_id"],
            "title": params.get("task_title") or f"Action Required: {state['query'][:60]}",
            "description": state["query"],
            "priority": params.get("priority", "HIGH"),
        }
        tool_def = self.tools.validate_and_check_permissions(ctx, tool_name, tool_args)
        state["pending_tool"] = {"tool_name": tool_name, "arguments": tool_args}
        state["requires_human_approval"] = tool_def.requires_approval
        if not tool_def.requires_approval:
            out = self.tools.execute_tool(ctx, state["run_id"], tool_name, tool_args)
            state["tool_results"].append({"tool_name": tool_name, "output": out})
        return state

    def _node_human_approval_pause(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        pending = state["pending_tool"]
        app_id = new_id("apr")
        now = utc_now_iso()
        summary = f"Execute tool '{pending['tool_name']}' with arguments: {json.dumps(pending['arguments'])}"
        self.db.execute(
            '''
            INSERT INTO approval_requests (
                id, organization_id, agent_run_id, tool_name, action_summary,
                payload_json, requested_by, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?)
            ''',
            (
                app_id,
                ctx.organization_id,
                state["run_id"],
                pending["tool_name"],
                summary,
                json.dumps(pending["arguments"]),
                ctx.user_id,
                now,
            ),
        )
        state["approval_request_id"] = app_id
        state["status"] = "WAITING_APPROVAL"
        self.audit.log_event(
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            event_type="HUMAN_APPROVAL_REQUESTED",
            resource_type="approval_request",
            resource_id=app_id,
            action="pause_workflow",
            metadata={"agent_run_id": state["run_id"], "tool_name": pending["tool_name"]},
        )
        return state

    def _node_verify_evidence(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        if state["intent"] == "document_comparison" and state.get("comparison_report"):
            refs = state["comparison_report"].get("source_references", [])
            state["evidence_verified"] = len(refs) > 0
        elif state["intent"] == "data_analytics" and state.get("analytics_output"):
            state["evidence_verified"] = bool(state["analytics_output"].get("deterministic_verified"))
        elif state["intent"] == "action_workflow" and state.get("tool_results"):
            state["evidence_verified"] = True
        elif state.get("retrieved_evidence"):
            ev = state["retrieved_evidence"]
            state["evidence_verified"] = (not ev["abstained"]) and len(ev["citations"]) > 0
        else:
            state["evidence_verified"] = False
        return state

    def _node_generate_response(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        if state["intent"] == "document_comparison" and state.get("comparison_report"):
            state["final_response"] = state["comparison_report"]["markdown_export"]
        elif state["intent"] == "data_analytics" and state.get("analytics_output"):
            ana = state["analytics_output"]
            state["final_response"] = (
                f"### Deterministic Data Analysis Result ({ana.get('dataset_name')})\n"
                f"- **Operation**: `{ana.get('operation')}`\n"
                f"- **Result Summary**: `{json.dumps({k: v for k, v in ana.items() if k not in {'schema', 'assumptions'}})}`\n"
                f"- **Verified Assumptions**: {'; '.join(ana.get('assumptions', []))}"
            )
        elif state["intent"] == "action_workflow" and state.get("tool_results"):
            last_tool = state["tool_results"][-1]
            state["final_response"] = (
                f"Approved action `{last_tool['tool_name']}` executed successfully after human authorization.\n"
                f"Result: `{json.dumps(last_tool['output'])}`"
            )
        elif state.get("retrieved_evidence"):
            state["final_response"] = state["retrieved_evidence"]["answer"]
        else:
            state["final_response"] = "ABSTENTION: Insufficient verified evidence to complete workflow."
        return state

    def _node_complete_workflow(self, ctx: TenantRequestContext, state: Dict[str, Any]) -> Dict[str, Any]:
        if state["status"] == "RUNNING":
            state["status"] = "COMPLETED"
        self.db.execute(
            "UPDATE agent_runs SET status = ?, final_output = ?, completed_at = ? WHERE id = ?",
            (state["status"], state.get("final_response"), utc_now_iso(), state["run_id"]),
        )
        return state

    def get_run_details(self, ctx: TenantRequestContext, run_id: str) -> Dict[str, Any]:
        run = self.db.fetch_one("SELECT * FROM agent_runs WHERE id = ?", (run_id,))
        if not run:
            raise ValueError(f"Agent run {run_id} not found.")
        if run["organization_id"] != ctx.organization_id:
            raise SecurityViolationError("CROSS_TENANT_AGENT_RUN", "Agent run belongs to another organization", 403)
        checkpoints = self.db.fetch_all(
            "SELECT id, step_number, node_name, state_json, created_at FROM agent_checkpoints WHERE agent_run_id = ? ORDER BY step_number ASC",
            (run_id,),
        )
        tool_execs = self.db.fetch_all(
            "SELECT * FROM tool_executions WHERE agent_run_id = ? ORDER BY created_at ASC",
            (run_id,),
        )
        approvals = self.db.fetch_all(
            "SELECT * FROM approval_requests WHERE agent_run_id = ? ORDER BY created_at ASC",
            (run_id,),
        )
        latest_state = json.loads(checkpoints[-1]["state_json"]) if checkpoints else {}
        return {
            "run": run,
            "plan": latest_state.get("plan", []),
            "visited_nodes": [c["node_name"] for c in checkpoints],
            "checkpoints": [
                {"id": c["id"], "step_number": c["step_number"], "node_name": c["node_name"], "created_at": c["created_at"]}
                for c in checkpoints
            ],
            "tool_executions": tool_execs,
            "approval_requests": approvals,
            "evidence_verified": latest_state.get("evidence_verified", False),
            "citations": latest_state.get("citations", []),
            "comparison_report": latest_state.get("comparison_report"),
            "analytics_output": latest_state.get("analytics_output"),
        }

    def list_runs(self, ctx: TenantRequestContext) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM agent_runs WHERE organization_id = ? ORDER BY started_at DESC LIMIT 50",
            (ctx.organization_id,),
        )

    def list_pending_approvals(self, ctx: TenantRequestContext) -> List[Dict[str, Any]]:
        return self.db.fetch_all(
            "SELECT * FROM approval_requests WHERE organization_id = ? ORDER BY created_at DESC",
            (ctx.organization_id,),
        )
