"""SQL-based view composer for enriched message views

Uses DuckDB to efficiently JOIN messages with JIRA metadata during view generation.
Delegates heavy lifting to SQL engine for optimal performance.
"""

from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime, timedelta
import duckdb


class SqlViewComposer:
    """Compose enriched message views using SQL

    Uses DuckDB to query Parquet files and enrich messages with JIRA metadata
    via SQL JOIN operations. More efficient than loading and joining in Python.

    Example:
        >>> composer = SqlViewComposer(base_path="cache")
        >>> messages = composer.read_messages_enriched("channel_C123", "2025-10-20")
        >>> for msg in messages:
        ...     print(msg["user_real_name"], msg.get("jira_metadata", []))
    """

    def __init__(self, base_path: str = "cache"):
        """Initialize SQL view composer

        Args:
            base_path: Base cache directory (default: "cache")
                      Messages expected at {base_path}/raw/messages
                      JIRA data expected at {base_path}/raw/jira
        """
        self.base_path = Path(base_path)
        self.messages_path = self.base_path / "raw" / "messages"
        self.jira_path = self.base_path / "raw" / "jira"

    def read_messages_enriched(
        self,
        channel: str,
        date: str
    ) -> List[Dict[str, Any]]:
        """Read messages with JIRA enrichment for a single channel/date

        Args:
            channel: Channel name (e.g., "channel_C05713KTQF9" or "backend-devs")
            date: Date in YYYY-MM-DD format

        Returns:
            List of message dicts with enriched jira_metadata field

        Example:
            >>> composer = SqlViewComposer()
            >>> messages = composer.read_messages_enriched("channel_C123", "2025-10-20")
            >>> len(messages)
            42
        """
        # Check if message partition exists
        partition_dir = self.messages_path / f"dt={date}" / f"channel={channel}"
        parquet_file = partition_dir / "data.parquet"

        if not parquet_file.exists():
            return []

        # Build SQL query
        messages_glob = f"{partition_dir}/data.parquet"
        jira_glob = f"{self.jira_path}/**/*.parquet"

        conn = duckdb.connect()

        # Check if JIRA cache exists
        jira_exists = any(self.jira_path.glob("**/*.parquet"))

        if jira_exists:
            # Enriched query with JIRA JOIN
            query = f"""
            SELECT
                m.*,
                LIST({{
                    ticket_id: j.ticket_id,
                    summary: j.summary,
                    status: j.status,
                    priority: j.priority,
                    assignee: j.assignee
                }}) FILTER (WHERE j.ticket_id IS NOT NULL) as jira_metadata
            FROM "{messages_glob}" m
            LEFT JOIN (
                SELECT DISTINCT ON (m2.message_id, unnested.ticket_id)
                    m2.message_id,
                    unnested.ticket_id,
                    j2.summary,
                    j2.status,
                    j2.priority,
                    j2.assignee
                FROM "{messages_glob}" m2,
                     UNNEST(m2.jira_tickets) as unnested(ticket_id)
                LEFT JOIN "{jira_glob}" j2
                    ON unnested.ticket_id = j2.ticket_id
            ) j ON m.message_id = j.message_id
            GROUP BY m.message_id, m.user_id, m.user_name, m.user_real_name, m.user_email,
                     m.user_is_bot, m.text, m.timestamp, m.thread_ts, m.is_thread_parent,
                     m.is_thread_reply, m.reply_count, m.reactions, m.files, m.jira_tickets,
                     m.has_reactions, m.has_files, m.has_thread, m.channel, m.dt
            ORDER BY m.timestamp
            """
        else:
            # Fallback: just read messages without enrichment
            query = f"""
            SELECT *
            FROM "{messages_glob}"
            ORDER BY timestamp
            """

        result = conn.execute(query).fetchdf()

        # Convert to list of dicts
        messages = result.to_dict('records')

        # Ensure jira_metadata exists even if no JIRA cache
        if not jira_exists:
            for msg in messages:
                msg['jira_metadata'] = []

        return messages

    def read_messages_enriched_range(
        self,
        channel: str,
        start_date: str,
        end_date: str
    ) -> List[Dict[str, Any]]:
        """Read enriched messages from a channel across date range

        Args:
            channel: Channel name
            start_date: Start date in YYYY-MM-DD format (inclusive)
            end_date: End date in YYYY-MM-DD format (inclusive)

        Returns:
            List of enriched message dicts sorted chronologically

        Example:
            >>> composer = SqlViewComposer()
            >>> messages = composer.read_messages_enriched_range(
            ...     "channel_C123",
            ...     "2025-10-18",
            ...     "2025-10-20"
            ... )
        """
        # Generate date list
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
        date_list = []
        current = start
        while current <= end:
            date_list.append(current.strftime("%Y-%m-%d"))
            current += timedelta(days=1)

        # Collect messages from all dates
        all_messages = []
        for date in date_list:
            messages = self.read_messages_enriched(channel, date)
            all_messages.extend(messages)

        # Sort chronologically
        all_messages.sort(key=lambda m: m["timestamp"])

        return all_messages
