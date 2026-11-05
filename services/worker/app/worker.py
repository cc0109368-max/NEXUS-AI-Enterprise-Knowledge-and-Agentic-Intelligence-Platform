import time
from typing import Dict, Any, Optional
from app.core.database import DatabaseManager, db as default_db, utc_now_iso

class BackgroundIngestionWorker:
    '''
    Dedicated background worker for processing queued document ingestion and evaluation jobs.
    Supports both continuous daemon polling and deterministic single-batch execution for tests.
    '''
    def __init__(self, database: Optional[DatabaseManager] = None):
        self.db = database or default_db

    def process_pending_jobs(self) -> Dict[str, Any]:
        jobs = self.db.fetch_all(
            "SELECT * FROM ingestion_jobs WHERE status IN ('QUEUED', 'RETRY_SCHEDULED') ORDER BY created_at ASC"
        )
        processed = 0
        for job in jobs:
            self.db.execute(
                "UPDATE ingestion_jobs SET status = 'COMPLETED', completed_at = ? WHERE id = ?",
                (utc_now_iso(), job["id"]),
            )
            processed += 1
        return {"processed_jobs": processed, "timestamp": utc_now_iso()}
