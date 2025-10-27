"""Data schemas for LLM processing pipeline"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional


@dataclass
class ProcessingStep:
    """Record of a single processing step in the pipeline"""
    step_name: str
    input_data: str
    output_data: str
    processing_time: float
    success: bool
    error_message: Optional[str] = None


@dataclass
class ProcessingContext:
    """Context that flows through the processing pipeline"""

    # Input data
    channel_name: str
    date_range: str
    message_content: str

    # Processing configuration
    model: str = "gpt-5"  # Default model
    temperature: float = 0.7  # Not used for gpt-5
    max_tokens: int = 4000  # Not used for gpt-5

    # Processing results
    summary: Optional[str] = None
    processing_steps: List[ProcessingStep] = field(default_factory=list)

    # Metadata
    created_at: datetime = field(default_factory=datetime.now)


@dataclass
class AnalysisResult:
    """Complete result of the LLM processing pipeline"""

    # Input metadata
    channel_name: str
    date_range: str

    # Processing results
    summary: str

    # Processing metrics
    processing_steps: List[ProcessingStep]
    total_processing_time: float

    # Metadata
    model_used: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization"""
        return {
            "channel_name": self.channel_name,
            "date_range": self.date_range,
            "summary": self.summary,
            "model_used": self.model_used,
            "total_processing_time": self.total_processing_time,
            "timestamp": self.timestamp.isoformat(),
            "processing_steps": [
                {
                    "step_name": step.step_name,
                    "input_data": step.input_data,
                    "output_data": step.output_data,
                    "processing_time": step.processing_time,
                    "success": step.success,
                    "error_message": step.error_message,
                }
                for step in self.processing_steps
            ],
        }
