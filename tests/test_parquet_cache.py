"""Unit tests for ParquetCache - TDD approach

These tests are written FIRST and will FAIL until we implement:
- ParquetCache class
- save_messages() method
- PyArrow schema handling
"""

import pytest
from pathlib import Path
import shutil
from tests.fixtures import (
    sample_message_basic,
    sample_message_with_user_info,
    sample_message_with_reactions,
    sample_message_with_files,
    sample_message_with_jira,
    sample_channel,
    sample_jira_ticket_basic,
    sample_jira_ticket_full,
)


class TestParquetCacheInitialization:
    """Test ParquetCache initialization"""

    def test_cache_initialization(self, tmp_path):
        """Test creating ParquetCache with base path"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(tmp_path / "cache"))

        assert cache.base_path == str(tmp_path / "cache")
        assert hasattr(cache, "save_messages")

    def test_cache_default_path(self):
        """Test default cache path"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache()

        assert cache.base_path == "cache/raw"


class TestParquetCacheSaveMessages:
    """Test saving messages to Parquet"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup and cleanup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        yield
        # Cleanup after each test
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_save_single_message(self):
        """Test saving a single message to Parquet"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        msg = sample_message_basic()
        channel = sample_channel()

        # Save message
        file_path = cache.save_messages([msg], channel, "2023-10-18")

        # Verify file was created
        assert Path(file_path).exists()
        assert "dt=2023-10-18" in file_path
        assert "channel=engineering" in file_path
        assert file_path.endswith(".parquet")

    def test_save_multiple_messages_same_partition(self):
        """Test saving multiple messages to same partition"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        messages = [
            sample_message_basic(),
            sample_message_with_user_info(),
            sample_message_with_reactions(),
        ]
        channel = sample_channel()

        file_path = cache.save_messages(messages, channel, "2023-10-18")

        # Should create single file
        assert Path(file_path).exists()

        # Verify can read with pyarrow
        import pyarrow.parquet as pq
        table = pq.read_table(file_path)

        # Should have 3 rows
        assert table.num_rows == 3

    def test_save_messages_different_channels(self):
        """Test saving messages from different channels"""
        from slack_intel.parquet_cache import ParquetCache
        from slack_intel import SlackChannel

        cache = ParquetCache(base_path=str(self.cache_dir))

        channel1 = SlackChannel(name="engineering", id="C9876543210")
        channel2 = SlackChannel(name="random", id="C1111111111")

        file1 = cache.save_messages([sample_message_basic()], channel1, "2023-10-18")
        file2 = cache.save_messages([sample_message_basic()], channel2, "2023-10-18")

        # Different channels = different partition paths
        assert "channel=engineering" in file1
        assert "channel=random" in file2
        assert Path(file1).exists()
        assert Path(file2).exists()

    def test_save_messages_different_dates(self):
        """Test saving messages from different dates"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        file1 = cache.save_messages([sample_message_basic()], channel, "2023-10-18")
        file2 = cache.save_messages([sample_message_basic()], channel, "2023-10-19")

        # Different dates = different partition paths
        assert "dt=2023-10-18" in file1
        assert "dt=2023-10-19" in file2
        assert Path(file1).exists()
        assert Path(file2).exists()

    def test_overwrite_existing_partition(self):
        """Test overwriting existing partition"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Write first batch
        messages1 = [sample_message_basic()]
        file1 = cache.save_messages(messages1, channel, "2023-10-18")

        # Read and verify 1 row
        import pyarrow.parquet as pq
        table1 = pq.read_table(file1)
        assert table1.num_rows == 1

        # Overwrite with different batch
        messages2 = [
            sample_message_with_user_info(),
            sample_message_with_reactions(),
        ]
        file2 = cache.save_messages(messages2, channel, "2023-10-18")

        # Should be same file path
        assert file1 == file2

        # Should have 2 rows (overwritten)
        table2 = pq.read_table(file2)
        assert table2.num_rows == 2

    def test_directory_creation(self):
        """Test that directories are created automatically"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Directory shouldn't exist yet
        partition_dir = self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering"
        assert not partition_dir.exists()

        # Save message
        cache.save_messages([sample_message_basic()], channel, "2023-10-18")

        # Directory should now exist
        assert partition_dir.exists()
        assert (partition_dir / "data.parquet").exists()


class TestParquetCacheSchema:
    """Test PyArrow schema generation and validation"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_parquet_schema_correct(self):
        """Test that Parquet schema matches expected structure"""
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        msg = sample_message_with_user_info()
        channel = sample_channel()

        file_path = cache.save_messages([msg], channel, "2023-10-18")

        # Read schema
        table = pq.read_table(file_path)
        schema = table.schema

        # Verify required fields exist
        required_fields = [
            "message_id",
            "user_id",
            "text",
            "timestamp",
            "is_thread_parent",
            "is_thread_reply",
            "user_name",
            "user_real_name",
            "reactions",
            "files",
            "jira_tickets",
        ]

        schema_names = [field.name for field in schema]
        for field_name in required_fields:
            assert field_name in schema_names, f"Missing field: {field_name}"

    def test_nested_types_preserved(self):
        """Test that nested types (reactions, files) are preserved correctly"""
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        msg = sample_message_with_reactions()
        channel = sample_channel()

        file_path = cache.save_messages([msg], channel, "2023-10-18")

        # Read data
        table = pq.read_table(file_path)
        data = table.to_pylist()

        # Verify reactions structure
        assert len(data) == 1
        assert "reactions" in data[0]
        assert isinstance(data[0]["reactions"], list)
        assert len(data[0]["reactions"]) == 2  # sample has 2 reactions

        # Verify first reaction structure
        reaction = data[0]["reactions"][0]
        assert "emoji" in reaction
        assert "count" in reaction
        assert "users" in reaction

    def test_all_message_types_supported(self):
        """Test that all message types can be saved"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Try different message types
        messages = [
            sample_message_basic(),
            sample_message_with_user_info(),
            sample_message_with_reactions(),
            sample_message_with_files(),
            sample_message_with_jira(),
        ]

        # Should not raise any errors
        file_path = cache.save_messages(messages, channel, "2023-10-18")

        import pyarrow.parquet as pq
        table = pq.read_table(file_path)
        assert table.num_rows == 5


class TestParquetCacheEdgeCases:
    """Test edge cases and error handling"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_save_empty_message_list(self):
        """Test saving empty message list"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Should handle empty list gracefully
        file_path = cache.save_messages([], channel, "2023-10-18")

        # File should either not exist or be empty
        if Path(file_path).exists():
            import pyarrow.parquet as pq
            table = pq.read_table(file_path)
            assert table.num_rows == 0

    def test_save_message_with_null_fields(self):
        """Test saving message with many null fields"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Basic message has minimal fields
        msg = sample_message_basic()

        # Should handle null user_info gracefully
        file_path = cache.save_messages([msg], channel, "2023-10-18")

        import pyarrow.parquet as pq
        table = pq.read_table(file_path)
        data = table.to_pylist()

        # Null fields should be None
        assert data[0]["user_real_name"] is None
        assert data[0]["user_email"] is None

    def test_date_validation(self):
        """Test that invalid dates are handled"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Date should be YYYY-MM-DD format
        with pytest.raises((ValueError, AssertionError)):
            cache.save_messages([sample_message_basic()], channel, "invalid-date")


class TestParquetCacheJiraTickets:
    """Test saving JIRA tickets to Parquet"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup and cleanup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_save_single_jira_ticket(self):
        """Test saving a single JIRA ticket to Parquet"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        ticket = sample_jira_ticket_basic()

        # Save JIRA ticket
        file_path = cache.save_jira_tickets([ticket], "2023-10-18")

        # Verify file was created
        assert Path(file_path).exists()
        assert "jira/dt=2023-10-18" in file_path
        assert file_path.endswith(".parquet")

    def test_save_multiple_jira_tickets(self):
        """Test saving multiple JIRA tickets to Parquet"""
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        tickets = [
            sample_jira_ticket_basic(),
            sample_jira_ticket_full(),
        ]

        file_path = cache.save_jira_tickets(tickets, "2023-10-18")

        # Verify file and row count
        assert Path(file_path).exists()
        table = pq.read_table(file_path)
        assert table.num_rows == 2

    def test_jira_partition_by_date(self):
        """Test that JIRA tickets are partitioned by date"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        ticket = sample_jira_ticket_basic()

        file1 = cache.save_jira_tickets([ticket], "2023-10-18")
        file2 = cache.save_jira_tickets([ticket], "2023-10-19")

        # Different dates = different partition paths
        assert "dt=2023-10-18" in file1
        assert "dt=2023-10-19" in file2
        assert Path(file1).exists()
        assert Path(file2).exists()

    def test_jira_cached_at_timestamp_added(self):
        """Test that cached_at timestamp is added automatically"""
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq
        from datetime import datetime

        cache = ParquetCache(base_path=str(self.cache_dir))
        ticket = sample_jira_ticket_basic()

        before = datetime.utcnow()
        file_path = cache.save_jira_tickets([ticket], "2023-10-18")
        after = datetime.utcnow()

        # Read data and verify cached_at exists
        table = pq.read_table(file_path)
        data = table.to_pylist()

        assert len(data) == 1
        assert "cached_at" in data[0]
        assert data[0]["cached_at"] is not None

        # Verify timestamp is within reasonable range
        cached_at = data[0]["cached_at"]
        assert before <= cached_at <= after

    def test_jira_schema_correct(self):
        """Test that JIRA Parquet schema matches expected structure"""
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        ticket = sample_jira_ticket_full()

        file_path = cache.save_jira_tickets([ticket], "2023-10-18")

        # Read schema
        table = pq.read_table(file_path)
        schema = table.schema

        # Verify required fields exist
        required_fields = [
            "ticket_id",
            "summary",
            "priority",
            "issue_type",
            "status",
            "assignee",
            "due_date",
            "story_points",
            "blocks",
            "blocked_by",
            "components",
            "labels",
            "progress_total",
            "progress_done",
            "progress_percentage",
            "project",
            "sprints",
            "cached_at",
        ]

        schema_names = [field.name for field in schema]
        for field_name in required_fields:
            assert field_name in schema_names, f"Missing field: {field_name}"

    def test_jira_nested_types_preserved(self):
        """Test that nested JIRA types (sprints, dependencies) are preserved"""
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        ticket = sample_jira_ticket_full()

        file_path = cache.save_jira_tickets([ticket], "2023-10-18")

        # Read data
        table = pq.read_table(file_path)
        data = table.to_pylist()

        assert len(data) == 1
        row = data[0]

        # Verify sprints structure (list of structs)
        assert "sprints" in row
        assert isinstance(row["sprints"], list)
        if len(row["sprints"]) > 0:
            sprint = row["sprints"][0]
            assert "name" in sprint
            assert "state" in sprint

        # Verify dependencies are lists
        assert isinstance(row["blocks"], list)
        assert isinstance(row["blocked_by"], list)
        assert isinstance(row["components"], list)

    def test_save_empty_jira_ticket_list(self):
        """Test saving empty JIRA ticket list"""
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))

        # Should handle empty list gracefully
        file_path = cache.save_jira_tickets([], "2023-10-18")

        # File should exist but be empty
        assert Path(file_path).exists()
        table = pq.read_table(file_path)
        assert table.num_rows == 0

    def test_jira_overwrite_existing_partition(self):
        """Test overwriting existing JIRA partition"""
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))

        # Write first batch
        tickets1 = [sample_jira_ticket_basic()]
        file1 = cache.save_jira_tickets(tickets1, "2023-10-18")

        # Verify 1 row
        table1 = pq.read_table(file1)
        assert table1.num_rows == 1

        # Overwrite with different batch
        tickets2 = [
            sample_jira_ticket_basic(),
            sample_jira_ticket_full(),
        ]
        file2 = cache.save_jira_tickets(tickets2, "2023-10-18")

        # Should be same file path
        assert file1 == file2

        # Should have 2 rows (overwritten)
        table2 = pq.read_table(file2)
        assert table2.num_rows == 2

    def test_jira_date_validation(self):
        """Test that invalid dates are rejected for JIRA tickets"""
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        ticket = sample_jira_ticket_basic()

        # Date should be YYYY-MM-DD format
        with pytest.raises((ValueError, AssertionError)):
            cache.save_jira_tickets([ticket], "invalid-date")
