"""Main chain-of-thought processor for Slack message analysis"""

import time
from datetime import datetime
from typing import Optional

from .processors import OpenAIProcessor
from .schemas import ProcessingContext, ProcessingStep, AnalysisResult


class ChainProcessor:
    """
    Main chain-of-thought processor that orchestrates LLM analysis of Slack messages.

    Processing steps:
    1. Process - Generate AI summary of messages
    (Future: Can add more steps like sentiment analysis, entity extraction, etc.)
    """

    def __init__(self, openai_api_key: str):
        """Initialize chain processor

        Args:
            openai_api_key: OpenAI API key for LLM processing
        """
        self.openai_processor = OpenAIProcessor(openai_api_key)

    def analyze_messages(
        self,
        message_content: str,
        channel_name: str,
        date_range: str,
        model: str = "gpt-5",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        stream: bool = True,
        reasoning_effort: str = "medium",
        view_type: str = "single_channel",
        channels: list = None
    ) -> AnalysisResult:
        """
        Run the complete chain-of-thought analysis on Slack messages

        Args:
            message_content: Formatted message content from view command
            channel_name: Name of the Slack channel or user
            date_range: Date range of messages
            model: OpenAI model to use (gpt-4o or gpt-5)
            temperature: Sampling temperature (not used for GPT-5)
            max_tokens: Maximum tokens in response (not used for GPT-5)
            stream: Whether to stream the response (not supported by GPT-5)
            reasoning_effort: Reasoning effort for GPT-5 (low, medium, high)
            view_type: Type of view ("single_channel", "multi_channel", "user_timeline")
            channels: List of channel names (for multi-channel and user timeline views)

        Returns:
            Complete analysis result with summary and metrics
        """
        start_time = datetime.now()

        # Initialize processing context
        context = ProcessingContext(
            channel_name=channel_name,
            date_range=date_range,
            message_content=message_content,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens
        )

        # Step 1: Process messages with LLM
        self._step_1_process_messages(
            context,
            stream=stream,
            reasoning_effort=reasoning_effort,
            view_type=view_type,
            channels=channels
        )

        # Calculate total time
        total_time = (datetime.now() - start_time).total_seconds()

        # Create final result
        result = AnalysisResult(
            channel_name=context.channel_name,
            date_range=context.date_range,
            summary=context.summary or "",
            processing_steps=context.processing_steps,
            total_processing_time=total_time,
            model_used=context.model
        )

        return result

    def _step_1_process_messages(
        self,
        context: ProcessingContext,
        stream: bool = True,
        reasoning_effort: str = "medium",
        view_type: str = "single_channel",
        channels: list = None
    ) -> None:
        """
        Step 1: Process messages with LLM to generate summary

        Args:
            context: Processing context
            stream: Whether to stream the response
            reasoning_effort: Reasoning effort for GPT-5 (low, medium, high)
            view_type: Type of view ("single_channel", "multi_channel", "user_timeline")
            channels: List of channel names (for multi-channel and user timeline views)
        """
        step_start = time.time()

        try:
            # Estimate input size
            input_size = self.openai_processor.estimate_tokens(context.message_content)

            # Generate summary
            summary_chunks = []
            for chunk in self.openai_processor.generate_summary(
                message_content=context.message_content,
                channel_name=context.channel_name,
                date_range=context.date_range,
                model=context.model,
                temperature=context.temperature,
                max_tokens=context.max_tokens,
                stream=stream,
                reasoning_effort=reasoning_effort,
                view_type=view_type,
                channels=channels
            ):
                summary_chunks.append(chunk)

            context.summary = "".join(summary_chunks)
            duration = time.time() - step_start

            # Record processing step
            output_size = self.openai_processor.estimate_tokens(context.summary)
            context.processing_steps.append(
                ProcessingStep(
                    step_name="process_messages",
                    input_data=f"Messages (~{input_size} tokens)",
                    output_data=f"Summary (~{output_size} tokens)",
                    processing_time=duration,
                    success=True
                )
            )

        except Exception as e:
            duration = time.time() - step_start
            context.processing_steps.append(
                ProcessingStep(
                    step_name="process_messages",
                    input_data=f"Messages",
                    output_data="",
                    processing_time=duration,
                    success=False,
                    error_message=str(e)
                )
            )
            raise Exception(f"Failed to process messages: {e}")
