"""TDD Test Suite for Idempotent Parquet Caching

This test suite defines the DESIRED behavior for cache operations:
- No data loss on overlapping cache runs
- No data duplication (exactly-once semantics)
- Idempotent operations (same input → same output)
- Proper merge semantics (upsert, not overwrite)

These tests will FAIL until we implement merge-based caching.

Terminology:
- Idempotency: Running cache multiple times = same result
- Exactly-once: Each message appears exactly once (no dupes, no loss)
- Upsert: Update existing OR insert new (merge semantics)
- Deduplication: Using message_id to identify unique messages
- Data Integrity: Cache accurately reflects Slack state
"""

import pytest
from pathlib import Path
import shutil
from datetime import datetime, timedelta
from tests.fixtures import sample_channel
from slack_intel import SlackMessage


class TestIdempotentCaching:
    """Test that cache operations are idempotent (safe to repeat)"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup and cleanup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_idempotent_full_recache_same_data(self):
        """Running cache with same date range twice should produce identical result

        Data Integrity Principle: Idempotency
        - Cache same period twice → same data
        - No duplicates, no data loss
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Create 5 messages for 2023-10-18
        messages_batch1 = [
            SlackMessage(
                ts=f"1697635200.{i:06d}",  # 2023-10-18 timestamp
                text=f"Message {i}",
                user_id=f"U{i}",
            )
            for i in range(5)
        ]

        # First cache run
        file_path = cache.save_messages(messages_batch1, channel, "2023-10-18")
        table1 = pq.read_table(file_path)

        # Second cache run (exact same data)
        file_path = cache.save_messages(messages_batch1, channel, "2023-10-18")
        table2 = pq.read_table(file_path)

        # REQUIREMENT: Idempotency
        assert table1.num_rows == table2.num_rows == 5
        assert table1.to_pydict() == table2.to_pydict()

    def test_overlapping_cache_preserves_existing_messages(self):
        """Overlapping cache runs should preserve all unique messages

        Data Integrity Principle: No Data Loss
        - Run 1: Cache full day (100 messages)
        - Run 2: Cache half day overlap (50 messages, 20 are new)
        - Result: 120 total messages (100 + 20 new, no loss)
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Run 1: Cache full day with 100 messages
        messages_run1 = [
            SlackMessage(
                ts=f"1697635200.{i:06d}",
                text=f"Message {i}",
                user_id=f"U{i}",
            )
            for i in range(100)
        ]
        cache.save_messages(messages_run1, channel, "2023-10-18")

        # Run 2: Overlapping cache with 50 messages
        # - First 30 overlap with run 1 (ts 0-29)
        # - Last 20 are new (ts 100-119)
        messages_run2 = [
            SlackMessage(
                ts=f"1697635200.{i:06d}",
                text=f"Message {i}",
                user_id=f"U{i}",
            )
            for i in list(range(30)) + list(range(100, 120))
        ]
        cache.save_messages(messages_run2, channel, "2023-10-18")

        # REQUIREMENT: No data loss - should have 120 unique messages
        table = pq.read_table(cache.save_messages([], channel, "2023-10-18"))

        # This will FAIL with current implementation (overwrites to 50)
        # DESIRED: 120 messages (all unique, merged)
        assert table.num_rows == 120, \
            f"Expected 120 unique messages (100 original + 20 new), got {table.num_rows}"

    def test_no_duplicates_on_overlapping_cache(self):
        """Overlapping cache runs should not create duplicate messages

        Data Integrity Principle: Exactly-Once Semantics
        - Same message_id should appear exactly once
        - Deduplication by message_id (ts field)
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Create messages with specific IDs
        messages_set1 = [
            SlackMessage(ts="1697635200.000001", text="Msg 1", user_id="U1"),
            SlackMessage(ts="1697635200.000002", text="Msg 2", user_id="U1"),
            SlackMessage(ts="1697635200.000003", text="Msg 3", user_id="U1"),
        ]

        # Cache first set
        cache.save_messages(messages_set1, channel, "2023-10-18")

        # Cache overlapping set (msg 2, 3, 4)
        messages_set2 = [
            SlackMessage(ts="1697635200.000002", text="Msg 2", user_id="U1"),  # Duplicate!
            SlackMessage(ts="1697635200.000003", text="Msg 3", user_id="U1"),  # Duplicate!
            SlackMessage(ts="1697635200.000004", text="Msg 4", user_id="U1"),  # New
        ]

        cache.save_messages(messages_set2, channel, "2023-10-18")

        # REQUIREMENT: Exactly-once semantics
        # Should have 4 unique messages (1, 2, 3, 4) - NO duplicates
        table = pq.read_table(
            str(self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering" / "data.parquet")
        )
        data = table.to_pydict()

        # Verify exactly 4 unique messages
        assert table.num_rows == 4, \
            f"Expected 4 unique messages, got {table.num_rows}"

        # Verify unique message IDs
        message_ids = data['message_id']
        unique_ids = set(message_ids)
        assert len(unique_ids) == 4, \
            f"Expected 4 unique message IDs, got {len(unique_ids)}"

    def test_partial_day_cache_preserves_earlier_messages(self):
        """Caching partial day (e.g., last 0.5 day) should not lose earlier messages

        Real-world scenario:
        - Morning: Cache full day (messages from 00:00-23:59)
        - Afternoon: Cache last 12 hours (messages from 12:00-23:59)
        - Expected: All messages preserved
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Morning cache: Messages from 00:00 to 23:59
        morning_messages = [
            SlackMessage(
                ts=f"1697635200.{i:06d}",  # Early timestamps
                text=f"Morning msg {i}",
                user_id="U1",
            )
            for i in range(50)  # Messages 0-49
        ]
        cache.save_messages(morning_messages, channel, "2023-10-18")

        # Afternoon cache: Messages from 12:00 onwards (partial overlap)
        # Simulates: --days 0.5 run
        afternoon_messages = [
            SlackMessage(
                ts=f"1697635200.{i:06d}",
                text=f"Afternoon msg {i}",
                user_id="U1",
            )
            for i in range(25, 75)  # Messages 25-74 (overlaps 25-49, new 50-74)
        ]
        cache.save_messages(afternoon_messages, channel, "2023-10-18")

        # REQUIREMENT: No data loss from morning run
        table = pq.read_table(
            str(self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering" / "data.parquet")
        )

        # Should have 75 unique messages (0-74)
        # Current implementation: Only 50 (overwrites to 25-74, losing 0-24)
        assert table.num_rows == 75, \
            f"Expected 75 messages (morning + afternoon), got {table.num_rows}"


class TestUpsertSemantics:
    """Test upsert (update + insert) merge semantics"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_upsert_inserts_new_messages(self):
        """New messages should be inserted into existing partition

        Data Integrity Principle: Incremental Processing
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Initial cache: 3 messages
        initial_messages = [
            SlackMessage(ts="1697635200.000001", text="Msg 1", user_id="U1"),
            SlackMessage(ts="1697635200.000002", text="Msg 2", user_id="U1"),
            SlackMessage(ts="1697635200.000003", text="Msg 3", user_id="U1"),
        ]
        cache.save_messages(initial_messages, channel, "2023-10-18")

        # Incremental cache: 2 new messages
        new_messages = [
            SlackMessage(ts="1697635200.000004", text="Msg 4", user_id="U1"),
            SlackMessage(ts="1697635200.000005", text="Msg 5", user_id="U1"),
        ]
        cache.save_messages(new_messages, channel, "2023-10-18")

        # REQUIREMENT: Upsert - should insert new messages
        table = pq.read_table(
            str(self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering" / "data.parquet")
        )
        assert table.num_rows == 5, \
            f"Expected 5 messages after upsert, got {table.num_rows}"

    def test_upsert_updates_existing_messages(self):
        """Updated messages (same ID, new content) should update existing

        Use case: Thread parent gets updated with reply_count
        - Message written with reply_count=0
        - Reply added, message updated with reply_count=1
        - Cache should reflect latest state
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Initial: Thread parent with no replies
        initial_message = SlackMessage(
            ts="1697635200.000001",
            text="Thread parent",
            user="U1",
            replies_count=0,  # Use correct field name
        )
        cache.save_messages([initial_message], channel, "2023-10-18")

        # Update: Thread parent now has 3 replies
        updated_message = SlackMessage(
            ts="1697635200.000001",  # SAME ID
            text="Thread parent",
            user="U1",
            replies_count=3,  # UPDATED
        )
        cache.save_messages([updated_message], channel, "2023-10-18")

        # REQUIREMENT: Upsert - should update existing message
        table = pq.read_table(
            str(self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering" / "data.parquet")
        )
        data = table.to_pydict()

        # Should still have 1 message (not 2)
        assert table.num_rows == 1

        # Should have updated replies_count
        assert data['reply_count'][0] == 3, \
            f"Expected reply_count=3, got {data['reply_count'][0]}"

    def test_upsert_preserves_unaffected_messages(self):
        """Upsert should not touch messages not in the new batch

        Data Integrity Principle: Surgical Updates
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Initial: 10 messages
        initial_messages = [
            SlackMessage(
                ts=f"1697635200.{i:06d}",
                text=f"Original msg {i}",
                user_id="U1",
            )
            for i in range(10)
        ]
        cache.save_messages(initial_messages, channel, "2023-10-18")

        # Update: Only update message 5
        update_batch = [
            SlackMessage(
                ts="1697635200.000005",
                text="UPDATED msg 5",  # Changed
                user_id="U1",
            )
        ]
        cache.save_messages(update_batch, channel, "2023-10-18")

        # REQUIREMENT: Messages 0-4, 6-9 unchanged
        table = pq.read_table(
            str(self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering" / "data.parquet")
        )
        data = table.to_pydict()

        # Still 10 messages
        assert table.num_rows == 10

        # Message 5 updated
        msg_5_idx = [i for i, ts in enumerate(data['message_id']) if ts == "1697635200.000005"][0]
        assert "UPDATED" in data['text'][msg_5_idx]

        # Message 4 unchanged
        msg_4_idx = [i for i, ts in enumerate(data['message_id']) if ts == "1697635200.000004"][0]
        assert data['text'][msg_4_idx] == "Original msg 4"


class TestDeduplication:
    """Test message deduplication by message_id"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_deduplicate_by_message_id(self):
        """Messages with same message_id (ts) should be deduplicated

        Data Integrity Principle: Primary Key Enforcement
        - message_id is the unique identifier
        - Same ID = same message (keep one, discard duplicate)
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Batch with duplicate message IDs
        messages = [
            SlackMessage(ts="1697635200.000001", text="First version", user_id="U1"),
            SlackMessage(ts="1697635200.000002", text="Unique message", user_id="U1"),
            SlackMessage(ts="1697635200.000001", text="Duplicate ID!", user_id="U1"),  # Duplicate!
        ]

        cache.save_messages(messages, channel, "2023-10-18")

        # REQUIREMENT: Deduplication
        table = pq.read_table(
            str(self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering" / "data.parquet")
        )
        data = table.to_pydict()

        # Should have 2 unique messages (not 3)
        assert table.num_rows == 2

        # Should have 2 unique IDs
        unique_ids = set(data['message_id'])
        assert len(unique_ids) == 2

    def test_deduplicate_across_multiple_cache_runs(self):
        """Deduplication should work across separate cache operations

        Real scenario: API returns same message in multiple paginated responses
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Run 1: Messages 1, 2, 3
        batch1 = [
            SlackMessage(ts="1697635200.000001", text="Msg 1", user_id="U1"),
            SlackMessage(ts="1697635200.000002", text="Msg 2", user_id="U1"),
            SlackMessage(ts="1697635200.000003", text="Msg 3", user_id="U1"),
        ]
        cache.save_messages(batch1, channel, "2023-10-18")

        # Run 2: Messages 2, 3, 4 (overlapping)
        batch2 = [
            SlackMessage(ts="1697635200.000002", text="Msg 2", user_id="U1"),  # Duplicate
            SlackMessage(ts="1697635200.000003", text="Msg 3", user_id="U1"),  # Duplicate
            SlackMessage(ts="1697635200.000004", text="Msg 4", user_id="U1"),  # New
        ]
        cache.save_messages(batch2, channel, "2023-10-18")

        # Run 3: Messages 1, 4 (non-contiguous)
        batch3 = [
            SlackMessage(ts="1697635200.000001", text="Msg 1", user_id="U1"),  # Duplicate
            SlackMessage(ts="1697635200.000004", text="Msg 4", user_id="U1"),  # Duplicate
        ]
        cache.save_messages(batch3, channel, "2023-10-18")

        # REQUIREMENT: Only 4 unique messages total
        table = pq.read_table(
            str(self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering" / "data.parquet")
        )

        assert table.num_rows == 4, \
            f"Expected 4 unique messages across all runs, got {table.num_rows}"


class TestDataIntegrityEdgeCases:
    """Test edge cases for data integrity"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_empty_cache_run_preserves_existing_data(self):
        """Caching with empty result should not delete existing data

        Scenario: API returns 0 messages (rate limit, network error, etc.)
        Expected: Existing cache preserved
        """
        from slack_intel.parquet_cache import ParquetCache
        import pyarrow.parquet as pq

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Initial cache with data
        messages = [
            SlackMessage(ts="1697635200.000001", text="Msg 1", user_id="U1"),
            SlackMessage(ts="1697635200.000002", text="Msg 2", user_id="U1"),
        ]
        cache.save_messages(messages, channel, "2023-10-18")

        # Empty cache run (API returned nothing)
        cache.save_messages([], channel, "2023-10-18")

        # REQUIREMENT: Existing data preserved
        table = pq.read_table(
            str(self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering" / "data.parquet")
        )

        # Should still have 2 messages (NOT 0)
        assert table.num_rows == 2, \
            f"Empty cache run should preserve data, got {table.num_rows} messages"

    def test_concurrent_cache_operations_same_partition(self):
        """Multiple concurrent cache operations should maintain data integrity

        Edge case: Two processes caching same partition simultaneously
        Expected: All unique messages preserved (no race conditions)
        """
        # This test would require threading/multiprocessing
        # Placeholder for now - demonstrates the requirement
        pytest.skip("Concurrent operations test - requires threading implementation")

    def test_large_overlap_no_memory_explosion(self):
        """Large overlapping cache runs should not explode memory

        Performance requirement: Efficient merge even with large datasets
        """
        from slack_intel.parquet_cache import ParquetCache

        cache = ParquetCache(base_path=str(self.cache_dir))
        channel = sample_channel()

        # Cache 10,000 messages
        large_batch = [
            SlackMessage(
                ts=f"1697635200.{i:06d}",
                text=f"Msg {i}",
                user_id="U1",
            )
            for i in range(10000)
        ]
        cache.save_messages(large_batch, channel, "2023-10-18")

        # Cache overlapping 9,999 messages (99% overlap)
        overlapping_batch = [
            SlackMessage(
                ts=f"1697635200.{i:06d}",
                text=f"Msg {i}",
                user_id="U1",
            )
            for i in range(1, 10000)
        ]
        cache.save_messages(overlapping_batch, channel, "2023-10-18")

        # REQUIREMENT: Should complete without OOM
        # Should have 10,000 unique messages
        import pyarrow.parquet as pq
        table = pq.read_table(
            str(self.cache_dir / "messages" / "dt=2023-10-18" / "channel=engineering" / "data.parquet")
        )
        assert table.num_rows == 10000
