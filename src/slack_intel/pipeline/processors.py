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

    SUMMARIZE_USER_TIMELINE = """You are analyzing a Slack user's timeline to understand their contributions and communication patterns.

User: {channel_name}
Date Range: {date_range}
Channels: {channels}

Messages:
{message_content}

Please provide a comprehensive analysis that includes:
1. **Key Contributions**: Main topics and areas where this user is active
2. **Expertise & Focus Areas**: Technical domains or business areas they engage with
3. **Communication Patterns**: How they interact (questions, answers, decisions, collaboration)
4. **Action Items Owned**: Tasks and responsibilities they've taken on
5. **Collaboration Network**: Who they work with most frequently
6. **Questions & Blockers**: Areas where they need input or are blocked

Focus on providing insights that would help understand this person's role, contributions, and current priorities."""

    SUMMARIZE_MULTI_CHANNEL = """You are analyzing messages across multiple Slack channels to identify organization-wide patterns and themes.

Channels: {channels}
Date Range: {date_range}

Messages:
{message_content}

Please provide a comprehensive cross-channel analysis that includes:
1. **Common Themes**: Topics and discussions appearing across multiple channels
2. **Cross-Functional Coordination**: How different teams interact and depend on each other
3. **Channel-Specific Highlights**: Key developments unique to each channel
4. **Organization-Wide Trends**: Patterns affecting multiple teams or the whole organization
5. **Critical Dependencies**: Blockers or decisions impacting multiple channels
6. **Emerging Issues**: New concerns or opportunities emerging across channels

Focus on synthesizing insights across channels rather than analyzing them in isolation."""


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
        reasoning_effort: str = "medium",
        view_type: str = "single_channel",
        channels: list = None
    ) -> Iterator[str]:
        """
        Generate a summary of Slack messages using OpenAI

        Args:
            message_content: Formatted message content from view command
            channel_name: Name of the Slack channel or user
            date_range: Date range of messages
            model: OpenAI model to use (default: gpt-4o, or gpt-5)
            temperature: Sampling temperature (not supported by GPT-5)
            max_tokens: Maximum tokens in response (not supported by GPT-5)
            stream: Whether to stream the response (not supported by GPT-5)
            reasoning_effort: Reasoning effort for GPT-5 (low, medium, high)
            view_type: Type of view ("single_channel", "multi_channel", "user_timeline")
            channels: List of channel names (for multi-channel and user timeline views)

        Yields:
            Chunks of generated text if streaming, full text otherwise
        """
        # Select appropriate prompt template based on view type
        if view_type == "user_timeline":
            template = PromptTemplates.SUMMARIZE_USER_TIMELINE
            channels_str = ", ".join(channels) if channels else "multiple channels"
            prompt = template.format(
                channel_name=channel_name,
                date_range=date_range,
                channels=channels_str,
                message_content=message_content
            )
        elif view_type == "multi_channel":
            template = PromptTemplates.SUMMARIZE_MULTI_CHANNEL
            channels_str = ", ".join(channels) if channels else "multiple channels"
            prompt = template.format(
                channels=channels_str,
                date_range=date_range,
                message_content=message_content
            )
        else:  # single_channel
            template = PromptTemplates.SUMMARIZE_MESSAGES
            prompt = template.format(
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
