"""
Raw Block Ingestor (The Dumb Pipe).
Streams the file line-by-line, splits blocks using config, 
parses timestamps to epoch, and writes to SQLite.
"""
import re
import logging
import datetime
from pathlib import Path
from src.models import SplitterConfig
from src.database import get_db_connection

logger = logging.getLogger(__name__)

BATCH_SIZE = 5000 # Flush to DB every 5000 blocks to save RAM

def ingest_file(
    file_path: str | Path, 
    test_id: str, 
    config: SplitterConfig, 
    db_path: str | Path,
    start_sequence: int = 0
) -> int:
    """
    Streams a QXDM log file and inserts blocks into the database.
    Returns the final sequence_id so the next file can continue seamlessly.
    """
    block_start_re = re.compile(config.block_start_regex)
    timestamp_re = re.compile(config.timestamp_regex)
    
    conn = get_db_connection(db_path)
    conn.isolation_level = None # Manual transaction management for speed
    c = conn.cursor()
    
    # Mark test run as indexing
    c.execute("INSERT OR REPLACE INTO test_runs (test_id, status) VALUES (?, 'INDEXING')", (test_id,))
    conn.commit()

    # Get last sequence ID if appending to an existing test run
    if start_sequence > 0:
        seq = start_sequence
    else:
        row = c.execute("SELECT MAX(global_sequence_id) FROM log_blocks WHERE test_id = ?", (test_id,)).fetchone()
        seq = (row[0] if row and row[0] else 0) + 1

    logger.info(f"Ingesting {file_path} starting at sequence {seq}...")

    batch_buffer = []
    current_block_lines = []
    block_count = 0

    def flush_batch():
        nonlocal batch_buffer
        if batch_buffer:
            c.executemany(
                "INSERT INTO log_blocks (test_id, global_sequence_id, timestamp_raw, timestamp_epoch_ms, msg_code, raw_text) VALUES (?, ?, ?, ?, ?, ?)",
                batch_buffer
            )
            conn.commit()
            batch_buffer = []

    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                # Detect start of new block
                if block_start_re.match(line):
                    # We found a new header, flush previous block
                    if current_block_lines:
                        full_text = "\n".join(current_block_lines)
                        
                        # Try to parse timestamp
                        ts_match = timestamp_re.search(current_block_lines[0])
                        ts_raw = None
                        ts_epoch = None
                        msg_code = None

                        if ts_match:
                            ts_raw = ts_match.group(1)
                            try:
                                dt = datetime.datetime.strptime(ts_raw, config.strptime_format)
                                ts_epoch = int(dt.timestamp() * 1000)
                            except ValueError as e:
                                logger.warning(f"Timestamp parse failed for seq {seq}: {e}")
                        
                        # Try to extract msg_code (e.g., 0x1544) from the first few lines
                        code_match = re.search(r'0[xX][0-9A-Fa-f]{4}', "\n".join(current_block_lines[:3]))
                        if code_match:
                            msg_code = code_match.group(0).upper()

                        batch_buffer.append((test_id, seq, ts_raw, ts_epoch, msg_code, full_text))
                        seq += 1
                        block_count += 1
                        
                        if len(batch_buffer) >= BATCH_SIZE:
                            flush_batch()

                    # Start new block
                    current_block_lines = [line.strip()]
                else:
                    # Continuation of current block
                    if line.strip():
                        current_block_lines.append(line.strip())

            # Flush the very last block in the file
            if current_block_lines:
                full_text = "\n".join(current_block_lines)
                ts_match = timestamp_re.search(current_block_lines[0])
                ts_raw = ts_match.group(1) if ts_match else None
                ts_epoch = None
                msg_code = None

                if ts_raw:
                    try:
                        dt = datetime.datetime.strptime(ts_raw, config.strptime_format)
                        ts_epoch = int(dt.timestamp() * 1000)
                    except ValueError:
                        pass
                
                code_match = re.search(r'0[xX][0-9A-Fa-f]{4}', "\n".join(current_block_lines[:3]))
                if code_match:
                    msg_code = code_match.group(0).upper()

                batch_buffer.append((test_id, seq, ts_raw, ts_epoch, msg_code, full_text))
                flush_batch()

    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        c.execute("UPDATE test_runs SET status = 'FAILED' WHERE test_id = ?", (test_id,))
        conn.commit()
        raise e
    finally:
        conn.close()

    logger.info(f"Ingested {block_count} blocks. Last sequence: {seq}")
    
    # Mark run as ready for analysis
    conn = get_db_connection(db_path)
    conn.execute("UPDATE test_runs SET status = 'READY' WHERE test_id = ?", (test_id,))
    conn.commit()
    conn.close()

    return seq