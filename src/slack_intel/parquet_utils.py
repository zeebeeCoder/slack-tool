"""Utilities for Parquet file partitioning and path management"""

from datetime import datetime
from pathlib import Path


def extract_date_from_slack_ts(timestamp: str) -> str:
    """Extract YYYY-MM-DD date from Slack timestamp

    Args:
        timestamp: Slack timestamp string (e.g., "1697654321.123456")

    Returns:
        Date string in YYYY-MM-DD format (e.g., "2023-10-18")

    Example:
        >>> extract_date_from_slack_ts("1697654321.123456")
        '2023-10-18'
    """
    # Convert Slack timestamp to datetime
    dt = datetime.fromtimestamp(float(timestamp))

    # Return date in YYYY-MM-DD format
    return dt.strftime("%Y-%m-%d")


def generate_partition_key(
    timestamp: str,
    channel_id: str,
    channel_name: str
) -> str:
    """Generate partition key from timestamp and channel

    Partition format: dt=YYYY-MM-DD/channel=channel_name

    Args:
        timestamp: Slack timestamp string
        channel_id: Slack channel ID (e.g., "C9876543210")
        channel_name: Human-readable channel name (e.g., "engineering")

    Returns:
        Partition key string (e.g., "dt=2023-10-18/channel=engineering")

    Example:
        >>> generate_partition_key("1697654321.123456", "C9876543210", "engineering")
        'dt=2023-10-18/channel=engineering'
    """
    date_str = extract_date_from_slack_ts(timestamp)
    return f"dt={date_str}/channel={channel_name}"


def get_partition_path(base_path: str, partition_key: str) -> str:
    """Get full path to Parquet file including partitions

    Args:
        base_path: Base directory for Parquet files (e.g., "cache/raw/messages")
        partition_key: Partition key (e.g., "dt=2023-10-18/channel=engineering")

    Returns:
        Full path to Parquet data file

    Example:
        >>> get_partition_path("cache/raw/messages", "dt=2023-10-18/channel=engineering")
        'cache/raw/messages/dt=2023-10-18/channel=engineering/data.parquet'
    """
    # Combine base path, partition key, and filename
    path = Path(base_path) / partition_key / "data.parquet"

    # Return as string with forward slashes
    return str(path).replace("\\", "/")


def get_partition_directory(base_path: str, partition_key: str) -> str:
    """Get directory path for a partition (without data.parquet filename)

    Args:
        base_path: Base directory for Parquet files
        partition_key: Partition key

    Returns:
        Directory path for the partition

    Example:
        >>> get_partition_directory("cache/raw/messages", "dt=2023-10-18/channel=engineering")
        'cache/raw/messages/dt=2023-10-18/channel=engineering'
    """
    path = Path(base_path) / partition_key
    return str(path).replace("\\", "/")
