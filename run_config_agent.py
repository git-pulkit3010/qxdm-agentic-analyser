"""
Runner script for the Configurator Agent.
Analyzes a sample QXDM log file to deduce block boundaries and timestamp schema,
saving the result to config/splitter_config.json.
"""
import sys
from pathlib import Path
from src.config_agent import generate_config_from_log

if __name__ == "__main__":
    # Point this to your actual log file in the data/ folder
    log_file = Path("data/UE23_TCP_UDP_UL_75_01-11.06-36-49-875.txt")
    
    if not log_file.exists():
        print(f"❌ Error: Log file not found at '{log_file}'. Please check the path.")
        sys.exit(1)

    print(f"📄 Analyzing log file: {log_file}")
    try:
        config = generate_config_from_log(
            log_file_path=log_file,
            model="deepseek/deepseek-v4.1-flash-1017"
        )
        print("\n🎉 Configuration generation succeeded!")
        print(f"   • Block Start Regex: {config.block_start_regex}")
        print(f"   • Timestamp Regex:   {config.timestamp_regex}")
        print(f"   • Strptime Format:   {config.strptime_format}")
    except ValueError as e:
        print(f"\n❌ Configuration Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected Error: {e}")
        sys.exit(1)
