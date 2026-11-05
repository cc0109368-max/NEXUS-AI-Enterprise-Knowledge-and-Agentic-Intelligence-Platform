import base64
import csv
import hashlib
import io
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import docx
import openpyxl
import pandas as pd
import pypdf
from packages.shared_contracts.schemas import CLASSIFICATION_TO_MIN_ROLE
from packages.llm_core.provider import get_llm_provider
from app.core.config import settings
from app.core.database import DatabaseManager, db as default_db, new_id, utc_now_iso
from app.core.security import PromptInjectionGuard, SecurityViolationError, TenantRequestContext
from app.audit.service import AuditService
from app.observability.tracer import ObservabilityService

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx"}

class DocumentIntelligenceService:
    '''
    Module B: Secure Document Upload, Multi-Format Parsing, Versioning,
    Indirect Prompt Injection Scanning, Structural Chunking, and Idempotent Indexing.
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
        self.storage_dir = Path(tempfile.gettempdir()) / "nexus-ai" / "storage"
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def upload_and_ingest_document(
        self,
        ctx: TenantRequestContext,
        workspace_id: str,
        title: str,
        filename: str,
        classification: str = "INTERNAL",
        raw_bytes: Optional[bytes] = None,
        raw_text: Optional[str] = None,
        mime_type: str = "text/markdown",
        change_summary: str = "Initial upload",
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise ValueError(f"Unsupported file type '{ext}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}")

        if raw_bytes is None:
            if raw_text is not None:
                raw_bytes = raw_text.encode("utf-8")
            else:
                raise ValueError("Document upload requires either raw_bytes or raw_text.")

        if len(raw_bytes) == 0:
            raise ValueError("Uploaded document is empty (0 bytes).")
        if len(raw_bytes) > settings.max_upload_bytes:
            raise ValueError(f"File size {len(raw_bytes)} exceeds limit of {settings.max_upload_bytes} bytes.")

        ws = self.db.fetch_one(
            "SELECT id FROM workspaces WHERE id = ? AND organization_id = ?",
            (workspace_id, ctx.organization_id),
        )
        if not ws:
            raise SecurityViolationError("INVALID_WORKSPACE", "Workspace does not belong to organization", 403)

        sha256_hash = hashlib.sha256(raw_bytes).hexdigest()
        idem_key = idempotency_key or f"ing_{ctx.organization_id}_{workspace_id}_{filename}_{sha256_hash[:16]}"

        # Check idempotency job first
        existing_job = self.db.fetch_one(
            "SELECT * FROM ingestion_jobs WHERE idempotency_key = ? AND organization_id = ?",
            (idem_key, ctx.organization_id),
        )
        if existing_job and existing_job["status"] == "COMPLETED":
            doc = self.get_document(ctx, existing_job["document_id"])
            return {
                "document": doc,
                "ingestion_job_id": existing_job["id"],
                "idempotent_replay": True,
                "status": doc["status"],
            }

        # Check if document with same title/filename exists in workspace for versioning
        existing_doc = self.db.fetch_one(
            "SELECT * FROM documents WHERE organization_id = ? AND workspace_id = ? AND filename = ?",
            (ctx.organization_id, workspace_id, filename),
        )
        now = utc_now_iso()
        min_role = CLASSIFICATION_TO_MIN_ROLE.get(classification, "MEMBER")

        if existing_doc:
            # Check exact duplicate hash on current version
            if existing_doc["sha256_hash"] == sha256_hash and existing_doc["status"] == "READY":
                return {
                    "document": existing_doc,
                    "ingestion_job_id": existing_job["id"] if existing_job else "dedup_hit",
                    "idempotent_replay": True,
                    "status": "READY",
                }
            doc_id = existing_doc["id"]
            version_number = int(existing_doc["current_version"]) + 1
            self.db.execute(
                '''
                UPDATE documents
                SET current_version = ?, sha256_hash = ?, file_size_bytes = ?,
                    classification = ?, min_role_required = ?, status = 'PROCESSING', updated_at = ?
                WHERE id = ?
                ''',
                (version_number, sha256_hash, len(raw_bytes), classification, min_role, now, doc_id),
            )
        else:
            doc_id = new_id("doc")
            version_number = 1
            self.db.execute(
                '''
                INSERT INTO documents (
                    id, organization_id, workspace_id, title, filename, mime_type,
                    file_size_bytes, sha256_hash, current_version, classification,
                    min_role_required, status, uploaded_by, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PROCESSING', ?, ?, ?)
                ''',
                (
                    doc_id,
                    ctx.organization_id,
                    workspace_id,
                    title.strip(),
                    filename,
                    mime_type,
                    len(raw_bytes),
                    sha256_hash,
                    version_number,
                    classification,
                    min_role,
                    ctx.user_id,
                    now,
                    now,
                ),
            )

        ver_id = new_id("ver")
        storage_path = str(self.storage_dir / f"{ctx.organization_id}_{doc_id}_v{version_number}{ext}")
        Path(storage_path).write_bytes(raw_bytes)

        # Create initial document_versions record before ingestion_jobs so FK document_version_id is satisfied
        self.db.execute(
            '''
            INSERT INTO document_versions (
                id, document_id, organization_id, version_number, sha256_hash,
                storage_path, page_count, word_count, parser_used, change_summary,
                created_by, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, 0, 'pending', ?, ?, ?)
            ''',
            (ver_id, doc_id, ctx.organization_id, version_number, sha256_hash, storage_path, change_summary, ctx.user_id, now),
        )
        job_id = existing_job["id"] if existing_job else new_id("job")
        if not existing_job:
            self.db.execute(
                '''
                INSERT INTO ingestion_jobs (
                    id, organization_id, document_id, document_version_id, idempotency_key,
                    status, attempt_count, max_attempts, started_at, created_at
                ) VALUES (?, ?, ?, ?, ?, 'PROCESSING', 1, 3, ?, ?)
                ''',
                (job_id, ctx.organization_id, doc_id, ver_id, idem_key, now, now),
            )

        try:
            pages, parser_name, dataset_meta = self._parse_file_bytes(
                ext=ext,
                raw_bytes=raw_bytes,
                ctx=ctx,
                workspace_id=workspace_id,
                doc_id=doc_id,
                title=title,
            )
            total_words = sum(len(p["text"].split()) for p in pages)
            if total_words == 0:
                err_msg = (
                    "Scanned or empty document detected: 0 extractable words found. "
                    "OCR is not enabled; refusing to fabricate empty chunks."
                )
                self.db.execute(
                    "UPDATE documents SET status = 'FAILED', error_message = ?, updated_at = ? WHERE id = ?",
                    (err_msg, utc_now_iso(), doc_id),
                )
                self.db.execute(
                    "UPDATE ingestion_jobs SET status = 'FAILED', error_message = ?, completed_at = ? WHERE id = ?",
                    (err_msg, utc_now_iso(), job_id),
                )
                raise ValueError(err_msg)

            self.db.execute(
                '''
                UPDATE document_versions
                SET page_count = ?, word_count = ?, parser_used = ?
                WHERE id = ?
                ''',
                (len(pages), total_words, parser_name, ver_id),
            )

            chunks = self._chunk_pages(pages)
            texts_to_embed = [c["sanitized_content"] for c in chunks]
            embeddings = self.llm.embed_texts(texts_to_embed, task_type="RETRIEVAL_DOCUMENT")

            quarantined_count = 0
            with self.db.connection() as conn:
                for idx, (chunk, emb) in enumerate(zip(chunks, embeddings)):
                    chunk_id = new_id("chk")
                    emb_id = new_id("emb")
                    is_quarantined = 1 if chunk["is_quarantined"] else 0
                    if is_quarantined:
                        quarantined_count += 1
                    conn.execute(
                        '''
                        INSERT INTO document_chunks (
                            id, document_id, document_version_id, organization_id, workspace_id,
                            chunk_index, page_number, section_title, content, token_count,
                            char_start, char_end, metadata_json, is_quarantined_injection, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            chunk_id,
                            doc_id,
                            ver_id,
                            ctx.organization_id,
                            workspace_id,
                            idx,
                            chunk["page_number"],
                            chunk["section_title"],
                            chunk["content"],
                            chunk["token_count"],
                            chunk["char_start"],
                            chunk["char_end"],
                            json.dumps(chunk["metadata"]),
                            is_quarantined,
                            now,
                        ),
                    )
                    conn.execute(
                        '''
                        INSERT INTO document_chunks_fts (chunk_id, organization_id, document_id, section_title, content)
                        VALUES (?, ?, ?, ?, ?)
                        ''',
                        (chunk_id, ctx.organization_id, doc_id, chunk["section_title"], chunk["sanitized_content"]),
                    )
                    conn.execute(
                        '''
                        INSERT INTO document_embeddings (
                            id, chunk_id, organization_id, embedding_model, dimensions, vector_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''',
                        (
                            emb_id,
                            chunk_id,
                            ctx.organization_id,
                            settings.gemini_embedding_model,
                            len(emb),
                            json.dumps(emb),
                            now,
                        ),
                    )
                conn.execute(
                    "UPDATE documents SET status = 'READY', error_message = NULL, updated_at = ? WHERE id = ?",
                    (utc_now_iso(), doc_id),
                )
                conn.execute(
                    "UPDATE ingestion_jobs SET status = 'COMPLETED', completed_at = ? WHERE id = ?",
                    (utc_now_iso(), job_id),
                )

            if quarantined_count > 0:
                self.audit.log_event(
                    organization_id=ctx.organization_id,
                    actor_user_id=ctx.user_id,
                    event_type="INDIRECT_PROMPT_INJECTION_QUARANTINED",
                    resource_type="document",
                    resource_id=doc_id,
                    action="ingest_scan",
                    status="QUARANTINED_CHUNKS",
                    metadata={"quarantined_chunks": quarantined_count, "filename": filename},
                )

            self.audit.log_event(
                organization_id=ctx.organization_id,
                actor_user_id=ctx.user_id,
                event_type="DOCUMENT_INGESTED",
                resource_type="document",
                resource_id=doc_id,
                action="ingest",
                metadata={
                    "version": version_number,
                    "chunks": len(chunks),
                    "quarantined_chunks": quarantined_count,
                    "dataset_id": dataset_meta["id"] if dataset_meta else None,
                },
            )
            doc_record = self.get_document(ctx, doc_id)
            return {
                "document": doc_record,
                "version_id": ver_id,
                "version_number": version_number,
                "ingestion_job_id": job_id,
                "chunk_count": len(chunks),
                "quarantined_chunks": quarantined_count,
                "dataset": dataset_meta,
                "idempotent_replay": False,
                "status": "READY",
            }
        except Exception as exc:
            self.db.execute(
                "UPDATE documents SET status = 'FAILED', error_message = ?, updated_at = ? WHERE id = ?",
                (str(exc), utc_now_iso(), doc_id),
            )
            self.db.execute(
                "UPDATE ingestion_jobs SET status = 'FAILED', error_message = ?, completed_at = ? WHERE id = ?",
                (str(exc), utc_now_iso(), job_id),
            )
            raise

    def _parse_file_bytes(
        self,
        ext: str,
        raw_bytes: bytes,
        ctx: TenantRequestContext,
        workspace_id: str,
        doc_id: str,
        title: str,
    ) -> Tuple[List[Dict[str, Any]], str, Optional[Dict[str, Any]]]:
        dataset_meta = None
        if ext in {".md", ".txt"}:
            text = raw_bytes.decode("utf-8", errors="replace")
            # Split synthetic multi-page markers if present (e.g. <!-- PAGE 2 -->)
            raw_pages = re.split(r"<!--\s*PAGE\s+\d+\s*-->|\f", text)
            pages = [
                {"page_number": i + 1, "text": p.strip()}
                for i, p in enumerate(raw_pages)
                if p.strip()
            ]
            return pages, "markdown_text_parser", None

        if ext == ".pdf":
            reader = pypdf.PdfReader(io.BytesIO(raw_bytes))
            pages = []
            for idx, page in enumerate(reader.pages):
                txt = (page.extract_text() or "").strip()
                if txt:
                    pages.append({"page_number": idx + 1, "text": txt})
            return pages, "pypdf_structural_parser", None

        if ext == ".docx":
            doc = docx.Document(io.BytesIO(raw_bytes))
            paras = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
            return [{"page_number": 1, "text": "\n\n".join(paras)}], "python_docx_parser", None

        if ext in {".csv", ".xlsx"}:
            if ext == ".csv":
                df = pd.read_csv(io.BytesIO(raw_bytes))
                parser_name = "pandas_csv_parser"
            else:
                df = pd.read_excel(io.BytesIO(raw_bytes))
                parser_name = "openpyxl_xlsx_parser"

            schema_info = []
            for col in df.columns:
                schema_info.append({
                    "column": str(col),
                    "dtype": str(df[col].dtype),
                    "missing_count": int(df[col].isna().sum()),
                    "non_null_count": int(df[col].notna().sum()),
                })
            num_cols = df.select_dtypes(include=["number"]).columns.tolist()
            stats = {}
            for nc in num_cols:
                series = df[nc].dropna()
                if len(series) > 0:
                    stats[str(nc)] = {
                        "count": int(series.count()),
                        "mean": round(float(series.mean()), 4),
                        "sum": round(float(series.sum()), 4),
                        "min": round(float(series.min()), 4),
                        "max": round(float(series.max()), 4),
                        "std": round(float(series.std()), 4) if len(series) > 1 else 0.0,
                    }

            ds_id = new_id("ds")
            self.db.execute(
                '''
                INSERT INTO datasets (
                    id, organization_id, workspace_id, document_id, name,
                    row_count, column_count, schema_json, summary_stats_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''',
                (
                    ds_id,
                    ctx.organization_id,
                    workspace_id,
                    doc_id,
                    title.strip(),
                    int(len(df)),
                    int(len(df.columns)),
                    json.dumps(schema_info),
                    json.dumps(stats),
                    utc_now_iso(),
                ),
            )
            dataset_meta = {
                "id": ds_id,
                "name": title.strip(),
                "row_count": int(len(df)),
                "column_count": int(len(df.columns)),
                "schema": schema_info,
                "summary_stats": stats,
            }
            summary_lines = [
                f"# Structured Dataset Summary: {title}",
                f"Rows: {len(df)}, Columns: {len(df.columns)} ({', '.join(map(str, df.columns))})",
                "## Deterministic Numerical Summary",
            ]
            for col_name, st in stats.items():
                summary_lines.append(
                    f"- Column {col_name}: sum={st['sum']}, mean={st['mean']}, min={st['min']}, max={st['max']}, count={st['count']}"
                )
            summary_lines.append("## Sample Records")
            for idx_row, row in df.head(15).iterrows():
                row_str = ", ".join(f"{k}={v}" for k, v in row.to_dict().items())
                summary_lines.append(f"Row {idx_row + 1}: {row_str}")
            return [{"page_number": 1, "text": "\n".join(summary_lines)}], parser_name, dataset_meta

        raise ValueError(f"Unsupported file extension: {ext}")

    def _chunk_pages(self, pages: List[Dict[str, Any]], max_words: int = 140) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        for page in pages:
            page_num = page["page_number"]
            text = page["text"]
            blocks = re.split(r"\n(?=##?#?\s+|SECTION\s+\d+|\d+\.\d+\s+)", text)
            char_cursor = 0
            current_section = "General Overview"

            for block in blocks:
                block = block.strip()
                if not block:
                    continue
                lines = block.splitlines()
                first_line = lines[0].strip()
                if first_line.startswith("#") or re.match(r"^(SECTION\s+\d+|\d+\.\d+\s+|[A-Z][A-Z0-9\s\-:]{4,40}$)", first_line):
                    current_section = first_line.lstrip("#").strip()

                words = block.split()
                for start_idx in range(0, len(words), max(1, max_words - 20)):
                    slice_words = words[start_idx : start_idx + max_words]
                    chunk_text = " ".join(slice_words)
                    is_suspicious, sanitized_text, matched_rules = PromptInjectionGuard.scan_document_chunk(chunk_text)
                    char_start = char_cursor
                    char_end = char_cursor + len(chunk_text)
                    char_cursor = char_end + 1
                    chunks.append({
                        "page_number": page_num,
                        "section_title": current_section[:120],
                        "content": chunk_text,
                        "sanitized_content": sanitized_text,
                        "token_count": len(slice_words),
                        "char_start": char_start,
                        "char_end": char_end,
                        "is_quarantined": is_suspicious,
                        "metadata": {
                            "injection_rules_triggered": matched_rules,
                            "word_count": len(slice_words),
                        },
                    })
        return chunks

    def get_document(self, ctx: TenantRequestContext, document_id: str) -> Dict[str, Any]:
        doc = self.db.fetch_one("SELECT * FROM documents WHERE id = ?", (document_id,))
        if not doc:
            raise ValueError(f"Document {document_id} not found.")
        if doc["organization_id"] != ctx.organization_id:
            self.audit.log_event(
                organization_id=ctx.organization_id,
                actor_user_id=ctx.user_id,
                event_type="CROSS_TENANT_DOCUMENT_ACCESS_BLOCKED",
                resource_type="document",
                resource_id=document_id,
                action="get_document",
                status="BLOCKED",
                metadata={"target_org_id": doc["organization_id"]},
            )
            raise SecurityViolationError(
                "CROSS_TENANT_ACCESS_DENIED",
                f"Document {document_id} belongs to another organization.",
                403,
            )
        if not ctx.can_access_classification(doc["classification"]):
            self.audit.log_event(
                organization_id=ctx.organization_id,
                actor_user_id=ctx.user_id,
                event_type="UNAUTHORIZED_CLASSIFICATION_ACCESS_BLOCKED",
                resource_type="document",
                resource_id=document_id,
                action="get_document",
                status="BLOCKED",
                metadata={"classification": doc["classification"], "user_role": ctx.role},
            )
            raise SecurityViolationError(
                "CLASSIFICATION_ACCESS_DENIED",
                f"Role {ctx.role} cannot access {doc['classification']} document (requires {doc['min_role_required']}).",
                403,
            )
        return doc

    def list_documents(self, ctx: TenantRequestContext, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if workspace_id:
            rows = self.db.fetch_all(
                "SELECT * FROM documents WHERE organization_id = ? AND workspace_id = ? ORDER BY updated_at DESC",
                (ctx.organization_id, workspace_id),
            )
        else:
            rows = self.db.fetch_all(
                "SELECT * FROM documents WHERE organization_id = ? ORDER BY updated_at DESC",
                (ctx.organization_id,),
            )
        return [r for r in rows if ctx.can_access_classification(r["classification"])]

    def get_document_versions(self, ctx: TenantRequestContext, document_id: str) -> List[Dict[str, Any]]:
        self.get_document(ctx, document_id)
        return self.db.fetch_all(
            "SELECT * FROM document_versions WHERE document_id = ? AND organization_id = ? ORDER BY version_number DESC",
            (document_id, ctx.organization_id),
        )

    def get_document_chunks(
        self, ctx: TenantRequestContext, document_id: str, version_number: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        doc = self.get_document(ctx, document_id)
        target_ver = version_number or doc["current_version"]
        ver = self.db.fetch_one(
            "SELECT id FROM document_versions WHERE document_id = ? AND version_number = ?",
            (document_id, target_ver),
        )
        if not ver:
            return []
        return self.db.fetch_all(
            "SELECT * FROM document_chunks WHERE document_id = ? AND document_version_id = ? ORDER BY chunk_index ASC",
            (document_id, ver["id"]),
        )

    def delete_document(self, ctx: TenantRequestContext, document_id: str) -> Dict[str, Any]:
        if not ctx.has_min_role("MANAGER"):
            raise SecurityViolationError("INSUFFICIENT_ROLE", "Requires MANAGER or higher to delete documents", 403)
        doc = self.get_document(ctx, document_id)
        with self.db.connection() as conn:
            conn.execute("DELETE FROM document_chunks_fts WHERE document_id = ? AND organization_id = ?", (document_id, ctx.organization_id))
            conn.execute("DELETE FROM documents WHERE id = ? AND organization_id = ?", (document_id, ctx.organization_id))
        self.audit.log_event(
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            event_type="DOCUMENT_DELETED",
            resource_type="document",
            resource_id=document_id,
            action="delete",
            metadata={"title": doc["title"]},
        )
        return {"deleted": True, "document_id": document_id}
