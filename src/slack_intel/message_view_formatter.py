"""Format structured messages into LLM-optimized text views

Generates human and LLM-readable text output from structured message data,
matching the format of generate_llm_optimized_text() in slack_channels.py
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
import re
from .time_bucketer import TimeBucketer, TimeBucket


@dataclass
class ViewMetadata:
    """Computed metadata statistics for attention flow analysis"""
    total_messages: int = 0
    total_threads: int = 0
    total_replies: int = 0
    unique_participants: int = 0
    avg_thread_depth: float = 0.0
    high_engagement_threads: int = 0  # threads with N+ replies
    leadership_messages: int = 0  # messages from high-weight stakeholders
    cross_channel_topics: int = 0  # topics mentioned across multiple channels


@dataclass
class ViewContext:
    """Context information for view formatting

    Attributes:
        channel_name: Name of the channel (or "Multi-Channel")
        date_range: Optional date range string (e.g., "2023-10-20" or "2023-10-18 to 2023-10-20")
        channels: Optional list of channels (for multi-channel views)
        org_context: Optional organizational context (name, stakeholders, channel descriptions)
        metadata: Optional computed metadata statistics
    """
    channel_name: str
    date_range: Optional[str] = None
    channels: Optional[List[str]] = field(default_factory=list)
    org_context: Optional[Dict[str, Any]] = None  # From config
    metadata: Optional[ViewMetadata] = None


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

    def __init__(self, template: str = "llm_optimized", resolve_mentions: bool = True, bucket_type: str = None):
        """Initialize formatter

        Args:
            template: Output template type (default: "llm_optimized")
                     Options: "llm_optimized", "compact"
            resolve_mentions: Whether to resolve user mentions from <@USER_ID> to @username
            bucket_type: Time bucketing for multi-channel views ("hour", "day", "none", or None for single-channel)
        """
        self.template = template
        self.resolve_mentions = resolve_mentions
        self.bucket_type = bucket_type
        self.user_mapping: Dict[str, str] = {}  # user_id -> display name

    @staticmethod
    def compute_metadata(
        messages: List[Dict[str, Any]],
        org_context: Optional[Dict[str, Any]] = None,
        high_engagement_threshold: int = 5
    ) -> ViewMetadata:
        """Compute metadata statistics for attention flow analysis

        Args:
            messages: List of structured message dicts
            org_context: Optional organizational context with stakeholders
            high_engagement_threshold: Minimum replies for high engagement thread

        Returns:
            ViewMetadata with computed statistics
        """
        total_messages = len(messages)
        total_threads = 0
        total_replies = 0
        unique_participants = set()
        thread_depths = []
        high_engagement_threads = 0
        leadership_messages = 0

        # Build stakeholder name set for quick lookup
        leadership_names = set()
        if org_context and org_context.get("stakeholders"):
            for s in org_context["stakeholders"]:
                if s.get("weight", 0) >= 7:  # High-weight stakeholders
                    leadership_names.add(s.get("name", "").lower())

        # Analyze messages
        for msg in messages:
            # Track participants
            user_name = msg.get("user_real_name") or msg.get("user_name")
            if user_name:
                unique_participants.add(user_name)

                # Check if leadership
                if user_name.lower() in leadership_names:
                    leadership_messages += 1

            # Check for thread
            replies = msg.get("replies", [])
            if replies:
                total_threads += 1
                reply_count = len(replies)
                total_replies += reply_count
                thread_depths.append(reply_count)

                if reply_count >= high_engagement_threshold:
                    high_engagement_threads += 1

                # Track reply participants
                for reply in replies:
                    reply_user = reply.get("user_real_name") or reply.get("user_name")
                    if reply_user:
                        unique_participants.add(reply_user)

                        # Check if leadership in replies
                        if reply_user.lower() in leadership_names:
                            leadership_messages += 1

        # Compute average thread depth
        avg_thread_depth = sum(thread_depths) / len(thread_depths) if thread_depths else 0.0

        return ViewMetadata(
            total_messages=total_messages,
            total_threads=total_threads,
            total_replies=total_replies,
            unique_participants=len(unique_participants),
            avg_thread_depth=avg_thread_depth,
            high_engagement_threads=high_engagement_threads,
            leadership_messages=leadership_messages
        )

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

        # Store context for use in formatting methods
        self.context = context

        # Build user ID -> name mapping if mention resolution is enabled
        if self.resolve_mentions:
            self._build_user_mapping(messages, cached_users=cached_users)

        # Check if multi-channel view with bucketing
        if self.bucket_type and len(context.channels) > 1:
            return self._format_bucketed_view(messages, context)
        else:
            return self._format_single_channel_view(messages, context)

    def _format_single_channel_view(
        self,
        messages: List[Dict[str, Any]],
        context: ViewContext
    ) -> str:
        """Format traditional single-channel view (original behavior)"""
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

    def _format_bucketed_view(
        self,
        messages: List[Dict[str, Any]],
        context: ViewContext
    ) -> str:
        """Format multi-channel view with time bucketing

        Groups messages into time buckets (hour/day), then within each bucket
        displays messages grouped by channel for better UX.
        """
        output_lines = []

        # Header
        output_lines.extend(self._format_header(context, messages))
        output_lines.append("")

        # Create time bucketer and bucket messages
        bucketer = TimeBucketer(bucket_type=self.bucket_type)
        buckets = bucketer.bucket_messages(messages)

        # Track global stats
        total_message_count = 0
        total_thread_count = 0
        total_reply_count = 0

        # Format each bucket
        for bucket_idx, bucket in enumerate(buckets, 1):
            output_lines.extend(self._format_bucket_header(bucket, bucket_idx))
            output_lines.append("")

            # Format messages for each channel in this bucket
            for channel in bucket.get_channels():
                channel_messages = bucket.messages_by_channel[channel]

                output_lines.append(f"📱 #{channel} ({len(channel_messages)} messages)")
                output_lines.append("")

                # Format messages in this channel
                for msg_idx, msg in enumerate(channel_messages, 1):
                    total_message_count += 1

                    # Format message (simplified for bucketed view)
                    formatted_msg = self._format_message_compact(msg, msg_idx)
                    output_lines.append(formatted_msg)

                    # Check for thread replies
                    replies = msg.get("replies", [])
                    if replies:
                        total_thread_count += 1
                        total_reply_count += len(replies)

                        output_lines.append("")
                        output_lines.append("  🧵 THREAD REPLIES:")

                        for reply_idx, reply in enumerate(replies, 1):
                            formatted_reply = self._format_reply(reply, reply_idx)
                            output_lines.append(formatted_reply)

                    output_lines.append("")

                output_lines.append("-" * 50)
                output_lines.append("")

            # Bucket separator
            output_lines.append("=" * 80)
            output_lines.append("")

        # Overall summary
        output_lines.extend(self._format_summary(
            total_message_count,
            total_thread_count,
            total_reply_count
        ))

        return "\n".join(output_lines)

    def _format_header(self, context: ViewContext, messages: List[Dict[str, Any]]) -> List[str]:
        """Format header section with optional metadata and organizational context"""
        lines = []
        lines.append("=" * 80)

        # Organization context
        if context.org_context and context.org_context.get("name"):
            org_name = context.org_context.get("name")
            lines.append(f"🏢 ORGANIZATION: {org_name}")

        # Channel info
        if context.channels:
            # Multi-channel view
            lines.append(f"📱 SLACK CHANNELS: {', '.join(context.channels)}")

            # Add channel descriptions if available
            if context.org_context and context.org_context.get("channels"):
                channel_map = {ch['name']: ch for ch in context.org_context['channels']}
                for channel_name in context.channels:
                    # Try with and without channel_ prefix
                    ch_config = channel_map.get(channel_name) or channel_map.get(channel_name.replace("channel_", ""))
                    if ch_config and ch_config.get("description"):
                        lines.append(f"   • {channel_name}: {ch_config['description']}")
        else:
            # Single channel view
            lines.append(f"📱 SLACK CHANNEL: {context.channel_name}")

            # Add channel description if available
            if context.org_context and context.org_context.get("channels"):
                channel_map = {ch['name']: ch for ch in context.org_context['channels']}
                ch_name = context.channel_name.replace("channel_", "")
                ch_config = channel_map.get(ch_name)
                if ch_config and ch_config.get("description"):
                    lines.append(f"   Purpose: {ch_config['description']}")

        # Date range
        if context.date_range:
            lines.append(f"⏰ TIME WINDOW: {context.date_range}")

        # Metadata section (if computed)
        if context.metadata:
            lines.append("")
            lines.append("📊 CONVERSATION METRICS:")
            meta = context.metadata
            lines.append(f"   • Total Messages: {meta.total_messages}")
            lines.append(f"   • Active Threads: {meta.total_threads} ({meta.total_replies} replies)")
            if meta.avg_thread_depth > 0:
                lines.append(f"   • Avg Thread Depth: {meta.avg_thread_depth:.1f} replies")
            lines.append(f"   • Unique Participants: {meta.unique_participants}")
            if meta.high_engagement_threads > 0:
                lines.append(f"   • High Engagement Threads: {meta.high_engagement_threads} (5+ replies)")
            if meta.leadership_messages > 0:
                lines.append(f"   • Leadership Involvement: {meta.leadership_messages} messages from key stakeholders")

        # Stakeholder context (if available)
        if context.org_context and context.org_context.get("stakeholders"):
            stakeholders = context.org_context["stakeholders"]
            if stakeholders:
                lines.append("")
                lines.append("👥 KEY STAKEHOLDERS:")
                for s in stakeholders[:5]:  # Show top 5
                    role = s.get("role", "")
                    weight = s.get("weight", 5)
                    attention_level = "🔴" if weight >= 9 else "🟠" if weight >= 7 else "🟡"
                    lines.append(f"   {attention_level} {s.get('name', '')} - {role}")

        lines.append("=" * 80)

        return lines

    def _format_bucket_header(self, bucket: TimeBucket, bucket_number: int) -> List[str]:
        """Format header for a time bucket"""
        lines = []

        # Format time range based on bucket type
        if self.bucket_type == "hour":
            time_label = bucket.start_time.strftime("%Y-%m-%d %H:00-%H:59")
        elif self.bucket_type == "day":
            time_label = bucket.start_time.strftime("%Y-%m-%d")
        else:
            time_label = "All Messages"

        lines.append("=" * 80)
        lines.append(f"📅 TIME BUCKET: {time_label}")
        lines.append(f"   Total Messages: {bucket.total_messages} across {bucket.get_channel_count()} channels")
        lines.append("=" * 80)

        return lines

    def _format_message_compact(self, msg: Dict[str, Any], msg_number: int) -> str:
        """Format a message in compact style for bucketed views"""
        lines = []

        # User and timestamp
        user_name = msg.get("user_real_name", "Unknown User")
        timestamp = self._format_timestamp_short(msg.get("timestamp", ""))

        text = self._resolve_mentions(msg.get("text", ""))
        lines.append(f"  💬 {user_name} at {timestamp}:")
        lines.append(f"     {text}")

        # Reactions (compact)
        reactions = msg.get("reactions", [])
        if reactions:
            reaction_strs = [f"{r.get('emoji', '')}({r.get('count', 0)})" for r in reactions]
            lines.append(f"     😊 {', '.join(reaction_strs)}")

        # Files (compact)
        files = msg.get("files", [])
        if files:
            file_names = [f.get("name", "file") for f in files]
            lines.append(f"     📎 {', '.join(file_names)}")

        # JIRA tickets
        jira_tickets = msg.get("jira_tickets", [])
        if jira_tickets:
            lines.append(f"     🎫 {', '.join(jira_tickets)}")

        return "\n".join(lines)

    def _format_message(self, msg: Dict[str, Any], msg_number: int) -> str:
        """Format a single parent message"""
        lines = []

        # Message header
        clipped_indicator = ""
        if msg.get("is_clipped_thread") or msg.get("is_orphaned_reply"):
            clipped_indicator = " (🔗 Thread clipped)"

        lines.append(f"💬 MESSAGE #{msg_number}{clipped_indicator}")

        # Show channel name if multi-channel context (like user timeline)
        if hasattr(self, 'context') and self.context:
            context_channels = getattr(self.context, 'channels', [])
            if context_channels and len(context_channels) > 1:
                channel = msg.get("channel", "unknown")
                lines.append(f"📍 Channel: #{channel}")

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

    def _format_timestamp_short(self, timestamp_str: str) -> str:
        """Format timestamp to short readable format (HH:MM only)

        Args:
            timestamp_str: ISO 8601 timestamp string

        Returns:
            Formatted timestamp (e.g., "10:30")
        """
        if not timestamp_str:
            return "unknown"

        try:
            ts = timestamp_str.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
            return dt.strftime("%H:%M")
        except (ValueError, AttributeError):
            return timestamp_str[:5] if len(timestamp_str) >= 5 else timestamp_str

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
