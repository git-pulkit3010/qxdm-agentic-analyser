"""
Analyst Agent Tools.
Python functions exposed to the LLM to query the Universal Log Store.
"""
import sqlite3
import json
import re
from pathlib import Path
from src.database import get_db_connection

def _add_regex_support(conn: sqlite3.Connection):
    """Adds native REGEXP support to the SQLite connection."""
    def regexp(expr, item):
        if not item: return False
        reg = re.compile(expr, re.IGNORECASE)
        return reg.search(item) is not None
    conn.create_function("REGEXP", 2, regexp)

def search_blocks(db_path: str, query: str, limit: int = 20, test_id: str = None) -> str:
    """Searches the FTS5 index for keywords (e.g., 'RRC Release' or 'Cause=22'). Returns a JSON string."""
    conn = get_db_connection(db_path)
    sql = """
        SELECT b.global_sequence_id, b.timestamp_raw, b.msg_code, b.raw_text
        FROM log_blocks_fts fts
        JOIN log_blocks b ON b.id = fts.rowid
        WHERE log_blocks_fts MATCH ?
    """
    params = [query]
    if test_id:
        sql += " AND b.test_id = ?"
        params.append(test_id)
    sql += " ORDER BY b.global_sequence_id ASC LIMIT ?"
    params.append(limit)
    
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    
    results = [
        {"sequence_id": r[0], "timestamp": r[1], "msg_code": r[2], "raw_text": r[3]} 
        for r in rows
    ]
    return json.dumps(results, indent=2)

def get_block_context(db_path: str, sequence_id: int, window: int = 5, test_id: str = None) -> str:
    """Gets the blocks surrounding a specific sequence ID to read the context. Returns a JSON string."""
    conn = get_db_connection(db_path)
    sql = """
        SELECT global_sequence_id, timestamp_raw, msg_code, raw_text
        FROM log_blocks
        WHERE global_sequence_id BETWEEN ? AND ?
    """
    params = [sequence_id - window, sequence_id + window]
    if test_id:
        sql += " AND test_id = ?"
        params.append(test_id)
    sql += " ORDER BY global_sequence_id ASC"
    
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    
    results = [
        {"sequence_id": r[0], "timestamp": r[1], "msg_code": r[2], "raw_text": r[3]} 
        for r in rows
    ]
    return json.dumps(results, indent=2)

def count_pattern(db_path: str, regex_pattern: str, test_id: str = None) -> str:
    """Counts how many blocks match a specific regex pattern. Returns a JSON string."""
    conn = get_db_connection(db_path)
    _add_regex_support(conn)
    sql = "SELECT COUNT(*) FROM log_blocks WHERE raw_text REGEXP ?"
    params = [regex_pattern]
    if test_id:
        sql += " AND test_id = ?"
        params.append(test_id)
    count = conn.execute(sql, params).fetchone()[0]
    conn.close()
    return json.dumps({"count": count})

def save_analysis(db_path: str, test_id: str, verdict: str, summary: str, findings: str) -> str:
    """Saves the Analyst Agent's final RCA report to the database. Returns a JSON string."""
    conn = get_db_connection(db_path)
    conn.execute("""
        INSERT OR REPLACE INTO test_run_analysis 
        (test_id, verdict, executive_summary, findings_json)
        VALUES (?, ?, ?, ?)
    """, (test_id, verdict, summary, findings))
    
    conn.execute("UPDATE test_runs SET status = 'ANALYZED' WHERE test_id = ?", (test_id,))
    conn.commit()
    conn.close()
    return json.dumps({"status": "success", "message": f"Analysis for {test_id} saved to database."})