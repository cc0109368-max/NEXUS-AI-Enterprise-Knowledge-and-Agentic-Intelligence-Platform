import difflib
import re
from typing import Any, Dict, List, Optional
from app.core.database import DatabaseManager, db as default_db, new_id, utc_now_iso
from app.core.security import TenantRequestContext
from app.documents.service import DocumentIntelligenceService
from app.audit.service import AuditService

class DocumentComparisonService:
    '''
    Module H: Document Comparison, Policy Diff Detection, and Traceable Report Generation.
    Clearly separates directly extracted source facts (with exact page/chunk citations)
    from synthesized operational impact and risk analysis.
    '''
    def __init__(self, database: Optional[DatabaseManager] = None):
        self.db = database or default_db
        self.docs = DocumentIntelligenceService(self.db)
        self.audit = AuditService(self.db)

    def compare_documents(
        self,
        ctx: TenantRequestContext,
        doc_a_id: str,
        doc_b_id: str,
        version_a: Optional[int] = None,
        version_b: Optional[int] = None,
        report_title: str = "Enterprise Policy Comparison & Impact Review Report",
    ) -> Dict[str, Any]:
        doc_a = self.docs.get_document(ctx, doc_a_id)
        doc_b = self.docs.get_document(ctx, doc_b_id)

        ver_a = version_a or (1 if doc_a_id == doc_b_id and doc_a["current_version"] > 1 else doc_a["current_version"])
        ver_b = version_b or doc_b["current_version"]

        chunks_a = self.docs.get_document_chunks(ctx, doc_a_id, version_number=ver_a)
        chunks_b = self.docs.get_document_chunks(ctx, doc_b_id, version_number=ver_b)

        map_a = {c["section_title"]: c for c in chunks_a}
        map_b = {c["section_title"]: c for c in chunks_b}
        all_sections = list(dict.fromkeys(list(map_a.keys()) + list(map_b.keys())))

        extracted_differences: List[Dict[str, Any]] = []
        source_references: List[Dict[str, Any]] = []
        operational_impacts: List[Dict[str, Any]] = []

        for sec in all_sections:
            ca = map_a.get(sec)
            cb = map_b.get(sec)
            if ca and cb:
                if ca["content"].strip() != cb["content"].strip():
                    cite_a = f"DOC-{doc_a_id}:v{ver_a}:p{ca['page_number']}:c{ca['chunk_index']}"
                    cite_b = f"DOC-{doc_b_id}:v{ver_b}:p{cb['page_number']}:c{cb['chunk_index']}"
                    nums_a = re.findall(r"\b\d+\s*(?:days?|months?|years?|hours?|%|MB|GB)\b", ca["content"], flags=re.I)
                    nums_b = re.findall(r"\b\d+\s*(?:days?|months?|years?|hours?|%|MB|GB)\b", cb["content"], flags=re.I)
                    extracted_differences.append({
                        "section_title": sec,
                        "change_type": "MODIFIED",
                        "baseline_excerpt": ca["content"],
                        "baseline_citation": cite_a,
                        "Baseline_page": ca["page_number"],
                        "updated_excerpt": cb["content"],
                        "updated_citation": cite_b,
                        "updated_page": cb["page_number"],
                        "quantitative_shifts": {"from": nums_a, "to": nums_b},
                    })
                    source_references.extend([
                        {"citation_key": cite_a, "document_title": doc_a["title"], "version": ver_a, "page": ca["page_number"], "section": sec},
                        {"citation_key": cite_b, "document_title": doc_b["title"], "version": ver_b, "page": cb["page_number"], "section": sec},
                    ])
                    operational_impacts.append({
                        "section": sec,
                        "risk_level": "HIGH" if (nums_a != nums_b) else "MEDIUM",
                        "impact_analysis": (
                            f"Policy clause '{sec}' changed between {doc_a['title']} (v{ver_a}) and {doc_b['title']} (v{ver_b}). "
                            f"Quantitative thresholds shifted from {nums_a or ['baseline text']} to {nums_b or ['updated text']}, "
                            f"requiring compliance workflow and automated retention/SLA configuration updates."
                        ),
                        "supporting_citations": [cite_a, cite_b],
                    })
            elif cb and not ca:
                cite_b = f"DOC-{doc_b_id}:v{ver_b}:p{cb['page_number']}:c{cb['chunk_index']}"
                extracted_differences.append({
                    "section_title": sec,
                    "change_type": "ADDED",
                    "baseline_excerpt": None,
                    "baseline_citation": None,
                    "updated_excerpt": cb["content"],
                    "updated_citation": cite_b,
                    "updated_page": cb["page_number"],
                })
                source_references.append(
                    {"citation_key": cite_b, "document_title": doc_b["title"], "version": ver_b, "page": cb["page_number"], "section": sec}
                )
                operational_impacts.append({
                    "section": sec,
                    "risk_level": "MEDIUM",
                    "impact_analysis": f"New section '{sec}' introduced in {doc_b['title']} (v{ver_b}) [{cite_b}].",
                    "supporting_citations": [cite_b],
                })
            elif ca and not cb:
                cite_a = f"DOC-{doc_a_id}:v{ver_a}:p{ca['page_number']}:c{ca['chunk_index']}"
                extracted_differences.append({
                    "section_title": sec,
                    "change_type": "REMOVED",
                    "baseline_excerpt": ca["content"],
                    "baseline_citation": cite_a,
                    "updated_excerpt": None,
                    "updated_citation": None,
                })
                source_references.append(
                    {"citation_key": cite_a, "document_title": doc_a["title"], "version": ver_a, "page": ca["page_number"], "section": sec}
                )

        # Fallback if sections had different titles across two separate documents
        if not extracted_differences and chunks_a and chunks_b:
            ca, cb = chunks_a[0], chunks_b[0]
            cite_a = f"DOC-{doc_a_id}:v{ver_a}:p{ca['page_number']}:c{ca['chunk_index']}"
            cite_b = f"DOC-{doc_b_id}:v{ver_b}:p{cb['page_number']}:c{cb['chunk_index']}"
            extracted_differences.append({
                "section_title": f"{ca['section_title']} vs {cb['section_title']}",
                "change_type": "MODIFIED",
                "baseline_excerpt": ca["content"],
                "baseline_citation": cite_a,
                "updated_excerpt": cb["content"],
                "updated_citation": cite_b,
                "quantitative_shifts": {},
            })
            source_references.extend([
                {"citation_key": cite_a, "document_title": doc_a["title"], "version": ver_a, "page": ca["page_number"], "section": ca["section_title"]},
                {"citation_key": cite_b, "document_title": doc_b["title"], "version": ver_b, "page": cb["page_number"], "section": cb["section_title"]},
            ])

        md_lines = [
            f"# {report_title}",
            f"**Generated At:** {utc_now_iso()}  ",
            f"**Baseline Document:** {doc_a['title']} (Version {ver_a}, ID `{doc_a_id}`)  ",
            f"**Target Document:** {doc_b['title']} (Version {ver_b}, ID `{doc_b_id}`)",
            "",
            "## 1. Executive Summary",
            f"Comparison detected **{len(extracted_differences)} structural/policy difference(s)** across **{len(all_sections)} evaluated section(s)**.",
            "",
            "## 2. Directly Extracted Source Findings (Verified Facts)",
        ]
        for idx, diff in enumerate(extracted_differences, 1):
            md_lines.append(f"### 2.{idx} Section: {diff['section_title']} ({diff['change_type']})")
            if diff.get("baseline_excerpt"):
                md_lines.append(f"- **Previous / Baseline ({diff['baseline_citation']})**: {diff['baseline_excerpt']}")
            if diff.get("updated_excerpt"):
                md_lines.append(f"- **Current / Updated ({diff['updated_citation']})**: {diff['updated_excerpt']}")
            if diff.get("quantitative_shifts"):
                md_lines.append(f"- **Detected Quantitative Shift**: `{diff['quantitative_shifts']}`")
            md_lines.append("")

        md_lines.append("## 3. Model-Synthesized Operational Impact & Risk Analysis")
        for imp in operational_impacts:
            md_lines.append(f"- **[{imp['risk_level']} IMPACT — {imp['section']}]**: {imp['impact_analysis']} (Refs: {', '.join(imp['supporting_citations'])})")

        md_lines.append("\n## 4. Verified Source Reference Table")
        for ref in source_references:
            md_lines.append(f"- `{ref['citation_key']}` — **{ref['document_title']}** (v{ref['version']}, Page {ref['page']}, Section: {ref['section']})")

        markdown_report = "\n".join(md_lines)
        self.audit.log_event(
            organization_id=ctx.organization_id,
            actor_user_id=ctx.user_id,
            event_type="DOCUMENT_COMPARISON_GENERATED",
            resource_type="report",
            resource_id=f"{doc_a_id}_vs_{doc_b_id}",
            action="compare_documents",
            metadata={"differences_count": len(extracted_differences)},
        )
        return {
            "report_id": new_id("rep"),
            "title": report_title,
            "baseline_document": {"id": doc_a_id, "title": doc_a["title"], "version": ver_a},
            "target_document": {"id": doc_b_id, "title": doc_b["title"], "version": ver_b},
            "directly_extracted_differences": extracted_differences,
            "operational_impact_analysis": operational_impacts,
            "source_references": source_references,
            "markdown_export": markdown_report,
            "created_at": utc_now_iso(),
        }
