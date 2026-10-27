import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from src.analyst_agent import run_analysis

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv()

if __name__ == "__main__":
    DB_PATH = "qxdm_logs.db"
    TEST_ID = "TEST_RUN_001"
    
    # Use the same model logic as config_agent.py
    MODEL = os.getenv("ANALYST_MODEL", "openrouter/deepseek/deepseek-v4.1-flash-1017")
    
    print(f"🚀 Launching Analyst Agent on DB: {DB_PATH}, Test ID: {TEST_ID}")
    run_analysis(DB_PATH, TEST_ID, model=MODEL)