"""Time-based message bucketing for multi-channel views

Groups messages into time buckets (hourly, daily) and organizes by channel
within each bucket for improved UX in merged views.
"""

from typing import List, Dict, Any
from datetime import datetime
from collections import defaultdict


class TimeBucket:
    """Represents a time bucket containing messages from multiple channels

    Attributes:
        start_time: Start of the bucket (datetime)
        end_time: End of the bucket (datetime)
        messages_by_channel: Dict mapping channel name to list of messages
        total_messages: Total count of messages in this bucket
    """

    def __init__(self, start_time: datetime, end_time: datetime):
        self.start_time = start_time
        self.end_time = end_time
        self.messages_by_channel: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.total_messages = 0

    def add_message(self, message: Dict[str, Any], channel: str):
        """Add a message to this bucket under the specified channel"""
        self.messages_by_channel[channel].append(message)
        self.total_messages += 1

    def get_channel_count(self) -> int:
        """Get number of unique channels with messages in this bucket"""
        return len(self.messages_by_channel)

    def get_channels(self) -> List[str]:
        """Get sorted list of channel names in this bucket"""
        return sorted(self.messages_by_channel.keys())


class TimeBucketer:
    """Bucket messages by time intervals for multi-channel views

    Supports hourly, daily, or no bucketing (pure chronological).
    Within each bucket, messages are grouped by channel.

    Example:
        >>> bucketer = TimeBucketer(bucket_type="hour")
        >>> buckets = bucketer.bucket_messages(messages)
        >>> for bucket in buckets:
        ...     print(f"{bucket.start_time} - {bucket.total_messages} messages")
    """

    def __init__(self, bucket_type: str = "hour"):
        """Initialize time bucketer

        Args:
            bucket_type: Type of bucketing ("hour", "day", "none")
                        - "hour": Group messages by hour
                        - "day": Group messages by day
                        - "none": No bucketing (pure chronological)
        """
        if bucket_type not in ["hour", "day", "none"]:
            raise ValueError(f"Invalid bucket_type: {bucket_type}")

        self.bucket_type = bucket_type

    def bucket_messages(self, messages: List[Dict[str, Any]]) -> List[TimeBucket]:
        """Bucket messages by time and channel

        Args:
            messages: List of message dicts with 'timestamp' and 'channel' fields
                     Messages should be sorted chronologically

        Returns:
            List of TimeBucket objects in chronological order
            Each bucket contains messages grouped by channel

        Example:
            >>> messages = [
            ...     {"timestamp": "2025-10-20T09:15:00Z", "channel": "backend", ...},
            ...     {"timestamp": "2025-10-20T09:45:00Z", "channel": "frontend", ...},
            ...     {"timestamp": "2025-10-20T10:30:00Z", "channel": "backend", ...},
            ... ]
            >>> bucketer = TimeBucketer("hour")
            >>> buckets = bucketer.bucket_messages(messages)
            >>> len(buckets)
            2
        """
        if not messages:
            return []

        if self.bucket_type == "none":
            # No bucketing - return single bucket with all messages
            return self._create_single_bucket(messages)

        # Group messages by bucket key
        bucket_map: Dict[str, TimeBucket] = {}

        for msg in messages:
            timestamp_str = msg.get("timestamp", "")
            channel = msg.get("channel", "unknown")

            if not timestamp_str:
                continue

            # Parse timestamp
            try:
                ts = timestamp_str.replace("Z", "+00:00")
                dt = datetime.fromisoformat(ts)
            except (ValueError, AttributeError):
                continue

            # Determine bucket key
            bucket_key = self._get_bucket_key(dt)

            # Create bucket if needed
            if bucket_key not in bucket_map:
                bucket_start, bucket_end = self._get_bucket_bounds(dt)
                bucket_map[bucket_key] = TimeBucket(bucket_start, bucket_end)

            # Add message to bucket
            bucket_map[bucket_key].add_message(msg, channel)

        # Sort buckets chronologically
        sorted_buckets = sorted(bucket_map.values(), key=lambda b: b.start_time)

        return sorted_buckets

    def _create_single_bucket(self, messages: List[Dict[str, Any]]) -> List[TimeBucket]:
        """Create a single bucket containing all messages (for 'none' mode)"""
        if not messages:
            return []

        # Get time range from messages
        first_ts = self._parse_timestamp(messages[0].get("timestamp", ""))
        last_ts = self._parse_timestamp(messages[-1].get("timestamp", ""))

        if not first_ts or not last_ts:
            # Fallback to current time if timestamps are invalid
            first_ts = datetime.now()
            last_ts = datetime.now()

        bucket = TimeBucket(first_ts, last_ts)

        for msg in messages:
            channel = msg.get("channel", "unknown")
            bucket.add_message(msg, channel)

        return [bucket]

    def _get_bucket_key(self, dt: datetime) -> str:
        """Get bucket key for a datetime"""
        if self.bucket_type == "hour":
            # Key: YYYY-MM-DD-HH
            return dt.strftime("%Y-%m-%d-%H")
        elif self.bucket_type == "day":
            # Key: YYYY-MM-DD
            return dt.strftime("%Y-%m-%d")
        else:
            return "all"

    def _get_bucket_bounds(self, dt: datetime) -> tuple:
        """Get start and end times for a bucket containing this datetime

        Args:
            dt: Datetime to find bucket for

        Returns:
            Tuple of (bucket_start, bucket_end) as datetime objects
        """
        if self.bucket_type == "hour":
            # Hourly bucket: HH:00 to HH:59
            start = dt.replace(minute=0, second=0, microsecond=0)
            end = start.replace(minute=59, second=59)
            return start, end
        elif self.bucket_type == "day":
            # Daily bucket: 00:00 to 23:59
            start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start.replace(hour=23, minute=59, second=59)
            return start, end
        else:
            # No bucketing - use message time as-is
            return dt, dt

    def _parse_timestamp(self, timestamp_str: str) -> datetime:
        """Parse timestamp string to datetime, returning None on error"""
        if not timestamp_str:
            return None

        try:
            ts = timestamp_str.replace("Z", "+00:00")
            return datetime.fromisoformat(ts)
        except (ValueError, AttributeError):
            return None
