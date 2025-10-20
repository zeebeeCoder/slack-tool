"""Unit tests for ParquetMessageReader - TDD approach

Tests reading messages from Parquet files with partitioning support.
These tests will FAIL until ParquetMessageReader is implemented.
"""

import pytest
from pathlib import Path
from datetime import datetime
import pyarrow as pa
import pyarrow.parquet as pq


# This import will fail until we create the module
try:
    from slack_intel.parquet_message_reader import ParquetMessageReader
except ImportError:
    ParquetMessageReader = None


@pytest.fixture
def sample_parquet_cache(tmp_path):
    """Create sample Parquet cache with realistic test data"""
    base_path = tmp_path / "cache" / "raw" / "messages"

    # Define schema matching our Parquet schema
    schema = pa.schema([
        ("message_id", pa.string()),
        ("user_id", pa.string()),
        ("text", pa.string()),
        ("timestamp", pa.string()),
        ("thread_ts", pa.string()),
        ("is_thread_parent", pa.bool_()),
        ("is_thread_reply", pa.bool_()),
        ("reply_count", pa.int64()),
        ("user_name", pa.string()),
        ("user_real_name", pa.string()),
        ("user_email", pa.string()),
        ("user_is_bot", pa.bool_()),
        ("reactions", pa.list_(pa.struct([
            ("emoji", pa.string()),
            ("count", pa.int64()),
            ("users", pa.list_(pa.string()))
        ]))),
        ("files", pa.list_(pa.struct([
            ("id", pa.string()),
            ("name", pa.string()),
            ("mimetype", pa.string()),
            ("url", pa.string()),
            ("size", pa.int64())
        ]))),
        ("jira_tickets", pa.list_(pa.string())),
        ("has_reactions", pa.bool_()),
        ("has_files", pa.bool_()),
        ("has_thread", pa.bool_()),
    ])

    # Create test data for engineering channel - 2023-10-20
    engineering_data_oct20 = [
        {
            "message_id": "1697800000.000001",
            "user_id": "U001",
            "text": "First message of the day",
            "timestamp": "2023-10-20T10:00:00Z",
            "thread_ts": None,
            "is_thread_parent": False,
            "is_thread_reply": False,
            "reply_count": 0,
            "user_name": "alice",
            "user_real_name": "Alice Smith",
            "user_email": "alice@example.com",
            "user_is_bot": False,
            "reactions": [],
            "files": [],
            "jira_tickets": [],
            "has_reactions": False,
            "has_files": False,
            "has_thread": False,
        },
        {
            "message_id": "1697803600.000002",
            "user_id": "U002",
            "text": "Thread parent message",
            "timestamp": "2023-10-20T11:00:00Z",
            "thread_ts": "1697803600.000002",
            "is_thread_parent": True,
            "is_thread_reply": False,
            "reply_count": 2,
            "user_name": "bob",
            "user_real_name": "Bob Johnson",
            "user_email": "bob@example.com",
            "user_is_bot": False,
            "reactions": [{"emoji": "100", "count": 1, "users": ["U001"]}],
            "files": [],
            "jira_tickets": [],
            "has_reactions": True,
            "has_files": False,
            "has_thread": True,
        },
        {
            "message_id": "1697803700.000003",
            "user_id": "U001",
            "text": "Reply to thread",
            "timestamp": "2023-10-20T11:01:40Z",
            "thread_ts": "1697803600.000002",
            "is_thread_parent": False,
            "is_thread_reply": True,
            "reply_count": 0,
            "user_name": "alice",
            "user_real_name": "Alice Smith",
            "user_email": "alice@example.com",
            "user_is_bot": False,
            "reactions": [],
            "files": [],
            "jira_tickets": [],
            "has_reactions": False,
            "has_files": False,
            "has_thread": False,
        },
        {
            "message_id": "1697803800.000004",
            "user_id": "U003",
            "text": "Another reply mentioning PROJ-123",
            "timestamp": "2023-10-20T11:03:20Z",
            "thread_ts": "1697803600.000002",
            "is_thread_parent": False,
            "is_thread_reply": True,
            "reply_count": 0,
            "user_name": "charlie",
            "user_real_name": "Charlie Brown",
            "user_email": "charlie@example.com",
            "user_is_bot": False,
            "reactions": [],
            "files": [],
            "jira_tickets": ["PROJ-123"],
            "has_reactions": False,
            "has_files": False,
            "has_thread": False,
        },
    ]

    # Create test data for engineering channel - 2023-10-21
    engineering_data_oct21 = [
        {
            "message_id": "1697886400.000005",
            "user_id": "U002",
            "text": "Next day message",
            "timestamp": "2023-10-21T10:00:00Z",
            "thread_ts": None,
            "is_thread_parent": False,
            "is_thread_reply": False,
            "reply_count": 0,
            "user_name": "bob",
            "user_real_name": "Bob Johnson",
            "user_email": "bob@example.com",
            "user_is_bot": False,
            "reactions": [],
            "files": [],
            "jira_tickets": [],
            "has_reactions": False,
            "has_files": False,
            "has_thread": False,
        },
    ]

    # Create test data for design channel - 2023-10-20
    design_data_oct20 = [
        {
            "message_id": "1697800100.000006",
            "user_id": "U004",
            "text": "Design review meeting",
            "timestamp": "2023-10-20T10:01:40Z",
            "thread_ts": None,
            "is_thread_parent": False,
            "is_thread_reply": False,
            "reply_count": 0,
            "user_name": "diana",
            "user_real_name": "Diana Prince",
            "user_email": "diana@example.com",
            "user_is_bot": False,
            "reactions": [],
            "files": [{"id": "F123", "name": "mockup.png", "mimetype": "image/png", "url": "https://files.slack.com/F123", "size": 50000}],
            "jira_tickets": ["DESIGN-456"],
            "has_reactions": False,
            "has_files": True,
            "has_thread": False,
        },
    ]

    # Write Parquet files with partitioning
    def write_partition(channel: str, date: str, data: list):
        partition_dir = base_path / f"dt={date}" / f"channel={channel}"
        partition_dir.mkdir(parents=True, exist_ok=True)

        table = pa.Table.from_pylist(data, schema=schema)
        pq.write_table(table, partition_dir / "data.parquet", compression='snappy')

    write_partition("engineering", "2023-10-20", engineering_data_oct20)
    write_partition("engineering", "2023-10-21", engineering_data_oct21)
    write_partition("design", "2023-10-20", design_data_oct20)

    return str(base_path.parent.parent)  # Return base cache directory


class TestParquetMessageReaderBasics:
    """Test basic read operations"""

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_read_single_partition(self, sample_parquet_cache):
        """Test reading messages from a single channel/date partition"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel(channel="engineering", date="2023-10-20")

        assert isinstance(messages, list)
        assert len(messages) == 4  # 4 messages in engineering on 2023-10-20
        assert all(isinstance(msg, dict) for msg in messages)
        assert all("message_id" in msg for msg in messages)
        assert all("text" in msg for msg in messages)

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_messages_sorted_chronologically(self, sample_parquet_cache):
        """Test returned messages are sorted by timestamp"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel(channel="engineering", date="2023-10-20")

        timestamps = [msg["timestamp"] for msg in messages]
        assert timestamps == sorted(timestamps), "Messages should be sorted chronologically"

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_read_nonexistent_partition_returns_empty(self, sample_parquet_cache):
        """Test querying non-existent partition returns empty list"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel(channel="nonexistent", date="2020-01-01")

        assert messages == []

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_read_different_channel(self, sample_parquet_cache):
        """Test reading from different channel returns correct data"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel(channel="design", date="2023-10-20")

        assert len(messages) == 1
        assert messages[0]["user_real_name"] == "Diana Prince"
        assert messages[0]["has_files"] is True


class TestParquetMessageReaderDateRanges:
    """Test reading across date ranges"""

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_read_channel_date_range(self, sample_parquet_cache):
        """Test reading messages across multiple date partitions"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel_range(
            channel="engineering",
            start_date="2023-10-20",
            end_date="2023-10-21"
        )

        assert isinstance(messages, list)
        assert len(messages) == 5  # 4 from Oct 20 + 1 from Oct 21

        # Check messages from both dates are present
        dates = set(msg["timestamp"][:10] for msg in messages)
        assert "2023-10-20" in dates
        assert "2023-10-21" in dates

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_date_range_chronologically_sorted(self, sample_parquet_cache):
        """Test date range results are sorted chronologically across partitions"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel_range(
            channel="engineering",
            start_date="2023-10-20",
            end_date="2023-10-21"
        )

        timestamps = [msg["timestamp"] for msg in messages]
        assert timestamps == sorted(timestamps)

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_single_date_range(self, sample_parquet_cache):
        """Test date range with start=end returns same as single day"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel_range(
            channel="engineering",
            start_date="2023-10-20",
            end_date="2023-10-20"
        )

        assert len(messages) == 4  # Same as single partition read


class TestParquetMessageReaderMultiChannel:
    """Test reading from multiple channels"""

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_read_all_channels_single_date(self, sample_parquet_cache):
        """Test reading messages from all channels for a specific date"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_all_channels(date="2023-10-20")

        assert isinstance(messages, list)
        assert len(messages) == 5  # 4 from engineering + 1 from design

        # Verify messages from both channels present
        channels = set(msg.get("channel_name") for msg in messages if "channel_name" in msg)
        # Note: channel_name might need to be added by reader

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_multi_channel_chronologically_sorted(self, sample_parquet_cache):
        """Test multi-channel results are sorted chronologically"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_all_channels(date="2023-10-20")

        timestamps = [msg["timestamp"] for msg in messages]
        assert timestamps == sorted(timestamps)


class TestParquetMessageReaderDataIntegrity:
    """Test data integrity and field preservation"""

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_all_fields_preserved(self, sample_parquet_cache):
        """Test all message fields are preserved from Parquet"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel(channel="engineering", date="2023-10-20")

        # Check first message has all expected fields
        msg = messages[0]
        expected_fields = [
            "message_id", "user_id", "text", "timestamp",
            "thread_ts", "is_thread_parent", "is_thread_reply",
            "user_name", "user_real_name", "user_email", "user_is_bot",
            "reactions", "files", "jira_tickets",
            "has_reactions", "has_files", "has_thread"
        ]

        for field in expected_fields:
            assert field in msg, f"Missing field: {field}"

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_nested_arrays_preserved(self, sample_parquet_cache):
        """Test nested arrays (reactions, files, jira_tickets) are preserved"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel(channel="engineering", date="2023-10-20")

        # Find message with reactions
        msg_with_reactions = next(m for m in messages if m["has_reactions"])
        assert isinstance(msg_with_reactions["reactions"], list)
        assert len(msg_with_reactions["reactions"]) > 0
        assert "emoji" in msg_with_reactions["reactions"][0]

        # Find message with JIRA tickets
        msg_with_jira = next(m for m in messages if m["jira_tickets"])
        assert isinstance(msg_with_jira["jira_tickets"], list)
        assert "PROJ-123" in msg_with_jira["jira_tickets"]

    @pytest.mark.skipif(ParquetMessageReader is None, reason="ParquetMessageReader not implemented yet")
    def test_thread_flags_accurate(self, sample_parquet_cache):
        """Test thread flags are accurate"""
        reader = ParquetMessageReader(base_path=sample_parquet_cache)

        messages = reader.read_channel(channel="engineering", date="2023-10-20")

        # Find thread parent
        thread_parent = next(m for m in messages if m["is_thread_parent"])
        assert thread_parent["thread_ts"] == thread_parent["message_id"]
        assert thread_parent["is_thread_reply"] is False
        assert thread_parent["reply_count"] == 2

        # Find thread replies
        thread_replies = [m for m in messages if m["is_thread_reply"]]
        assert len(thread_replies) == 2
        for reply in thread_replies:
            assert reply["thread_ts"] == thread_parent["message_id"]
            assert reply["is_thread_parent"] is False
