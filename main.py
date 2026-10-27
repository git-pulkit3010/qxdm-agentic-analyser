import argparse
import logging
from pathlib import Path
from src.database import initialize_schema
from src.ingestor import ingest_file
from src.models import SplitterConfig

# Setup clean logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def main():
    parser = argparse.ArgumentParser(description="QXDM Raw Block Ingestor")
    parser.add_argument("--file", required=True, help="Path to the QXDM log file")
    parser.add_argument("--db", default="qxdm_logs.db", help="Path to the SQLite database")
    parser.add_argument("--test-id", required=True, help="Unique ID for this test run")
    args = parser.parse_args()

    # 1. Initialize DB Schema (WAL mode, FTS5, Tables)
    initialize_schema(args.db)

    # 2. Load Config (Using defaults for now, Agent will generate this later)
    config = SplitterConfig()

    # 3. Run Ingestion
    final_seq = ingest_file(args.file, args.test_id, config, args.db)
    
    logging.info(f"✅ Ingestion complete. Total blocks indexed up to sequence {final_seq}.")

if __name__ == "__main__":
    main()