import logging
from src.watcher import process_incoming

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

if __name__ == "__main__":
    # To test this:
    # 1. Create a folder `data/incoming/`
    # 2. Copy your log file into it, but rename it to `TEST_RUN_001.txt` 
    #    (or split it into `TEST_RUN_001.txt` and `TEST_RUN_002.txt`)
    # 3. Run this script.
    process_incoming()