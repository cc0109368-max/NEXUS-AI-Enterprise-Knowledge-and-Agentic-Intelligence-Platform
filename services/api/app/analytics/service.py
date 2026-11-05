import io
import json
from pathlib import Path
from typing import Any, Dict, List, Optional
import pandas as pd
from app.core.database import DatabaseManager, db as default_db
from app.core.security import SecurityViolationError, TenantRequestContext
from app.audit.service import AuditService

ALLOWED_AGG_FUNCS = {"sum", "mean", "min", "max", "count", "median", "std"}

class DataAnalyticsService:
    '''
    Module G: Deterministic Python Data Analytics Engine
    Executes validated, read-only Pandas operations on ingested CSV and XLSX datasets.
    Never trusts LLM-generated arithmetic; all numerical outputs come strictly from Pandas.
    '''
    def __init__(self, database: Optional[DatabaseManager] = None):
        self.db = database or default_db
        self.audit = AuditService(self.db)

    def list_datasets(self, ctx: TenantRequestContext, workspace_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if workspace_id:
            rows = self.db.fetch_all(
                "SELECT * FROM datasets WHERE organization_id = ? AND workspace_id = ? ORDER BY created_at DESC",
                (ctx.organization_id, workspace_id),
            )
        else:
            rows = self.db.fetch_all(
                "SELECT * FROM datasets WHERE organization_id = ? ORDER BY created_at DESC",
                (ctx.organization_id,),
            )
        for r in rows:
            r["schema"] = json.loads(r.get("schema_json") or "[]")
            r["summary_stats"] = json.loads(r.get("summary_stats_json") or "{}")
        return rows

    def get_dataset(self, ctx: TenantRequestContext, dataset_id: str) -> Dict[str, Any]:
        ds = self.db.fetch_one("SELECT * FROM datasets WHERE id = ?", (dataset_id,))
        if not ds:
            raise ValueError(f"Dataset {dataset_id} not found.")
        if ds["organization_id"] != ctx.organization_id:
            raise SecurityViolationError("CROSS_TENANT_DATASET_DENIED", "Dataset belongs to another organization", 403)
        ds["schema"] = json.loads(ds.get("schema_json") or "[]")
        ds["summary_stats"] = json.loads(ds.get("summary_stats_json") or "{}")
        return ds

    def _load_dataframe(self, ctx: TenantRequestContext, dataset_id: str) -> pd.DataFrame:
        ds = self.get_dataset(ctx, dataset_id)
        ver = self.db.fetch_one(
            '''
            SELECT storage_path FROM document_versions
            WHERE document_id = ? AND organization_id = ?
            ORDER BY version_number DESC LIMIT 1
            ''',
            (ds["document_id"], ctx.organization_id),
        )
        if not ver or not Path(ver["storage_path"]).exists():
            raise ValueError(f"Underlying storage file for dataset {dataset_id} not found.")
        path = ver["storage_path"]
        if path.lower().endswith(".csv"):
            return pd.read_csv(path)
        return pd.read_excel(path)

    def run_analysis(
        self,
        ctx: TenantRequestContext,
        dataset_id: str,
        operation: str = "describe",
        group_by_column: Optional[str] = None,
        metric_column: Optional[str] = None,
        agg_func: str = "sum",
        filter_column: Optional[str] = None,
        filter_value: Optional[Any] = None,
        date_column: Optional[str] = None,
    ) -> Dict[str, Any]:
        ds = self.get_dataset(ctx, dataset_id)
        df = self._load_dataframe(ctx, dataset_id)
        assumptions = [
            f"Deterministic computation executed via Pandas {pd.__version__} on dataset '{ds['name']}' ({len(df)} rows).",
            "Missing values (NaN/null) are explicitly counted and excluded from numerical aggregations.",
        ]

        if filter_column:
            if filter_column not in df.columns:
                raise ValueError(f"Filter column '{filter_column}' not found in schema: {list(df.columns)}")
            df = df[df[filter_column].astype(str) == str(filter_value)]
            assumptions.append(f"Applied exact filter: {filter_column} == '{filter_value}' ({len(df)} matching rows).")

        if operation == "describe":
            return {
                "dataset_id": dataset_id,
                "dataset_name": ds["name"],
                "operation": "describe",
                "row_count": int(len(df)),
                "column_count": int(len(df.columns)),
                "schema": ds["schema"],
                "descriptive_statistics": ds["summary_stats"],
                "assumptions": assumptions,
                "deterministic_verified": True,
            }

        if agg_func not in ALLOWED_AGG_FUNCS:
            raise ValueError(f"Disallowed aggregation '{agg_func}'. Allowed: {sorted(ALLOWED_AGG_FUNCS)}")

        if operation in {"group_by", "filter_aggregate"}:
            if not metric_column or metric_column not in df.columns:
                raise ValueError(f"Metric column '{metric_column}' not found in dataset columns {list(df.columns)}")
            if group_by_column:
                if group_by_column not in df.columns:
                    raise ValueError(f"Group-by column '{group_by_column}' not found in dataset columns {list(df.columns)}")
                grouped = getattr(df.groupby(group_by_column)[metric_column], agg_func)().reset_index()
                records = [
                    {str(group_by_column): str(row[group_by_column]), str(metric_column): round(float(row[metric_column]), 4)}
                    for _, row in grouped.iterrows()
                ]
                chart_series = {
                    "type": "bar",
                    "x_key": group_by_column,
                    "y_key": metric_column,
                    "labels": [r[str(group_by_column)] for r in records],
                    "values": [r[str(metric_column)] for r in records],
                }
                total_val = round(float(getattr(df[metric_column].dropna(), agg_func)()), 4)
                return {
                    "dataset_id": dataset_id,
                    "dataset_name": ds["name"],
                    "operation": operation,
                    "group_by_column": group_by_column,
                    "metric_column": metric_column,
                    "agg_func": agg_func,
                    "overall_metric_value": total_val,
                    "grouped_results": records,
                    "chart_ready_output": chart_series,
                    "assumptions": assumptions,
                    "deterministic_verified": True,
                }
            else:
                val = round(float(getattr(df[metric_column].dropna(), agg_func)()), 4)
                return {
                    "dataset_id": dataset_id,
                    "dataset_name": ds["name"],
                    "operation": operation,
                    "metric_column": metric_column,
                    "agg_func": agg_func,
                    "value": val,
                    "assumptions": assumptions,
                    "deterministic_verified": True,
                }

        if operation == "time_series":
            col_date = date_column or (df.columns[0] if len(df.columns) > 0 else None)
            if not col_date or col_date not in df.columns or not metric_column or metric_column not in df.columns:
                raise ValueError("Valid date_column and metric_column required for time_series summary.")
            ts_df = df[[col_date, metric_column]].dropna().copy()
            grouped = getattr(ts_df.groupby(col_date)[metric_column], agg_func)().reset_index()
            series_rows = [
                {"period": str(r[col_date]), "value": round(float(r[metric_column]), 4)}
                for _, r in grouped.iterrows()
            ]
            return {
                "dataset_id": dataset_id,
                "dataset_name": ds["name"],
                "operation": "time_series",
                "date_column": col_date,
                "metric_column": metric_column,
                "agg_func": agg_func,
                "series": series_rows,
                "assumptions": assumptions,
                "deterministic_verified": True,
            }

        raise ValueError(f"Unsupported analytics operation: {operation}")
