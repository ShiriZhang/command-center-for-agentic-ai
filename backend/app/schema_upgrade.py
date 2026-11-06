"""
Schema Upgrade and Compatibility Module.
Provides explicit database schema migration from Assignment 1B to Assignment 2 (Orchestration),
compatible with both SQLite and PostgreSQL without external migration dependencies.
CSCI-GA.2630 Assignment 2
"""

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Set
from uuid import uuid4
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine, Connection


REQUIRED_STAGE2_RUN_COLUMNS: Dict[str, str] = {
    "run_uuid": "VARCHAR(36)",
    "protocol_version": "INTEGER DEFAULT 1",  # Existing legacy rows default to protocol 1
    "reset_generation": "INTEGER DEFAULT 0",
    "is_baseline_eligible": "BOOLEAN DEFAULT FALSE",
    "researcher_status": "VARCHAR(50)",
    "verifier_status": "VARCHAR(50)",
    "researcher_error": "TEXT",
    "verifier_error": "TEXT",
    "researcher_request_id": "VARCHAR(36)",
    "verifier_request_id": "VARCHAR(36)",
    "reserved_steps": "INTEGER DEFAULT 0",
    "reserved_fetches": "INTEGER DEFAULT 0",
    "reserved_tokens": "INTEGER DEFAULT 0",
    "measured_steps": "INTEGER DEFAULT 0",
    "measured_fetches": "INTEGER DEFAULT 0",
    "measured_tokens": "INTEGER DEFAULT 0",
    "charged_steps": "INTEGER DEFAULT 0",
    "charged_fetches": "INTEGER DEFAULT 0",
    "charged_tokens": "INTEGER DEFAULT 0",
    "stale_source_run_id": "INTEGER",
    "stale_source_run_uuid": "VARCHAR(36)",
}


@contextmanager
def _connection_context(engine_or_connection: Any) -> Iterator[Connection]:
    """Provides a managed connection across Engine or existing Connection."""
    if isinstance(engine_or_connection, Engine):
        with engine_or_connection.connect() as conn:
            yield conn
    else:
        yield engine_or_connection


def check_schema_compatibility(engine_or_connection: Any) -> Dict[str, Any]:
    """
    Inspects database tables and columns to verify if Stage 2 schema requirements are met.
    """
    inspector = inspect(engine_or_connection)
    existing_tables: Set[str] = set(inspector.get_table_names())

    required_tables = {"users", "tracker_runs", "tracker_articles", "tracker_developments", "tracker_claims"}
    missing_tables = list(required_tables - existing_tables)

    missing_columns: Dict[str, List[str]] = {}
    if "tracker_runs" in existing_tables:
        existing_cols = {col["name"] for col in inspector.get_columns("tracker_runs")}
        missing_run_cols = [col for col in REQUIRED_STAGE2_RUN_COLUMNS if col not in existing_cols]
        if missing_run_cols:
            missing_columns["tracker_runs"] = missing_run_cols

    is_compatible = len(missing_tables) == 0 and len(missing_columns) == 0
    return {
        "compatible": is_compatible,
        "missing_tables": missing_tables,
        "missing_columns": missing_columns,
    }


def upgrade_schema(engine_or_connection: Any) -> Dict[str, Any]:
    """
    Applies explicit schema upgrades using native SQL ALTER TABLE / CREATE TABLE DDL.
    Labels existing runs as legacy (protocol_version = 1) and assigns valid run_uuids.
    """
    added_columns: List[str] = []
    created_tables: List[str] = []
    legacy_rows_marked: int = 0

    with _connection_context(engine_or_connection) as conn:
        inspector = inspect(conn)
        existing_tables: Set[str] = set(inspector.get_table_names())

        # 1. Upgrade tracker_runs columns if table exists
        if "tracker_runs" in existing_tables:
            existing_cols = {col["name"] for col in inspector.get_columns("tracker_runs")}
            had_protocol_col = "protocol_version" in existing_cols

            for col_name, col_type in REQUIRED_STAGE2_RUN_COLUMNS.items():
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE tracker_runs ADD COLUMN {col_name} {col_type}"))
                    added_columns.append(f"tracker_runs.{col_name}")

            # 2. Mark legacy rows: protocol_version = 1, assign run_uuid if missing
            if not had_protocol_col:
                legacy_rows_marked = conn.execute(text("SELECT count(*) FROM tracker_runs WHERE protocol_version = 1")).scalar() or 0
            else:
                rows_to_update = conn.execute(
                    text("SELECT id FROM tracker_runs WHERE protocol_version IS NULL OR protocol_version = 0")
                ).mappings().all()
                for row in rows_to_update:
                    conn.execute(text("UPDATE tracker_runs SET protocol_version = 1 WHERE id = :id"), {"id": row["id"]})
                    legacy_rows_marked += 1

            null_uuid_rows = conn.execute(
                text("SELECT id FROM tracker_runs WHERE run_uuid IS NULL OR run_uuid = ''")
            ).mappings().all()
            for r in null_uuid_rows:
                conn.execute(
                    text("UPDATE tracker_runs SET run_uuid = :uuid WHERE id = :id"),
                    {"uuid": str(uuid4()), "id": r["id"]}
                )

            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tracker_runs_run_uuid ON tracker_runs(run_uuid)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tracker_runs_protocol_version ON tracker_runs(protocol_version)"))
            except Exception:
                pass

        # 3. Create tracker_claims table if not exists
        if "tracker_claims" not in existing_tables:
            dialect = conn.dialect.name
            id_col_type = "SERIAL PRIMARY KEY" if dialect == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"
            create_claims_sql = f"""
            CREATE TABLE tracker_claims (
                id {id_col_type},
                run_id INTEGER NOT NULL REFERENCES tracker_runs(id) ON DELETE CASCADE,
                development_id INTEGER NOT NULL REFERENCES tracker_developments(id) ON DELETE CASCADE,
                claim_id VARCHAR(255) NOT NULL,
                text TEXT NOT NULL,
                source_url VARCHAR(1024) NOT NULL,
                verdict VARCHAR(50) NOT NULL DEFAULT 'unverified',
                evidence TEXT,
                created_at TIMESTAMP NOT NULL,
                CONSTRAINT uq_tracker_claims_run_claim UNIQUE (run_id, claim_id)
            )
            """
            conn.execute(text(create_claims_sql))
            try:
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tracker_claims_run_id ON tracker_claims(run_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tracker_claims_development_id ON tracker_claims(development_id)"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tracker_claims_claim_id ON tracker_claims(claim_id)"))
            except Exception:
                pass
            created_tables.append("tracker_claims")

        conn.commit()

    return {
        "added_columns": added_columns,
        "created_tables": created_tables,
        "legacy_rows_marked": legacy_rows_marked,
    }


def check_rollback_compatibility(engine_or_connection: Any) -> Dict[str, Any]:
    """
    Verifies that legacy Assignment 1B queries execute successfully on the upgraded database.
    """
    with _connection_context(engine_or_connection) as conn:
        try:
            user_row = conn.execute(text("SELECT id, username, email FROM users LIMIT 1")).mappings().first()
            run_row = conn.execute(
                text("SELECT id, user_id, run_number, topic, target_k, status, step_count, fetch_count, tokens_spent FROM tracker_runs LIMIT 1")
            ).mappings().first()

            can_read = user_row is not None and run_row is not None
            return {
                "compatible": True,
                "can_read_legacy_runs": can_read,
            }
        except Exception as e:
            return {
                "compatible": False,
                "can_read_legacy_runs": False,
                "error": str(e),
            }
