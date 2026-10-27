"""
Pydantic Models for Configuration and Validation.
Ensures the Configurator Agent (or manual config) provides valid regexes.
"""
import re
from pydantic import BaseModel, Field, model_validator

class SplitterConfig(BaseModel):
    """
    Configuration for how to split raw QXDM text logs into blocks.
    """
    # Regex to identify the START of a new block.
    # Must be simple and robust (e.g. matches the date at the start of a line).
    block_start_regex: str = Field(
        default=r"^\d{4}\s+[A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\.\d{3}",
        description="Regex matching the start of a block header."
    )
    
    # Regex to extract the specific timestamp string from the header.
    # The capture group (1) must contain the parsable date/time.
    timestamp_regex: str = Field(
        default=r"^(\d{4}\s+[A-Za-z]{3}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2}\.\d{3})",
        description="Regex to extract the timestamp from the header line."
    )

    # The format string for strptime.
    strptime_format: str = Field(
        default="%Y %b %d %H:%M:%S.%f",
        description="Python strptime format string for the extracted timestamp."
    )

    @model_validator(mode='after')
    def validate_regexes(self):
        try:
            re.compile(self.block_start_regex)
        except re.error as e:
            raise ValueError(f"Invalid block_start_regex: {e}")
        
        try:
            re.compile(self.timestamp_regex)
        except re.error as e:
            raise ValueError(f"Invalid timestamp_regex: {e}")
            
        return self