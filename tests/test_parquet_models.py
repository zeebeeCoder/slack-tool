"""Unit tests for Parquet conversion methods - TDD approach

These tests are written FIRST and will FAIL until we implement:
- to_parquet_dict() methods on models
- Partition key generation utilities
"""

import pytest
from datetime import datetime
from tests.fixtures import (
    sample_user,
    sample_user_bot,
    sample_message_basic,
    sample_message_with_user_info,
    sample_message_with_reactions,
    sample_message_with_files,
    sample_message_with_jira,
    sample_message_thread_parent,
    sample_message_thread_reply,
    sample_jira_ticket_basic,
    sample_jira_ticket_full,
    sample_channel,
)


class TestSlackMessageParquet:
    """Test SlackMessage to Parquet conversion"""

    def test_basic_message_to_parquet_dict(self):
        """Test basic message converts to flat dict with required fields"""
        msg = sample_message_basic()

        # This will FAIL because to_parquet_dict() doesn't exist yet
        parquet_dict = msg.to_parquet_dict()

        # Verify required fields
        assert parquet_dict["message_id"] == "1697654321.123456"
        assert parquet_dict["user_id"] == "U012ABC3DEF"
        assert parquet_dict["text"] == "This is a simple test message"
        assert parquet_dict["timestamp"] is not None  # ISO format
        assert parquet_dict["is_thread_parent"] is False
        assert parquet_dict["is_thread_reply"] is False

    def test_nested_user_info_flattened(self):
        """Test user_info nested object gets flattened to user_* fields"""
        msg = sample_message_with_user_info()

        parquet_dict = msg.to_parquet_dict()

        # User info should be flattened
        assert parquet_dict["user_id"] == "U012ABC3DEF"
        assert parquet_dict["user_name"] == "john.doe"
        assert parquet_dict["user_real_name"] == "John Doe"
        assert parquet_dict["user_email"] == "john.doe@example.com"
        assert parquet_dict["user_is_bot"] is False

    def test_reactions_array_preserved(self):
        """Test reactions list converts to Parquet-compatible list of dicts"""
        msg = sample_message_with_reactions()

        parquet_dict = msg.to_parquet_dict()

        # Reactions should be preserved as list
        assert "reactions" in parquet_dict
        assert isinstance(parquet_dict["reactions"], list)
        assert len(parquet_dict["reactions"]) == 2

        # Check first reaction structure
        reaction = parquet_dict["reactions"][0]
        assert reaction["emoji"] == "100"
        assert reaction["count"] == 2
        assert isinstance(reaction["users"], list)

    def test_files_array_preserved(self):
        """Test files list converts to Parquet-compatible format"""
        msg = sample_message_with_files()

        parquet_dict = msg.to_parquet_dict()

        assert "files" in parquet_dict
        assert isinstance(parquet_dict["files"], list)
        assert len(parquet_dict["files"]) == 1

        # Check file structure
        file_dict = parquet_dict["files"][0]
        assert file_dict["id"] == "F1234567890"
        assert file_dict["name"] == "screenshot.png"
        assert file_dict["mimetype"] == "image/png"

    def test_jira_tickets_extracted_to_array(self):
        """Test JIRA ticket IDs extracted from text to array"""
        msg = sample_message_with_jira()

        parquet_dict = msg.to_parquet_dict()

        # JIRA tickets should be extracted and stored as array
        assert "jira_tickets" in parquet_dict
        assert isinstance(parquet_dict["jira_tickets"], list)
        # Should extract PROJ-123, PROJ-456, PROJ-789
        assert "PROJ-123" in parquet_dict["jira_tickets"]
        assert "PROJ-456" in parquet_dict["jira_tickets"]
        assert "PROJ-789" in parquet_dict["jira_tickets"]

    def test_timestamp_conversion_to_iso(self):
        """Test Slack timestamp converts to ISO 8601 datetime string"""
        msg = sample_message_basic()

        parquet_dict = msg.to_parquet_dict()

        # Timestamp should be ISO format string
        assert "timestamp" in parquet_dict
        timestamp_str = parquet_dict["timestamp"]
        assert isinstance(timestamp_str, str)

        # Should be parseable as ISO datetime
        parsed = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        assert isinstance(parsed, datetime)

    def test_thread_parent_flags(self):
        """Test thread parent message has correct flags"""
        msg = sample_message_thread_parent()

        parquet_dict = msg.to_parquet_dict()

        assert parquet_dict["is_thread_parent"] is True
        assert parquet_dict["is_thread_reply"] is False
        assert parquet_dict["thread_ts"] == "1697654321.123456"
        assert parquet_dict["reply_count"] == 2

    def test_thread_reply_flags(self):
        """Test thread reply message has correct flags"""
        msg = sample_message_thread_reply()

        parquet_dict = msg.to_parquet_dict()

        assert parquet_dict["is_thread_parent"] is False
        assert parquet_dict["is_thread_reply"] is True
        assert parquet_dict["thread_ts"] == "1697654321.123456"  # Parent ts
        assert parquet_dict["message_id"] == "1697654400.123457"  # Reply ts

    def test_missing_optional_fields_handled(self):
        """Test that missing optional fields don't cause errors"""
        msg = sample_message_basic()  # Has minimal fields

        parquet_dict = msg.to_parquet_dict()

        # Optional fields should have null/default values
        assert parquet_dict.get("user_real_name") is None
        assert parquet_dict.get("user_email") is None
        assert parquet_dict.get("reactions") == [] or parquet_dict.get("reactions") is None
        assert parquet_dict.get("files") == [] or parquet_dict.get("files") is None

    def test_boolean_flags_present(self):
        """Test boolean flags for filtering are included"""
        msg = sample_message_with_files()

        parquet_dict = msg.to_parquet_dict()

        # Useful boolean flags for queries
        assert "has_reactions" in parquet_dict
        assert "has_files" in parquet_dict
        assert "has_thread" in parquet_dict
        assert parquet_dict["has_files"] is True


class TestJiraTicketParquet:
    """Test JiraTicket to Parquet conversion"""

    def test_basic_jira_ticket_to_parquet_dict(self):
        """Test basic JIRA ticket conversion"""
        ticket = sample_jira_ticket_basic()

        parquet_dict = ticket.to_parquet_dict()

        assert parquet_dict["ticket_id"] == "PROJ-123"
        assert parquet_dict["summary"] == "Fix login bug"
        assert parquet_dict["status"] == "In Progress"
        assert parquet_dict["priority"] == "High"
        assert parquet_dict["assignee"] == "john.doe@example.com"

    def test_jira_arrays_preserved(self):
        """Test JIRA ticket arrays (blocks, depends_on) preserved"""
        ticket = sample_jira_ticket_full()

        parquet_dict = ticket.to_parquet_dict()

        # Arrays should be preserved
        assert parquet_dict["blocks"] == ["PROJ-789"]
        assert parquet_dict["blocked_by"] == ["PROJ-100"]
        assert "PROJ-200" in parquet_dict["depends_on"]
        assert "PROJ-300" in parquet_dict["depends_on"]

    def test_nested_progress_flattened(self):
        """Test JiraProgress nested object gets flattened"""
        ticket = sample_jira_ticket_full()

        parquet_dict = ticket.to_parquet_dict()

        # Progress fields should be flattened
        assert parquet_dict["progress_total"] == 100
        assert parquet_dict["progress_done"] == 65
        assert parquet_dict["progress_percentage"] == 65.0

    def test_nested_sprints_preserved(self):
        """Test sprints list preserved as array of dicts"""
        ticket = sample_jira_ticket_full()

        parquet_dict = ticket.to_parquet_dict()

        assert "sprints" in parquet_dict
        assert isinstance(parquet_dict["sprints"], list)
        assert len(parquet_dict["sprints"]) == 1
        assert parquet_dict["sprints"][0]["name"] == "Sprint 42"

    def test_comments_dict_preserved(self):
        """Test comments dict (user -> count) preserved"""
        ticket = sample_jira_ticket_full()

        parquet_dict = ticket.to_parquet_dict()

        assert "comments" in parquet_dict
        assert parquet_dict["comments"]["john.doe"] == 3
        assert parquet_dict["comments"]["jane.smith"] == 2
        assert parquet_dict["total_comments"] == 5


class TestSlackUserParquet:
    """Test SlackUser to Parquet conversion"""

    def test_user_to_parquet_dict(self):
        """Test user conversion"""
        user = sample_user()

        parquet_dict = user.to_parquet_dict()

        assert parquet_dict["user_id"] == "U012ABC3DEF"
        assert parquet_dict["user_name"] == "john.doe"
        assert parquet_dict["real_name"] == "John Doe"
        assert parquet_dict["email"] == "john.doe@example.com"
        assert parquet_dict["is_bot"] is False

    def test_bot_user_flag(self):
        """Test bot user has is_bot = True"""
        bot = sample_user_bot()

        parquet_dict = bot.to_parquet_dict()

        assert parquet_dict["is_bot"] is True
        assert parquet_dict["user_name"] == "deploybot"


class TestSlackThreadParquet:
    """Test SlackThread to Parquet conversion"""

    def test_thread_to_parquet_dict(self):
        """Test thread summary extracted"""
        msg = sample_message_thread_parent()
        thread = msg.thread

        parquet_dict = thread.to_parquet_dict()

        assert parquet_dict["thread_id"] == "1697654321.123456"
        assert parquet_dict["reply_count"] == 2
        assert parquet_dict["participant_count"] == 2
        assert "John Doe" in parquet_dict["participants"]
        assert "PROJ-123" in parquet_dict["jira_tickets"]

    def test_thread_duration_calculated(self):
        """Test thread duration in minutes calculated"""
        msg = sample_message_thread_parent()
        thread = msg.thread

        parquet_dict = thread.to_parquet_dict()

        assert "duration_minutes" in parquet_dict
        assert parquet_dict["duration_minutes"] > 0


class TestParquetPartitioning:
    """Test partition key and path generation"""

    def test_partition_key_generation(self):
        """Test generating partition key from timestamp and channel"""
        from slack_intel.parquet_utils import generate_partition_key

        timestamp = "1697654321.123456"  # 2023-10-18
        channel_id = "C9876543210"
        channel_name = "engineering"

        partition_key = generate_partition_key(timestamp, channel_id, channel_name)

        # Expected format: dt=2023-10-18/channel=engineering
        assert partition_key == "dt=2023-10-18/channel=engineering"

    def test_partition_path_creation(self):
        """Test creating full partition path"""
        from slack_intel.parquet_utils import get_partition_path

        base_path = "cache/raw/messages"
        partition_key = "dt=2023-10-18/channel=engineering"

        full_path = get_partition_path(base_path, partition_key)

        expected = "cache/raw/messages/dt=2023-10-18/channel=engineering/data.parquet"
        assert full_path == expected

    def test_date_extraction_from_slack_timestamp(self):
        """Test extracting YYYY-MM-DD from Slack timestamp"""
        from slack_intel.parquet_utils import extract_date_from_slack_ts

        timestamp = "1697654321.123456"  # 2023-10-18 17:38:41 UTC

        date_str = extract_date_from_slack_ts(timestamp)

        assert date_str == "2023-10-18"

    def test_multiple_messages_same_partition(self):
        """Test messages from same day/channel get same partition key"""
        from slack_intel.parquet_utils import generate_partition_key

        # Two messages on same day, same channel
        ts1 = "1697654321.123456"  # 2023-10-18 17:38 UTC
        ts2 = "1697660000.999999"  # 2023-10-18 19:13 UTC (still same day)
        channel_id = "C9876543210"
        channel_name = "engineering"

        partition1 = generate_partition_key(ts1, channel_id, channel_name)
        partition2 = generate_partition_key(ts2, channel_id, channel_name)

        assert partition1 == partition2  # Should be same partition

    def test_different_channels_different_partitions(self):
        """Test messages in different channels get different partition keys"""
        from slack_intel.parquet_utils import generate_partition_key

        timestamp = "1697654321.123456"

        partition1 = generate_partition_key(timestamp, "C9876543210", "engineering")
        partition2 = generate_partition_key(timestamp, "C1111111111", "random")

        assert partition1 != partition2  # Different channels
        assert "engineering" in partition1
        assert "random" in partition2


class TestParquetSchemaValidation:
    """Test Parquet schema adheres to expected structure"""

    def test_all_required_fields_present(self):
        """Test all required fields are in Parquet dict"""
        msg = sample_message_with_user_info()

        parquet_dict = msg.to_parquet_dict()

        required_fields = [
            "message_id",
            "user_id",
            "text",
            "timestamp",
            "is_thread_parent",
            "is_thread_reply",
        ]

        for field in required_fields:
            assert field in parquet_dict, f"Missing required field: {field}"

    def test_no_nested_objects_in_output(self):
        """Test that output doesn't contain nested Pydantic objects"""
        msg = sample_message_with_user_info()

        parquet_dict = msg.to_parquet_dict()

        # All values should be primitives, lists, or dicts (no Pydantic models)
        for key, value in parquet_dict.items():
            if value is not None:
                assert not hasattr(value, "model_dump"), \
                    f"Field '{key}' contains nested Pydantic model: {type(value)}"

    def test_array_fields_are_lists(self):
        """Test array fields are actual Python lists"""
        msg = sample_message_with_reactions()

        parquet_dict = msg.to_parquet_dict()

        # Array fields
        assert isinstance(parquet_dict.get("reactions", []), list)
        assert isinstance(parquet_dict.get("files", []), list)
        assert isinstance(parquet_dict.get("jira_tickets", []), list)
