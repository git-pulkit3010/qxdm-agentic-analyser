"""
Analyst Agent (LLM).
Connects to the SQLite database, searches raw logs, and generates RCA reports.
"""
import os
import json
import litellm
from pathlib import Path
from dotenv import load_dotenv
from src import tools

load_dotenv()

# Define the tools for LiteLLM (OpenAI-compatible function calling schema)
tool_definitions = [
    {
        "type": "function",
        "function": {
            "name": "search_blocks",
            "description": "Searches the log database using Full-Text Search (FTS5). Use keywords like 'RRC Release', 'Cause=22', 'Congestion', '0x1FE7'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "db_path": {"type": "string", "description": "Path to the SQLite database."},
                    "query": {"type": "string", "description": "The FTS5 search query."},
                    "limit": {"type": "integer", "description": "Max results to return.", "default": 20},
                    "test_id": {"type": "string", "description": "The test run ID.", "default": None}
                },
                "required": ["db_path", "query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_block_context",
            "description": "Retrieves the raw log blocks immediately before and after a specific sequence_id to understand the context of an event.",
            "parameters": {
                "type": "object",
                "properties": {
                    "db_path": {"type": "string", "description": "Path to the SQLite database."},
                    "sequence_id": {"type": "integer", "description": "The global_sequence_id of the target block."},
                    "window": {"type": "integer", "description": "Number of blocks before and after to retrieve.", "default": 5},
                    "test_id": {"type": "string", "description": "The test run ID.", "default": None}
                },
                "required": ["db_path", "sequence_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "count_pattern",
            "description": "Counts the total number of log blocks matching a specific Python regex pattern. Useful for quantifying how often an error occurs.",
            "parameters": {
                "type": "object",
                "properties": {
                    "db_path": {"type": "string", "description": "Path to the SQLite database."},
                    "regex_pattern": {"type": "string", "description": "The Python regex pattern to match against raw_text."},
                    "test_id": {"type": "string", "description": "The test run ID.", "default": None}
                },
                "required": ["db_path", "regex_pattern"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "save_analysis",
            "description": "Saves the final Root Cause Analysis (RCA) verdict, summary, and structured findings to the database. Call this when the analysis is complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "db_path": {"type": "string", "description": "Path to the SQLite database."},
                    "test_id": {"type": "string", "description": "The test run ID."},
                    "verdict": {"type": "string", "description": "Overall health: PASS, DEGRADED, or CRITICAL_FAILURE.", "enum": ["PASS", "DEGRADED", "CRITICAL_FAILURE"]},
                    "summary": {"type": "string", "description": "A concise executive summary of the root cause."},
                    "findings": {"type": "string", "description": "A JSON string containing detailed structured findings (e.g., counts, specific error codes, timestamps)."}
                },
                "required": ["db_path", "test_id", "verdict", "summary", "findings"]
            }
        }
    }
]

# Map function names to actual python functions
tool_map = {
    "search_blocks": tools.search_blocks,
    "get_block_context": tools.get_block_context,
    "count_pattern": tools.count_pattern,
    "save_analysis": tools.save_analysis
}

def run_analysis(db_path: str, test_id: str, model: str = "openrouter/deepseek/deepseek-v4.1-flash-1017"):
    print(f"🕵️ Starting Analyst Agent for test_id: {test_id}...")
    
    # Resolve API keys and URLs (matching your config_agent.py logic)
    resolved_api_key = (
        os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OR_API_KEY")
        or os.getenv("OPENAI_API_KEY")
    )
    if not resolved_api_key:
        raise ValueError("No API key found. Set OPENROUTER_API_KEY or OPENAI_API_KEY in .env")
        
    is_openrouter = model.startswith("openrouter/")
    if is_openrouter and not os.getenv("OPENROUTER_API_KEY"):
        os.environ["OPENROUTER_API_KEY"] = resolved_api_key
        
    resolved_base_url = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1") if is_openrouter else None
    
    headers = None
    if is_openrouter:
        headers = {
            "HTTP-Referer": os.getenv("OR_SITE_URL", "https://github.com/compnova/qxdm_agentic_analyst"),
            "X-Title": os.getenv("OR_APP_NAME", "QXDM Agentic Analyst"),
        }

    system_prompt = f"""You are an expert Telecom Root Cause Analysis (RCA) Agent. 
You have access to a SQLite database containing raw QXDM log blocks for test run '{test_id}'.
Your goal is to investigate the logs, identify any network anomalies (e.g., NAS Registration Rejects, RRC Connection Releases, missing back-off timers like T3346, poor RF coverage), and determine the root cause.

Investigation Steps:
1. Search for critical failure keywords (e.g., "Reject", "Release", "Failure", "Cause=22", "Congestion").
2. Read the context around those failures using get_block_context to understand the sequence of events.
3. Count how many times specific errors occur to determine if it's an isolated incident or a loop.
4. Once you have identified the root cause, use the `save_analysis` tool to write your final report to the database.

Be thorough but concise in your reasoning. Always output your final verdict using `save_analysis`.
"""

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Please analyze the logs in database '{db_path}' for test_id '{test_id}'."}
    ]

    # ReAct Loop (Max 10 iterations to prevent infinite loops)
    for i in range(10):
        print(f"\n🔄 Agent iteration {i+1}...")
        
        response = litellm.completion(
            model=model,
            messages=messages,
            tools=tool_definitions,
            tool_choice="auto",
            api_key=resolved_api_key,
            base_url=resolved_base_url,
            headers=headers
        )
        
        response_message = response.choices[0].message
        
        # Append the agent's response to the conversation
        messages.append(response_message)
        
        # Check if the agent wants to call a tool
        if response_message.tool_calls:
            for tool_call in response_message.tool_calls:
                func_name = tool_call.function.name
                func_args = json.loads(tool_call.function.arguments)
                
                print(f"🛠️ Agent calling tool: {func_name}({func_args})")
                
                # Execute the tool
                if func_name in tool_map:
                    try:
                        result = tool_map[func_name](**func_args)
                    except Exception as e:
                        result = json.dumps({"error": str(e)})
                else:
                    result = json.dumps({"error": f"Unknown tool: {func_name}"})
                    
                # Append the tool result to the conversation
                messages.append({
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": func_name,
                    "content": result
                })
        else:
            # No tool calls, the agent is done
            print("\n✅ Agent finished reasoning.")
            print("Final Message:", response_message.content)
            break