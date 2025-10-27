"""Format structured messages into LLM-optimized text views

Generates human and LLM-readable text output from structured message data,
matching the format of generate_llm_optimized_text() in slack_channels.py
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import re


@dataclass
class ViewContext:
    """Context information for view formatting

    Attributes:
        channel_name: Name of the channel (or "Multi-Channel")
        date_range: Optional date range string (e.g., "2023-10-20" or "2023-10-18 to 2023-10-20")
        channels: Optional list of channels (for multi-channel views)
    """
    channel_name: str
    date_range: Optional[str] = None
    channels: Optional[List[str]] = field(default_factory=list)


class MessageViewFormatter:
    """Format structured messages into LLM-optimized text views

    Produces text output matching the format of generate_llm_optimized_text()
    with support for:
    - Chronological message display
    - Nested thread visualization
    - Rich content (reactions, files, JIRA tickets)
    - Clipped thread indicators
    - Summary statistics

    Example:
        >>> formatter = MessageViewFormatter()
        >>> context = ViewContext(channel_name="engineering", date_range="2023-10-20")
        >>> view = formatter.format(messages, context)
        >>> print(view)
    """

    def __init__(self, template: str = "llm_optimized", resolve_mentions: bool = True):
        """Initialize formatter

        Args:
            template: Output template type (default: "llm_optimized")
                     Options: "llm_optimized", "compact"
            resolve_mentions: Whether to resolve user mentions from <@USER_ID> to @username
        """
        self.template = template
        self.resolve_mentions = resolve_mentions
        self.user_mapping: Dict[str, str] = {}  # user_id -> display name

    def format(
        self,
        messages: List[Dict[str, Any]],
        context: ViewContext,
        cached_users: Optional[Dict[str, Dict[str, Any]]] = None
    ) -> str:
        """Format messages into readable text view

        Args:
            messages: List of structured message dicts (with nested "replies" if applicable)
            context: View context with channel info, date range, etc.
            cached_users: Optional dict of cached user data (user_id -> user_dict)
                         Used to resolve mentions for users not in messages

        Returns:
            Formatted text string ready for LLM consumption or human reading
        """
        if not messages:
            return self._format_empty_view(context)

        # Build user ID -> name mapping if mention resolution is enabled
        if self.resolve_mentions:
            self._build_user_mapping(messages, cached_users=cached_users)

        output_lines = []

        # Header
        output_lines.extend(self._format_header(context, messages))
        output_lines.append("")

        # Messages
        message_count = 0
        thread_count = 0
        total_replies = 0

        for msg in messages:
            message_count += 1

            # Format parent message
            formatted_msg = self._format_message(msg, message_count)
            output_lines.append(formatted_msg)

            # Check for thread replies
            replies = msg.get("replies", [])
            if replies:
                thread_count += 1
                total_replies += len(replies)

                # Check if thread is clipped
                is_clipped = msg.get("is_clipped_thread") or msg.get("has_clipped_replies")
                expected_replies = msg.get("reply_count", 0)

                output_lines.append("")
                if is_clipped and expected_replies > len(replies):
                    output_lines.append(f"  🧵 THREAD REPLIES (showing {len(replies)} of {expected_replies}+ replies):")
                else:
                    output_lines.append("  🧵 THREAD REPLIES:")

                # Format each reply
                for i, reply in enumerate(replies, 1):
                    formatted_reply = self._format_reply(reply, i)
                    output_lines.append(formatted_reply)

                # Clipped thread hint
                if is_clipped and expected_replies > len(replies):
                    output_lines.append("")
                    output_lines.append("  💡 Thread may have additional replies outside this time range")

            # Check if this is an orphaned reply
            elif msg.get("is_orphaned_reply"):
                output_lines.append("  🔗 Thread clipped (parent message outside time window)")
                output_lines.append("  💡 Widen date range to see full thread")

            output_lines.append("")
            output_lines.append("-" * 60)
            output_lines.append("")

        # Summary
        output_lines.extend(self._format_summary(message_count, thread_count, total_replies))

        return "\n".join(output_lines)

    def _format_header(self, context: ViewContext, messages: List[Dict[str, Any]]) -> List[str]:
        """Format header section"""
        lines = []
        lines.append("=" * 80)

        if context.channels:
            # Multi-channel view
            lines.append(f"📱 SLACK CHANNELS: {', '.join(context.channels)}")
        else:
            # Single channel view
            lines.append(f"📱 SLACK CHANNEL: {context.channel_name}")

        if context.date_range:
            lines.append(f"⏰ TIME WINDOW: {context.date_range}")

        lines.append("=" * 80)

        return lines

    def _format_message(self, msg: Dict[str, Any], msg_number: int) -> str:
        """Format a single parent message"""
        lines = []

        # Message header
        clipped_indicator = ""
        if msg.get("is_clipped_thread") or msg.get("is_orphaned_reply"):
            clipped_indicator = " (🔗 Thread clipped)"

        lines.append(f"💬 MESSAGE #{msg_number}{clipped_indicator}")

        # User and timestamp
        user_name = msg.get("user_real_name", "Unknown User")
        timestamp = self._format_timestamp(msg.get("timestamp", ""))

        text = self._resolve_mentions(msg.get("text", ""))
        lines.append(f"👤 {user_name} at {timestamp}:")
        lines.append(f"   {text}")

        # Reactions
        reactions = msg.get("reactions", [])
        if reactions:
            reaction_strs = []
            for reaction in reactions:
                emoji = reaction.get("emoji", "")
                count = reaction.get("count", 0)
                reaction_strs.append(f"{emoji}({count})")

            lines.append(f"   😊 Reactions: {', '.join(reaction_strs)}")

        # Files
        files = msg.get("files", [])
        if files:
            file_names = []
            for file in files:
                name = file.get("name", "unknown")
                mimetype = file.get("mimetype", "")
                if mimetype:
                    file_names.append(f"{name} ({mimetype})")
                else:
                    file_names.append(name)

            lines.append(f"   📎 Files: {', '.join(file_names)}")

        # JIRA tickets
        jira_tickets = msg.get("jira_tickets", [])
        if jira_tickets:
            lines.append(f"   🎫 JIRA: {', '.join(jira_tickets)}")

        return "\n".join(lines)

    def _format_reply(self, reply: Dict[str, Any], reply_number: int) -> str:
        """Format a thread reply"""
        user_name = reply.get("user_real_name", "Unknown User")
        timestamp = self._format_timestamp(reply.get("timestamp", ""))
        text = self._resolve_mentions(reply.get("text", ""))

        lines = []
        lines.append(f"    ↳ REPLY #{reply_number}: {user_name} at {timestamp}:")
        lines.append(f"       {text}")

        # Reactions on reply
        reactions = reply.get("reactions", [])
        if reactions:
            reaction_strs = []
            for reaction in reactions:
                emoji = reaction.get("emoji", "")
                count = reaction.get("count", 0)
                reaction_strs.append(f"{emoji}({count})")

            lines.append(f"       😊 Reactions: {', '.join(reaction_strs)}")

        # Files on reply
        files = reply.get("files", [])
        if files:
            file_names = [f.get("name", "unknown") for f in files]
            lines.append(f"       📎 Files: {', '.join(file_names)}")

        return "\n".join(lines)

    def _format_summary(self, message_count: int, thread_count: int, total_replies: int) -> List[str]:
        """Format summary statistics section"""
        lines = []
        lines.append("📊 CONVERSATION SUMMARY:")
        lines.append(f"   • Total Messages: {message_count}")
        lines.append(f"   • Total Thread Replies: {total_replies}")
        lines.append(f"   • Active Threads: {thread_count}")

        return lines

    def _format_empty_view(self, context: ViewContext) -> str:
        """Format view for empty message list"""
        lines = []
        lines.append("=" * 80)
        lines.append(f"📱 SLACK CHANNEL: {context.channel_name}")
        if context.date_range:
            lines.append(f"⏰ TIME WINDOW: {context.date_range}")
        lines.append("=" * 80)
        lines.append("")
        lines.append("No messages found in the specified time window.")
        lines.append("")
        lines.append("=" * 80)

        return "\n".join(lines)

    def _build_user_mapping(self, messages: List[Dict[str, Any]], cached_users: Optional[Dict[str, Dict[str, Any]]] = None) -> None:
        """Build user_id -> display name mapping from messages and cached users

        Starts with cached user data as base, then overlays with message authors
        (who have fresher data). Recursively processes messages and replies.

        Args:
            messages: List of message dicts (potentially with nested replies)
            cached_users: Optional dict of cached user data (user_id -> user_dict)
                         Used as base mapping for users not in messages
        """
        # Start with cached users as base (if provided)
        if cached_users:
            for user_id, user_data in cached_users.items():
                display_name = user_data.get("user_real_name") or user_data.get("user_name") or user_id
                self.user_mapping[user_id] = display_name

        # Overlay with message authors (fresher data)
        def process_message(msg: Dict[str, Any]) -> None:
            user_id = msg.get("user_id")
            if user_id:
                # Always update - message authors have fresher data
                display_name = msg.get("user_real_name") or msg.get("user_name") or user_id
                self.user_mapping[user_id] = display_name

            # Process replies recursively
            for reply in msg.get("replies", []):
                process_message(reply)

        for message in messages:
            process_message(message)

    def _resolve_mentions(self, text: str) -> str:
        """Resolve Slack user mentions from <@USER_ID> to @username

        Args:
            text: Message text containing Slack mentions like <@U02JRGK9TCG>

        Returns:
            Text with mentions resolved to @username (or left as-is if not found)
        """
        if not self.resolve_mentions or not text:
            return text

        def replace_mention(match):
            user_id = match.group(1)
            if user_id in self.user_mapping:
                return f"@{self.user_mapping[user_id]}"
            else:
                # Keep original if not found in mapping
                return match.group(0)

        # Pattern: <@USER_ID> where USER_ID starts with U
        pattern = r'<@(U[A-Z0-9]+)>'
        return re.sub(pattern, replace_mention, text)

    def _format_timestamp(self, timestamp_str: str) -> str:
        """Format ISO timestamp to readable format with relative time

        Args:
            timestamp_str: ISO 8601 timestamp string (e.g., "2023-10-20T10:00:00Z")

        Returns:
            Formatted timestamp with relative time (e.g., "2023-10-20 10:00 (2 days ago)")
        """
        if not timestamp_str:
            return "unknown time"

        try:
            # Handle both with and without Z suffix
            ts = timestamp_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)

            # Format absolute time
            absolute_time = dt.strftime("%Y-%m-%d %H:%M")

            # Calculate relative time
            relative_time = self._get_relative_time(dt)

            return f"{absolute_time} ({relative_time})"
        except (ValueError, AttributeError):
            # Fallback for malformed timestamps
            return timestamp_str[:16] if len(timestamp_str) >= 16 else timestamp_str

    def _get_relative_time(self, dt: datetime) -> str:
        """Get human-readable relative time from datetime

        Args:
            dt: Datetime object to calculate relative time from

        Returns:
            Relative time string (e.g., "2 mins ago", "3 hours ago", "5 days ago")
        """
        now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
        diff = now - dt

        seconds = diff.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:  # Less than 1 hour
            mins = int(seconds / 60)
            return f"{mins} min{'s' if mins != 1 else ''} ago"
        elif seconds < 86400:  # Less than 1 day
            hours = int(seconds / 3600)
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        elif seconds < 604800:  # Less than 1 week
            days = int(seconds / 86400)
            return f"{days} day{'s' if days != 1 else ''} ago"
        elif seconds < 2592000:  # Less than 30 days
            weeks = int(seconds / 604800)
            return f"{weeks} week{'s' if weeks != 1 else ''} ago"
        elif seconds < 31536000:  # Less than 1 year
            months = int(seconds / 2592000)
            return f"{months} month{'s' if months != 1 else ''} ago"
        else:
            years = int(seconds / 31536000)
            return f"{years} year{'s' if years != 1 else ''} ago"
