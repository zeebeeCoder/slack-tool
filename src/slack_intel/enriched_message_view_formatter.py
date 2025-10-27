"""Enhanced message view formatter with JIRA metadata enrichment

Extends MessageViewFormatter to display enriched JIRA ticket metadata
(summary, status, priority, assignee) instead of just ticket IDs.
"""

from typing import List, Dict, Any, Optional
from .message_view_formatter import MessageViewFormatter, ViewContext


class EnrichedMessageViewFormatter(MessageViewFormatter):
    """Message formatter with JIRA metadata enrichment

    Extends base MessageViewFormatter to display enriched JIRA ticket details
    when jira_metadata field is available in messages.

    Falls back to ticket ID-only display if metadata is missing or empty.

    Example:
        >>> formatter = EnrichedMessageViewFormatter()
        >>> context = ViewContext(channel_name="engineering", date_range="2025-10-20")
        >>> view = formatter.format(messages, context)
        >>> print(view)
    """

    def __init__(self, template: str = "llm_optimized", resolve_mentions: bool = True, bucket_type: str = None):
        """Initialize enriched formatter

        Args:
            template: Output template type (default: "llm_optimized")
            resolve_mentions: Whether to resolve user mentions
            bucket_type: Time bucketing for multi-channel views
        """
        super().__init__(template=template, resolve_mentions=resolve_mentions, bucket_type=bucket_type)

    def _format_jira_tickets(self, msg: Dict[str, Any], indent: str = "   ") -> List[str]:
        """Format JIRA tickets with enriched metadata if available

        Args:
            msg: Message dict potentially containing jira_tickets and jira_metadata
            indent: Indentation string for formatting

        Returns:
            List of formatted lines for JIRA ticket display

        Example output:
            ```
            🎫 JIRA Tickets:
               • PRD-16920 [Highest] Issue Resolved
                 "Upgrade button still visible after upgra..."
                 Assignee: DeviBharat
            ```
        """
        jira_tickets = msg.get("jira_tickets", [])
        if jira_tickets is None or len(jira_tickets) == 0:
            return []

        jira_metadata = msg.get("jira_metadata", [])

        # If no metadata available, fall back to simple ticket ID display
        if jira_metadata is None or len(jira_metadata) == 0:
            return [f"{indent}🎫 JIRA: {', '.join(jira_tickets)}"]

        # Build metadata lookup by ticket_id
        metadata_map = {
            meta["ticket_id"]: meta
            for meta in jira_metadata
            if meta and "ticket_id" in meta
        }

        lines = [f"{indent}🎫 JIRA Tickets:"]

        for ticket_id in jira_tickets:
            meta = metadata_map.get(ticket_id)

            if meta:
                # Enriched display - handle None values
                priority = meta.get("priority") or "Unknown"
                status = meta.get("status") or "Unknown"
                summary = meta.get("summary") or "No summary"
                assignee = meta.get("assignee") or "Unassigned"

                # Truncate summary if too long
                if summary and len(summary) > 50:
                    summary = summary[:47] + "..."

                # Format: • TICKET-ID [Priority] Status
                lines.append(f"{indent}   • {ticket_id} [{priority}] {status}")
                # Format:   "Summary..."
                lines.append(f'{indent}     "{summary}"')
                # Format:   Assignee: Name
                lines.append(f"{indent}     Assignee: {assignee}")
            else:
                # Fallback: just show ticket ID if metadata missing
                lines.append(f"{indent}   • {ticket_id}")

        return lines

    def _format_message_compact(self, msg: Dict[str, Any], msg_number: int) -> str:
        """Format a message in compact style with enriched JIRA for bucketed views

        Overrides parent method to use enriched JIRA ticket display.
        """
        lines = []

        # User and timestamp
        user_name = msg.get("user_real_name", "Unknown User")
        timestamp = self._format_timestamp_short(msg.get("timestamp", ""))

        text = self._resolve_mentions(msg.get("text", ""))
        lines.append(f"  💬 {user_name} at {timestamp}:")
        lines.append(f"     {text}")

        # Reactions (compact)
        reactions = msg.get("reactions", [])
        if reactions is not None and len(reactions) > 0:
            reaction_strs = [f"{r.get('emoji', '')}({r.get('count', 0)})" for r in reactions]
            lines.append(f"     😊 {', '.join(reaction_strs)}")

        # Files (compact)
        files = msg.get("files", [])
        if files is not None and len(files) > 0:
            file_names = [f.get("name", "file") for f in files]
            lines.append(f"     📎 {', '.join(file_names)}")

        # JIRA tickets with enrichment (compact)
        jira_lines = self._format_jira_tickets(msg, indent="     ")
        if jira_lines:
            lines.extend(jira_lines)

        return "\n".join(lines)

    def _format_message(self, msg: Dict[str, Any], msg_number: int) -> str:
        """Format a parent message with enriched JIRA tickets

        Overrides parent method to use enriched JIRA ticket display.

        Args:
            msg: Message dict
            msg_number: Sequential message number for display

        Returns:
            Formatted message string
        """
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
        if reactions is not None and len(reactions) > 0:
            reaction_strs = []
            for reaction in reactions:
                emoji = reaction.get("emoji", "")
                count = reaction.get("count", 0)
                reaction_strs.append(f"{emoji}({count})")

            lines.append(f"   😊 Reactions: {', '.join(reaction_strs)}")

        # Files
        files = msg.get("files", [])
        if files is not None and len(files) > 0:
            file_names = []
            for file in files:
                name = file.get("name", "unknown")
                mimetype = file.get("mimetype", "")
                if mimetype:
                    file_names.append(f"{name} ({mimetype})")
                else:
                    file_names.append(name)

            lines.append(f"   📎 Files: {', '.join(file_names)}")

        # JIRA tickets (enriched)
        jira_lines = self._format_jira_tickets(msg, indent="   ")
        lines.extend(jira_lines)

        return "\n".join(lines)

    def _format_reply(self, reply: Dict[str, Any], reply_number: int) -> str:
        """Format a thread reply with enriched JIRA tickets

        Overrides parent method to use enriched JIRA ticket display.

        Args:
            reply: Reply message dict
            reply_number: Sequential reply number for display

        Returns:
            Formatted reply string
        """
        user_name = reply.get("user_real_name", "Unknown User")
        timestamp = self._format_timestamp(reply.get("timestamp", ""))
        text = self._resolve_mentions(reply.get("text", ""))

        lines = []
        lines.append(f"    ↳ REPLY #{reply_number}: {user_name} at {timestamp}:")
        lines.append(f"       {text}")

        # Reactions on reply
        reactions = reply.get("reactions", [])
        if reactions is not None and len(reactions) > 0:
            reaction_strs = []
            for reaction in reactions:
                emoji = reaction.get("emoji", "")
                count = reaction.get("count", 0)
                reaction_strs.append(f"{emoji}({count})")

            lines.append(f"       😊 Reactions: {', '.join(reaction_strs)}")

        # JIRA tickets in reply (enriched)
        jira_lines = self._format_jira_tickets(reply, indent="       ")
        lines.extend(jira_lines)

        return "\n".join(lines)
