"""
Universal Log Store: SQLite Database Management.
Handles schema creation, WAL mode for concurrency, and FTS5 setup.
"""
import sqlite3
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

def get_db_connection(db_path: str | Path, auto_commit: bool = False) -> sqlite3.Connection:
    """
    Creates a connection with WAL mode and busy timeout enabled.
    This prevents 'database is locked' errors when the dashboard queries 
    the DB while the ingestor is writing to it.
    """
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=30000")
    if auto_commit:
        conn.isolation_level = None # Autocommit mode
    return conn

def initialize_schema(db_path: str | Path):
    """
    Creates the Universal Log Store schema if it doesn't exist.
    Includes the FTS5 virtual table for the Analyst Agent.
    """
    logger.info(f"Initializing schema at {db_path}")
    conn = get_db_connection(db_path)
    try:
        c = conn.cursor()
        
        # 1. Core Metadata Table
        c.execute("""
            CREATE TABLE IF NOT EXISTS test_runs (
                test_id TEXT PRIMARY KEY,
                status TEXT DEFAULT 'INDEXING', -- WAITING, INDEXING, READY, FAILED
                started_at TEXT DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT
            )
        """)

        # 2. Raw Log Blocks Table
        # We use epoch_ms for sorting, raw_text for the Agent.
        c.execute("""
            CREATE TABLE IF NOT EXISTS log_blocks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                test_id TEXT NOT NULL,
                global_sequence_id INTEGER NOT NULL,
                timestamp_raw TEXT, -- Preserved for display
                timestamp_epoch_ms INTEGER, -- Calculated for sorting
                msg_code TEXT, -- Optional quick filter (e.g. 0x1544)
                raw_text TEXT NOT NULL -- The full, untouched block
            )
        """)

        # 3. Indexes for Chronological Ordering
        c.execute("CREATE INDEX IF NOT EXISTS idx_sequence ON log_blocks(test_id, global_sequence_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_epoch ON log_blocks(test_id, timestamp_epoch_ms)")

        # 4. FTS5 Virtual Table (The Agent's Search Engine)
        # We use external content so we only store text once.
        c.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS log_blocks_fts USING fts5(
                raw_text, 
                content='log_blocks', 
                content_rowid='id'
            )
        """)

        # 5. Triggers to keep FTS5 in sync automatically
        c.execute("""
            CREATE TRIGGER IF NOT EXISTS blocks_fts_insert AFTER INSERT ON log_blocks
            BEGIN
                INSERT INTO log_blocks_fts(rowid, raw_text) VALUES (new.id, new.raw_text);
            END;
        """)

        # 6. Analysis Results Table (Where the Analyst Agent writes its findings)
        c.execute("""
            CREATE TABLE IF NOT EXISTS test_run_analysis (
                test_id TEXT PRIMARY KEY,
                verdict TEXT, -- PASS, DEGRADED, CRITICAL_FAILURE
                executive_summary TEXT,
                findings_json TEXT,
                analyzed_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        conn.commit()
        logger.info("Schema initialization complete.")
    except Exception as e:
        conn.rollback()
        logger.error(f"Schema initialization failed: {e}")
        raise e
    finally:
        conn.close()