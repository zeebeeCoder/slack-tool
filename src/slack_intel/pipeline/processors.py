"""LLM processors for message analysis"""

import time
from typing import Iterator, Optional
from openai import OpenAI


class PromptTemplates:
    """Prompt templates for different processing stages"""

    SUMMARIZE_MESSAGES = """You are analyzing Slack channel messages to provide actionable insights.

Channel: {channel_name}
Date Range: {date_range}

Messages:
{message_content}

Please provide a comprehensive summary that includes:
1. Key topics and discussions
2. Important decisions made
3. Action items or follow-ups mentioned
4. Notable patterns or trends
5. Critical issues or concerns raised

Focus on actionable insights that would help someone quickly understand what happened in this channel."""


class OpenAIProcessor:
    """
    Processes text content using OpenAI's API with streaming support
    """

    def __init__(self, api_key: str):
        """Initialize OpenAI processor

        Args:
            api_key: OpenAI API key
        """
        self.client = OpenAI(api_key=api_key)

    def generate_summary(
        self,
        message_content: str,
        channel_name: str,
        date_range: str,
        model: str = "gpt-5",
        temperature: float = 0.7,
        max_tokens: int = 4000,
        stream: bool = True,
        reasoning_effort: str = "medium"
    ) -> Iterator[str]:
        """
        Generate a summary of Slack messages using OpenAI

        Args:
            message_content: Formatted message content from view command
            channel_name: Name of the Slack channel
            date_range: Date range of messages
            model: OpenAI model to use (default: gpt-4o, or gpt-5)
            temperature: Sampling temperature (not supported by GPT-5)
            max_tokens: Maximum tokens in response (not supported by GPT-5)
            stream: Whether to stream the response (not supported by GPT-5)
            reasoning_effort: Reasoning effort for GPT-5 (low, medium, high)

        Yields:
            Chunks of generated text if streaming, full text otherwise
        """
        prompt = PromptTemplates.SUMMARIZE_MESSAGES.format(
            channel_name=channel_name,
            date_range=date_range,
            message_content=message_content
        )

        try:
            # GPT-5 uses the new Responses API
            if model.startswith("gpt-5") or model == "gpt-5":
                # Build full prompt with system context for GPT-5
                full_prompt = (
                    "You are an AI assistant specialized in analyzing Slack conversations "
                    "and extracting actionable insights.\n\n"
                    f"{prompt}"
                )

                # GPT-5 Responses API - no streaming, no temperature, no max_tokens
                response = self.client.responses.create(
                    model=model,
                    input=full_prompt,
                    reasoning={"effort": reasoning_effort}
                )

                # GPT-5 returns full response at once
                output_content = response.output_text
                yield output_content

            # GPT-4 and earlier use Chat Completions API
            else:
                if stream:
                    # Streaming response
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are an AI assistant specialized in analyzing Slack conversations and extracting actionable insights."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=True
                    )

                    for chunk in response:
                        if chunk.choices[0].delta.content:
                            yield chunk.choices[0].delta.content
                else:
                    # Non-streaming response
                    response = self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {
                                "role": "system",
                                "content": "You are an AI assistant specialized in analyzing Slack conversations and extracting actionable insights."
                            },
                            {
                                "role": "user",
                                "content": prompt
                            }
                        ],
                        temperature=temperature,
                        max_tokens=max_tokens,
                        stream=False
                    )

                    yield response.choices[0].message.content

        except Exception as e:
            raise Exception(f"OpenAI API error: {str(e)}")

    def estimate_tokens(self, text: str) -> int:
        """
        Rough estimate of token count for text
        Using approximation: 1 token ≈ 4 characters

        Args:
            text: Text to estimate

        Returns:
            Estimated token count
        """
        return len(text) // 4
