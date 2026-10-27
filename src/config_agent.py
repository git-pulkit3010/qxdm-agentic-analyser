"""
Configurator Agent (LLM).
Reads a sample of the raw log, deduces the schema, and generates splitter_config.json.
"""
import os
import re
import sys
import json
import logging
import litellm
from pathlib import Path

# Ensure project root is in sys.path so direct execution works
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
from src.models import SplitterConfig

logger = logging.getLogger(__name__)

# Load API keys and environment variables from .env
load_dotenv()

DEFAULT_MODEL = "openrouter/deepseek/deepseek-v4.1-flash-1017"
DEFAULT_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _extract_json_from_response(raw_text: str) -> dict:
    """
    Safely extract and parse JSON from the LLM output, handling markdown
    fences (```json ... ```) or preamble text.
    """
    text = raw_text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Attempt to extract from markdown code blocks
    if "```" in text:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL | re.IGNORECASE)
        if match:
            fenced_content = match.group(1).strip()
            try:
                return json.loads(fenced_content)
            except json.JSONDecodeError:
                pass

    # Fallback: attempt to extract outermost JSON object { ... }
    match = re.search(r"(\{.*\})", text, re.DOTALL)
    if match:
        return json.loads(match.group(1))

    raise ValueError(f"Could not extract valid JSON from LLM response:\n{raw_text}")


def generate_config_from_log(
    log_file_path: str | Path, 
    output_path: str | Path = "config/splitter_config.json",
    model: str = "deepseek/deepseek-v4.1-flash-1017",
    base_url: str | None = None,
    api_key: str | None = None,
) -> SplitterConfig:
    """
    Deduces log schema using an LLM and outputs a validated SplitterConfig.

    Args:
        log_file_path: Path to the raw QXDM log file.
        output_path: Destination path for the generated splitter_config.json.
        model: Model identifier. Defaults to 'deepseek/deepseek-v4.1-flash-1017' routed via OpenRouter.
        base_url: Optional API base URL override (defaults to OpenRouter's URL for OpenRouter models).
        api_key: Optional API key override (falls back to OPENROUTER_API_KEY, OPENAI_API_KEY, etc.).

    Returns:
        SplitterConfig: Validated Pydantic configuration object.
    """
    log_path = Path(log_file_path)
    if not log_path.is_file():
        raise FileNotFoundError(f"Log file not found: {log_file_path}")

    # Read first 200 lines to give the LLM context
    with open(log_path, 'r', encoding='utf-8', errors='ignore') as f:
        lines = [f.readline() for _ in range(200)]
    snippet = "".join(lines)

    # Normalize model name for OpenRouter:
    # If the user passed "deepseek/deepseek-v4.1-flash-1017" or similar without "openrouter/",
    # prefix it with "openrouter/" so LiteLLM targets OpenRouter rather than native DeepSeek.
    if not model.startswith("openrouter/") and (
        model.startswith("deepseek/") or "deepseek" in model.lower()
    ):
        routed_model = f"openrouter/{model}"
    else:
        routed_model = model

    is_openrouter = routed_model.startswith("openrouter/")

    # Resolve API Key:
    # Checks OPENROUTER_API_KEY, OR_API_KEY, OPENAI_API_KEY, and DEEPSEEK_API_KEY
    # so the user can leave their existing .env variable name as-is.
    resolved_api_key = (
        api_key
        or os.getenv("OPENROUTER_API_KEY")
        or os.getenv("OR_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or os.getenv("DEEPSEEK_API_KEY")
    )

    if not resolved_api_key:
        raise ValueError(
            "No API key found. Please set OPENROUTER_API_KEY (or OPENAI_API_KEY) in your .env file or environment."
        )

    # If key is provided under OPENAI_API_KEY, ensure OPENROUTER_API_KEY is also populated for LiteLLM
    if is_openrouter and not os.getenv("OPENROUTER_API_KEY"):
        os.environ["OPENROUTER_API_KEY"] = resolved_api_key

    # Resolve Base URL:
    # Can be set via parameter, OPENROUTER_BASE_URL, OPENROUTER_API_BASE, OPENAI_BASE_URL,
    # or defaults to OpenRouter's endpoint for OpenRouter models.
    resolved_base_url = (
        base_url
        or os.getenv("OPENROUTER_BASE_URL")
        or os.getenv("OPENROUTER_API_BASE")
        or os.getenv("OPENAI_BASE_URL")
        or (DEFAULT_OPENROUTER_BASE_URL if is_openrouter else None)
    )

    prompt = f"""You are an expert in parsing telecom QXDM logs. 
I need you to analyze the following log snippet and generate a JSON configuration to split it into blocks.

Rules:
1. `block_start_regex`: A regex that matches the start of a new log block (anchored with `^`). Keep it focused on the timestamp pattern at the beginning of the line (e.g. `^\\d{4}\\s+[A-Za-z]{3}\\s+\\d{1,2}\\s+\\d{2}:\\d{2}:\\d{2}\\.\\d{3}`). Do NOT overfit to specific message types or codes that appear later in the line. Use `\\s+` for spaces to handle single/double digit days.
2. `timestamp_regex`: A regex to extract JUST the timestamp string from that first line. Use a capture group `()`.
3. `strptime_format`: The exact Python `datetime.strptime` format string that matches the extracted timestamp. 

Output ONLY valid JSON matching this schema:
{{
  "block_start_regex": "...",
  "timestamp_regex": "...",
  "strptime_format": "..."
}}

Log Snippet:
{snippet}
"""

    headers = None
    if is_openrouter:
        headers = {
            "HTTP-Referer": os.getenv("OR_SITE_URL", "https://github.com/compnova/qxdm_agentic_analyst"),
            "X-Title": os.getenv("OR_APP_NAME", "QXDM Agentic Analyst"),
        }

    print(f"🤖 Asking Configurator Agent ({routed_model}) to deduce log schema...")
    if resolved_base_url:
        print(f"🌐 Base URL: {resolved_base_url}")

    response = litellm.completion(
        model=routed_model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        api_key=resolved_api_key,
        base_url=resolved_base_url,
        headers=headers,
    )

    raw_json = response.choices[0].message.content
    print("✅ Agent returned config:")
    print(raw_json)

    # Validate with Pydantic
    config_dict = _extract_json_from_response(raw_json)
    config = SplitterConfig(**config_dict)

    # Save to file
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(config.model_dump_json(indent=2))

    print(f"💾 Saved validated config to {output_path}")
    return config


if __name__ == "__main__":
    sample_log = PROJECT_ROOT / "data" / "UE23_TCP_UDP_UL_75_01-11.06-36-49-875.txt"
    if sample_log.exists():
        print(f"📄 Running Configurator Agent on sample log: {sample_log}")
        generate_config_from_log(sample_log)
    else:
        print(f"ℹ️ Configurator agent module ready. Pass a log file to generate_config_from_log().")

