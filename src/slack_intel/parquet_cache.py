"""Parquet caching for Slack messages using PyArrow

This module provides ParquetCache class for writing Slack messages to
partitioned Parquet files for efficient columnar storage and querying.
"""

from pathlib import Path
from typing import List, Dict, Any
import re

import pyarrow as pa
import pyarrow.parquet as pq

from .slack_channels import SlackMessage, SlackChannel


def _create_message_schema() -> pa.Schema:
    """Create PyArrow schema for Slack messages

    Schema matches PARQUET_SCHEMA.md specification.
    """
    return pa.schema([
        # Core message fields
        ("message_id", pa.string()),
        ("user_id", pa.string()),
        ("text", pa.string()),
        ("timestamp", pa.string()),  # ISO 8601 format

        # Thread fields
        ("thread_ts", pa.string()),
        ("is_thread_parent", pa.bool_()),
        ("is_thread_reply", pa.bool_()),
        ("reply_count", pa.int64()),

        # Flattened user fields
        ("user_name", pa.string()),
        ("user_real_name", pa.string()),
        ("user_email", pa.string()),
        ("user_is_bot", pa.bool_()),

        # Nested types - reactions
        ("reactions", pa.list_(pa.struct([
            ("emoji", pa.string()),
            ("count", pa.int64()),
            ("users", pa.list_(pa.string()))
        ]))),

        # Nested types - files
        ("files", pa.list_(pa.struct([
            ("id", pa.string()),
            ("name", pa.string()),
            ("mimetype", pa.string()),
            ("url", pa.string()),
            ("size", pa.int64())
        ]))),

        # JIRA tickets
        ("jira_tickets", pa.list_(pa.string())),

        # Boolean flags for filtering
        ("has_reactions", pa.bool_()),
        ("has_files", pa.bool_()),
        ("has_thread", pa.bool_()),
    ])


class ParquetCache:
    """Cache Slack messages in Parquet format for efficient querying

    Features:
    - Partitioned by date and channel
    - Columnar storage with PyArrow
    - Overwrite mode (replaces existing partitions)
    - Automatic directory creation

    Example:
        >>> cache = ParquetCache(base_path="cache/raw")
        >>> messages = [msg1, msg2, msg3]
        >>> channel = SlackChannel(name="engineering", id="C9876543210")
        >>> file_path = cache.save_messages(messages, channel, "2023-10-18")
        >>> print(file_path)
        'cache/raw/messages/dt=2023-10-18/channel=engineering/data.parquet'
    """

    def __init__(self, base_path: str = "cache/raw"):
        """Initialize ParquetCache

        Args:
            base_path: Base directory for cache (default: "cache/raw")
        """
        self.base_path = base_path
        self.schema = _create_message_schema()

    def save_messages(
        self,
        messages: List[SlackMessage],
        channel: SlackChannel,
        date: str
    ) -> str:
        """Save messages to partitioned Parquet file

        Args:
            messages: List of SlackMessage objects to save
            channel: SlackChannel object with name and id
            date: Date string in YYYY-MM-DD format

        Returns:
            Path to written Parquet file

        Raises:
            ValueError: If date format is invalid

        Example:
            >>> cache = ParquetCache()
            >>> messages = [SlackMessage(ts="123.456", text="Hello")]
            >>> channel = SlackChannel(name="general", id="C123")
            >>> path = cache.save_messages(messages, channel, "2023-10-18")
        """
        # Validate date format
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            raise ValueError(f"Invalid date format: {date}. Expected YYYY-MM-DD")

        # Handle empty message list
        if not messages:
            # Create empty table with schema
            table = pa.Table.from_pylist([], schema=self.schema)
        else:
            # Convert messages to dicts using to_parquet_dict()
            data = [msg.to_parquet_dict() for msg in messages]

            # Create PyArrow table
            table = pa.Table.from_pylist(data, schema=self.schema)

        # Generate partition path
        partition_key = f"dt={date}/channel={channel.name}"
        partition_dir = Path(self.base_path) / "messages" / partition_key
        file_path = partition_dir / "data.parquet"

        # Ensure directory exists
        self._ensure_directory_exists(str(partition_dir))

        # Write to Parquet (overwrite mode)
        # Note: If file exists, it will be overwritten automatically
        pq.write_table(
            table,
            str(file_path),
            compression='snappy'
        )

        return str(file_path).replace("\\", "/")

    def _ensure_directory_exists(self, path: str):
        """Create directory if it doesn't exist

        Args:
            path: Directory path to create
        """
        Path(path).mkdir(parents=True, exist_ok=True)

    def get_partition_info(self) -> Dict[str, Any]:
        """Get information about cached partitions

        Returns:
            Dict with partition statistics

        Example:
            >>> cache = ParquetCache()
            >>> info = cache.get_partition_info()
            >>> print(info['total_partitions'])
            5
        """
        messages_dir = Path(self.base_path) / "messages"

        if not messages_dir.exists():
            return {
                "total_partitions": 0,
                "partitions": []
            }

        # Find all Parquet files
        parquet_files = list(messages_dir.glob("**/*.parquet"))

        partitions = []
        for file_path in parquet_files:
            # Get partition info
            try:
                table = pq.read_table(str(file_path))
                partitions.append({
                    "path": str(file_path),
                    "row_count": table.num_rows,
                    "size_bytes": file_path.stat().st_size,
                })
            except Exception:
                # Skip files that can't be read
                continue

        return {
            "total_partitions": len(partitions),
            "partitions": partitions,
            "total_messages": sum(p["row_count"] for p in partitions),
            "total_size_bytes": sum(p["size_bytes"] for p in partitions),
        }
