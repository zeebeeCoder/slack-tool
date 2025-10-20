"""Read messages from Parquet cache with partitioning support

Provides efficient querying of cached Slack messages stored in partitioned
Parquet format (dt=YYYY-MM-DD/channel=name).
"""

from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import pyarrow.parquet as pq


class ParquetMessageReader:
    """Read and query Slack messages from Parquet cache

    Supports:
    - Single partition reads (channel + date)
    - Date range queries (multiple partitions)
    - Multi-channel queries
    - Automatic chronological sorting

    Example:
        >>> reader = ParquetMessageReader(base_path="cache/raw")
        >>> messages = reader.read_channel("engineering", "2023-10-20")
        >>> print(f"Found {len(messages)} messages")
    """

    def __init__(self, base_path: str = "cache"):
        """Initialize reader

        Args:
            base_path: Base cache directory (default: "cache")
                      Messages are expected at {base_path}/raw/messages
        """
        self.base_path = Path(base_path)
        self.messages_path = self.base_path / "raw" / "messages"

    def read_channel(
        self,
        channel: str,
        date: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Read messages from a single channel/date partition

        Args:
            channel: Channel name (e.g., "engineering")
            date: Date in YYYY-MM-DD format
            filters: Optional field filters (e.g., {"is_thread_parent": True})

        Returns:
            List of message dicts, sorted chronologically

        Example:
            >>> reader = ParquetMessageReader()
            >>> messages = reader.read_channel("engineering", "2023-10-20")
            >>> thread_parents = reader.read_channel(
            ...     "engineering",
            ...     "2023-10-20",
            ...     filters={"is_thread_parent": True}
            ... )
        """
        partition_dir = self.messages_path / f"dt={date}" / f"channel={channel}"
        parquet_file = partition_dir / "data.parquet"

        # Return empty list if partition doesn't exist
        if not parquet_file.exists():
            return []

        # Read Parquet file
        table = pq.read_table(str(parquet_file))

        # Convert to list of dicts
        messages = table.to_pylist()

        # Apply filters if provided
        if filters:
            messages = self._apply_filters(messages, filters)

        # Sort chronologically
        messages.sort(key=lambda m: m["timestamp"])

        return messages

    def read_channel_range(
        self,
        channel: str,
        start_date: str,
        end_date: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Read messages from a channel across multiple dates

        Args:
            channel: Channel name
            start_date: Start date in YYYY-MM-DD format (inclusive)
            end_date: End date in YYYY-MM-DD format (inclusive)
            filters: Optional field filters

        Returns:
            List of message dicts from all dates, sorted chronologically

        Example:
            >>> reader = ParquetMessageReader()
            >>> messages = reader.read_channel_range(
            ...     "engineering",
            ...     "2023-10-18",
            ...     "2023-10-20"
            ... )
        """
        # Generate list of dates in range
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")

        all_messages = []
        current = start

        while current <= end:
            date_str = current.strftime("%Y-%m-%d")
            messages = self.read_channel(channel, date_str, filters)
            all_messages.extend(messages)
            current += timedelta(days=1)

        # Sort chronologically across all partitions
        all_messages.sort(key=lambda m: m["timestamp"])

        return all_messages

    def read_all_channels(
        self,
        date: str,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Read messages from all channels for a specific date

        Args:
            date: Date in YYYY-MM-DD format
            filters: Optional field filters

        Returns:
            List of message dicts from all channels, sorted chronologically
            Each message will have a 'channel_name' field added

        Example:
            >>> reader = ParquetMessageReader()
            >>> messages = reader.read_all_channels("2023-10-20")
        """
        date_partition = self.messages_path / f"dt={date}"

        # Return empty list if date partition doesn't exist
        if not date_partition.exists():
            return []

        all_messages = []

        # Find all channel partitions for this date
        for channel_dir in date_partition.iterdir():
            if not channel_dir.is_dir():
                continue

            # Extract channel name from directory name (channel=engineering)
            if channel_dir.name.startswith("channel="):
                channel_name = channel_dir.name.replace("channel=", "")

                # Read messages from this channel
                messages = self.read_channel(channel_name, date, filters)

                # Add channel_name to each message
                for msg in messages:
                    msg["channel_name"] = channel_name

                all_messages.extend(messages)

        # Sort chronologically across all channels
        all_messages.sort(key=lambda m: m["timestamp"])

        return all_messages

    def find_messages_with_ticket(
        self,
        ticket_id: str,
        start_date: str,
        end_date: str,
        channel: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Find all messages mentioning a specific JIRA ticket

        Args:
            ticket_id: JIRA ticket ID (e.g., "PROJ-123")
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            channel: Optional channel name (searches all channels if not specified)

        Returns:
            List of messages containing the ticket ID, sorted chronologically

        Example:
            >>> reader = ParquetMessageReader()
            >>> messages = reader.find_messages_with_ticket(
            ...     "PROJ-123",
            ...     "2023-10-18",
            ...     "2023-10-20"
            ... )
        """
        if channel:
            # Search specific channel
            messages = self.read_channel_range(channel, start_date, end_date)
        else:
            # Search all channels
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")

            all_messages = []
            current = start

            while current <= end:
                date_str = current.strftime("%Y-%m-%d")
                messages = self.read_all_channels(date_str)
                all_messages.extend(messages)
                current += timedelta(days=1)

            messages = all_messages

        # Filter for messages containing the ticket
        filtered = [
            msg for msg in messages
            if ticket_id in msg.get("jira_tickets", [])
        ]

        # Already sorted chronologically
        return filtered

    def _apply_filters(
        self,
        messages: List[Dict[str, Any]],
        filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Apply filters to message list

        Args:
            messages: List of message dicts
            filters: Dict of field:value filters

        Returns:
            Filtered message list
        """
        filtered = messages

        for field, value in filters.items():
            filtered = [msg for msg in filtered if msg.get(field) == value]

        return filtered
