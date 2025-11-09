"""LLM processors for message analysis"""

import time
from typing import Iterator, Optional
from openai import OpenAI


class PromptTemplates:
    """Prompt templates for different processing stages with attention flow awareness"""

    SUMMARIZE_MESSAGES = """You are analyzing Slack channel messages to provide actionable insights.

Channel: {channel_name}
Date Range: {date_range}

{org_context}

Messages:
{message_content}

Please provide a comprehensive summary using the Attention Flow framework:

1. **KEY DISCUSSIONS** (What captured attention):
   - Main topics and their intensity level
   - Tag each as: 🚣 Tactical (execution), 🛠️ Strategic (systems/process), or ⚠️ Reactive (incidents)
   - Note leadership involvement (CEO, VPs) as gravity wells

2. **IMPORTANT DECISIONS & COMMITMENTS**:
   - Decisions made with owners
   - Commitments and deadlines
   - Decision velocity (fast vs slow)

3. **ACTION ITEMS & BLOCKERS**:
   - Clear action items with owners
   - Blockers or dependencies mentioned
   - Questions awaiting resolution

4. **ENGAGEMENT SIGNALS** (How hot is the discussion):
   - High engagement threads (5+ replies)
   - Cross-functional participation
   - Leadership attention markers

5. **TEMPORAL CONTEXT** (If visible):
   - New topics appearing for first time
   - Topics that seem resolved or concluded
   - Ongoing discussions continuing from prior context

Focus on actionable insights with attention ranking based on leadership involvement, cross-functional engagement, and decision velocity."""

    SUMMARIZE_USER_TIMELINE = """You are analyzing a Slack user's timeline to understand their contributions and communication patterns.

User: {channel_name}
Date Range: {date_range}
Channels: {channels}

{org_context}

Messages:
{message_content}

Please provide a comprehensive analysis using the Attention Flow framework:

1. **FOCAL POINTS** (Where their attention is concentrated):
   - Top 3-5 topics/initiatives they're driving or contributing to
   - Classify as: 🚣 Tactical execution or 🛠️ Strategic/infrastructure work
   - Attention intensity (message volume, thread depth)

2. **KEY CONTRIBUTIONS & EXPERTISE**:
   - Main technical domains or business areas
   - Type of participation: Asking questions, providing answers, making decisions
   - Leadership signals (if they're driving initiatives vs. supporting)

3. **COLLABORATION NETWORK**:
   - Who they work with most frequently
   - Cross-functional vs. within-team collaboration
   - Are they a connector or specialist?

4. **WORK CLASSIFICATION** (Paddling vs Boat-building):
   - % Tactical execution (features, firefighting, support)
   - % Strategic work (process, tooling, infrastructure)
   - % Reactive work (incidents, urgent fixes)

5. **ACTION ITEMS & OWNERSHIP**:
   - Clear commitments and deadlines
   - Tasks they've taken on
   - Dependencies and blockers

6. **QUESTIONS & NEEDS**:
   - Areas where they're seeking input
   - Blockers they're facing
   - Unanswered questions

Focus on understanding this person's role, impact level, and attention distribution across tactical vs. strategic work."""

    SUMMARIZE_MULTI_CHANNEL = """You are analyzing messages across multiple Slack channels to map organizational attention flow.

Channels: {channels}
Date Range: {date_range}

{org_context}

Messages:
{message_content}

Please provide a comprehensive Organizational Attention Flow analysis:

## 1. FOCAL POINTS (Where organizational attention is concentrated)

Identify the top 3-5 topics/initiatives consuming organizational energy:

🎯 **[Topic Name]**
   - **Drivers**: Key participants (note if leadership/CEO involved)
   - **Channels**: Which channels discussing this
   - **Intensity**: Message volume, thread depth, engagement level (High/Medium/Low)
   - **State**: Exploring | Deciding | Executing | Blocked | Resolving
   - **Work Type**: 🚣 Tactical | 🛠️ Strategic | ⚠️ Reactive

## 2. TEMPORAL DIRECTION (What's changing)

📈 **APPEARING** (New or escalating attention):
   - Topics first mentioned in this window or growing rapidly
   - Tag: [NEW] or [ESCALATING]

📉 **DISAPPEARING** (Fading or resolved):
   - Topics that were active but now quiet
   - Tag: [RESOLVED] (with evidence) or [ABANDONED] (no decision) or [QUIET]

🔄 **PERSISTING** (Strategic continuity):
   - Topics discussed consistently with sustained attention
   - Tag: [STRATEGIC] or [FOUNDATIONAL]

## 3. PADDLING vs BOAT-BUILDING (Organizational effort type)

🚣 **PADDLING** (Tactical - X%):
   - Feature development, bug fixes, product support
   - Customer issues, firefighting

🛠️ **BOAT-BUILDING** (Strategic - X%):
   - Process improvements, tooling, infrastructure
   - Governance, scalability, long-term capabilities

⚠️ **DRIFT** (Reactive overload - X%):
   - Incidents, urgent unplanned work
   - Context switching, chaos indicators

## 4. DECISION POINTS & BLOCKERS

❓ **OPEN QUESTIONS** being debated
🚧 **BLOCKERS** mentioned explicitly
✅ **COMMITMENTS** made (who will do what by when)

## 5. ORGANIZATIONAL DYNAMICS

**🎯 ATTENTION GRAVITY WELLS**:
   - Where is CEO/leadership pulling focus?
   - Topics with high-weight stakeholder involvement

**🔗 CROSS-FUNCTIONAL COORDINATION**:
   - How teams interact and depend on each other
   - Multi-channel topics (appear in 2+ channels)

**⚡ VELOCITY INDICATORS**:
   - Fast decisions (idea→decision in <4 hours)
   - Slow/stalled decisions (open for days)

**📡 SIGNAL STRENGTH**:
   - Strong signals: Leadership-driven, data-cited, cross-functional, clear ownership
   - Weak signals: Single advocates, vague ideas, no owner

Focus on synthesizing cross-channel patterns, ranking attention by leadership involvement and engagement intensity."""


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
        channels: list = None,
        org_context: dict = None
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
            org_context: Optional organizational context (stakeholders, channel descriptions)

        Yields:
            Chunks of generated text if streaming, full text otherwise
        """
        # Format organizational context if provided
        org_context_str = ""
        if org_context:
            org_context_str = self._format_org_context(org_context, view_type, channels)

        # Select appropriate prompt template based on view type
        if view_type == "user_timeline":
            template = PromptTemplates.SUMMARIZE_USER_TIMELINE
            channels_str = ", ".join(channels) if channels else "multiple channels"
            prompt = template.format(
                channel_name=channel_name,
                date_range=date_range,
                channels=channels_str,
                org_context=org_context_str,
                message_content=message_content
            )
        elif view_type == "multi_channel":
            template = PromptTemplates.SUMMARIZE_MULTI_CHANNEL
            channels_str = ", ".join(channels) if channels else "multiple channels"
            prompt = template.format(
                channels=channels_str,
                date_range=date_range,
                org_context=org_context_str,
                message_content=message_content
            )
        else:  # single_channel
            template = PromptTemplates.SUMMARIZE_MESSAGES
            prompt = template.format(
                channel_name=channel_name,
                date_range=date_range,
                org_context=org_context_str,
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

    def _format_org_context(self, org_context: dict, view_type: str, channels: list = None) -> str:
        """Format organizational context for prompt injection

        Args:
            org_context: Dict with organization, stakeholders, channels
            view_type: Type of view (affects which context to include)
            channels: List of channel names being analyzed

        Returns:
            Formatted context string
        """
        lines = []

        # Organization name
        if org_context.get("name"):
            lines.append(f"Organization: {org_context['name']}")

        # Stakeholders (for attention ranking)
        stakeholders = org_context.get("stakeholders", [])
        if stakeholders:
            lines.append("\nKey Stakeholders (for attention ranking):")
            for s in stakeholders:
                name = s.get("name", "")
                role = s.get("role", "")
                weight = s.get("weight", 5)
                # Only show high-weight stakeholders
                if weight >= 7:
                    attention_level = "CEO/Executive" if weight >= 9 else "Leadership"
                    lines.append(f"  • {name} ({role}) - {attention_level} level")

        # Channel context (if relevant)
        channel_configs = org_context.get("channels", [])
        if channel_configs and channels and view_type in ["multi_channel", "single_channel"]:
            lines.append("\nChannel Context:")
            channel_map = {ch["name"]: ch for ch in channel_configs}

            for channel_name in channels:
                # Try with and without channel_ prefix
                ch_key = channel_name.replace("channel_", "")
                ch_config = channel_map.get(ch_key) or channel_map.get(channel_name)

                if ch_config:
                    name = ch_config.get("name", channel_name)
                    purpose = ch_config.get("purpose", "")
                    signal_type = ch_config.get("signal_type", "medium")

                    signal_indicator = {
                        "critical": "🔴 CRITICAL",
                        "high": "🟠 HIGH",
                        "medium": "🟡 MEDIUM",
                        "low": "⚪ LOW"
                    }.get(signal_type, "🟡 MEDIUM")

                    if purpose:
                        lines.append(f"  • #{name} ({signal_indicator}): {purpose}")

        return "\n".join(lines) if lines else ""

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
