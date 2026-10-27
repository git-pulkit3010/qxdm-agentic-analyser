"""
The Orchestrator (Traffic Cop).
Watches incoming folder, stabilizes files, groups chunks, and triggers the pipeline.
"""
import re
import time
import shutil
import logging
from pathlib import Path
from collections import defaultdict

from src.models import SplitterConfig
from src.database import initialize_schema
from src.ingestor import ingest_chunks
from src.config_agent import generate_config_from_log
from src.analyst_agent import run_analysis

logger = logging.getLogger(__name__)

# Chunk markers identify the ORDER of the pieces belonging to one test run.
#   TEST_RUN_001_A.txt / TEST_RUN_001_B.txt      -> run "TEST_RUN_001", parts A, B
#   RUN123_chunk_001.txt / RUN123_chunk_002.txt  -> run "RUN123", parts 1, 2
#   run_001.txt / test_session_02.txt / log_chunk_3.txt -> run "run" / "test" / "log"
ALPHA_PART_PATTERN = re.compile(r'^(?P<base>.+?)[-_](?P<part>[A-Za-z]{1,2})$')
NUMERIC_PART_PATTERN = re.compile(
    r'^(?P<base>.+?)[-_]?(?:session|part|chunk|segment|seg|seq)?[-_]?(?P<part>\d{1,5})$',
    re.IGNORECASE
)

def _part_sort_key(part: str) -> tuple[int, int, str]:
    """Orders chunk markers: numeric chunks first, then alphabetical (A, B, ... Z, AA)."""
    if part.isdigit():
        return (0, int(part), '')
    letters = part.upper()
    value = 0
    for ch in letters:
        value = value * 26 + (ord(ch) - ord('A') + 1)
    return (1, value, letters)

def classify_chunks(files: list[Path]) -> dict[str, list[tuple[tuple[int, int, str], Path]]]:
    """Groups files by test_id and sorts each group's chunks by their part marker."""
    groups: dict[str, list[tuple[tuple[int, int, str], Path]]] = defaultdict(list)

    for f in files:
        stem = f.stem
        part = None
        base = None

        # Alphabetic part labels (A, B, ... AA) must be preceded by a separator,
        # otherwise plain file names like "sample.txt" would be mangled.
        match = ALPHA_PART_PATTERN.match(stem)
        if match:
            base = match.group('base')
            part = match.group('part')
        else:
            match = NUMERIC_PART_PATTERN.match(stem)
            if match:
                base = match.group('base')
                part = match.group('part')

        if base is None:
            # No chunk marker: the file is a standalone test run.
            groups[stem].append(((0, 0, ''), f))
            continue

        base = base.strip('-_ ') or stem
        groups[base].append((_part_sort_key(part), f))

    for test_id in groups:
        groups[test_id].sort(key=lambda x: x[0])
    return dict(groups)

def wait_for_stability(file_path: Path, stability_window: int = 3, max_wait: int = 60) -> bool:
    """Waits for file size to stop changing (prevents reading mid-transfer)."""
    last_size = -1
    waited = 0
    while waited < max_wait:
        current_size = file_path.stat().st_size
        if current_size == last_size and current_size > 0:
            return True
        last_size = current_size
        time.sleep(stability_window)
        waited += stability_window
    return False

def process_incoming(
    incoming_dir: str = "data/incoming",
    processed_dir: str = "data/processed",
    db_path: str = "qxdm_logs.db",
    config_path: str = "config/splitter_config.json"
):
    """Main orchestration loop."""
    incoming_path = Path(incoming_dir)
    processed_path = Path(processed_dir)
    incoming_path.mkdir(parents=True, exist_ok=True)
    processed_path.mkdir(parents=True, exist_ok=True)
    
    initialize_schema(db_path)
    
    print(f"👀 Watching {incoming_path} for new logs...")
    
    while True:
        txt_files = list(incoming_path.glob("*.txt"))
        if not txt_files:
            time.sleep(5)
            continue
            
        # 1. Wait for all files to finish transferring
        all_stable = True
        for f in txt_files:
            if not wait_for_stability(f):
                logger.warning(f"File {f.name} is still transferring. Waiting...")
                all_stable = False
                break
                
        if not all_stable:
            time.sleep(5)
            continue
            
        # 2. Group into test runs
        groups = classify_chunks(txt_files)
        
        for test_id, chunks in groups.items():
            chunk_paths = [c[1] for c in chunks]
            print(f"\n🚀 Processing test_id: {test_id} ({len(chunk_paths)} chunks)")
            
            # 3. Ensure Config Exists (Run Configurator Agent if needed)
            cfg_path = Path(config_path)
            if not cfg_path.exists():
                print("⚙️ No config found. Triggering Configurator Agent...")
                config = generate_config_from_log(chunk_paths[0], cfg_path)
            else:
                import json
                with open(cfg_path, 'r') as f:
                    config = SplitterConfig(**json.load(f))
                    
            # 4. Ingest (Stitches boundaries automatically)
            try:
                ingest_chunks(chunk_paths, test_id, config, db_path)
                
                # 5. Analyze (Trigger Analyst Agent)
                print("🕵️ Triggering Analyst Agent...")
                run_analysis(db_path, test_id)
                
                # 6. Archive
                dest_dir = processed_path / test_id
                dest_dir.mkdir(exist_ok=True)
                for cp in chunk_paths:
                    shutil.move(str(cp), str(dest_dir / cp.name))
                print(f"✅ {test_id} complete and archived to {dest_dir}")
                
            except Exception as e:
                logger.error(f"Pipeline failed for {test_id}: {e}")
                # Move to failed folder or leave in incoming for retry