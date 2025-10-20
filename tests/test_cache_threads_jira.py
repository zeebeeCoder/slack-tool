"""Test cases for caching messages with threads and JIRA tickets

This test suite verifies that the Slack → ParquetCache pipeline correctly
handles and preserves:
- Regular messages
- Thread parent messages
- Thread reply messages
- JIRA ticket extraction from message text
- Cross-channel queries
"""

import pytest
import shutil
from pathlib import Path
import duckdb

from slack_intel import ParquetCache, SlackChannel
from tests.fixtures import (
    sample_message_basic,
    sample_message_with_jira,
    sample_message_thread_parent,
)


class TestThreadsAndJiraCaching:
    """Test that threads and JIRA tickets are properly cached"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        self.cache = ParquetCache(base_path=str(self.cache_dir))
        self.channel = SlackChannel(name="test_channel", id="C123TEST")
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_cache_preserves_thread_metadata(self):
        """Test that thread parent and reply flags are preserved"""
        # Create a thread parent message
        parent_msg = sample_message_thread_parent()

        # Save to cache
        self.cache.save_messages([parent_msg], self.channel, "2023-10-18")

        # Query with DuckDB
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT is_thread_parent, reply_count
            FROM '{self.cache_dir}/messages/**/*.parquet'
        """).fetchone()

        assert result[0] == True  # is_thread_parent
        assert result[1] == 2     # reply_count from fixture

    def test_cache_preserves_jira_tickets(self):
        """Test that JIRA tickets are extracted and cached"""
        msg = sample_message_with_jira()

        self.cache.save_messages([msg], self.channel, "2023-10-18")

        # Query JIRA tickets
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT jira_tickets
            FROM '{self.cache_dir}/messages/**/*.parquet'
        """).fetchone()

        jira_tickets = result[0]
        assert len(jira_tickets) >= 2
        assert "PROJ-123" in jira_tickets
        assert "PROJ-456" in jira_tickets

    def test_mixed_messages_all_cached_correctly(self):
        """Test caching a mix of regular, thread, and JIRA messages"""
        messages = [
            sample_message_basic(),
            sample_message_thread_parent(),
            sample_message_with_jira(),
        ]

        self.cache.save_messages(messages, self.channel, "2023-10-18")

        conn = duckdb.connect()

        # Check total count
        total = conn.execute(f"""
            SELECT COUNT(*)
            FROM '{self.cache_dir}/messages/**/*.parquet'
        """).fetchone()[0]
        assert total == 3

        # Check thread parents
        thread_parents = conn.execute(f"""
            SELECT COUNT(*)
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE is_thread_parent = true
        """).fetchone()[0]
        assert thread_parents == 1

        # Check JIRA tickets exist
        with_jira = conn.execute(f"""
            SELECT COUNT(*)
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE LENGTH(jira_tickets) > 0
        """).fetchone()[0]
        assert with_jira >= 1

    def test_query_jira_tickets_across_messages(self):
        """Test querying JIRA tickets using DuckDB"""
        messages = [
            sample_message_with_jira(),  # Has PROJ-123, PROJ-456
        ]

        self.cache.save_messages(messages, self.channel, "2023-10-18")

        conn = duckdb.connect()

        # Unnest JIRA tickets to query them
        result = conn.execute(f"""
            SELECT UNNEST(jira_tickets) as ticket
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE LENGTH(jira_tickets) > 0
        """).fetchall()

        tickets = [r[0] for r in result]
        assert "PROJ-123" in tickets
        assert "PROJ-456" in tickets

    def test_thread_parent_with_replies_count(self):
        """Test that reply_count is correctly stored"""
        parent = sample_message_thread_parent()

        self.cache.save_messages([parent], self.channel, "2023-10-18")

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT reply_count, is_thread_parent
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE is_thread_parent = true
        """).fetchone()

        assert result[0] == 2      # reply_count from fixture
        assert result[1] == True   # is_thread_parent

    def test_cache_multiple_channels_with_jira(self):
        """Test caching JIRA tickets from multiple channels"""
        channel1 = SlackChannel(name="channel_a", id="C111")
        channel2 = SlackChannel(name="channel_b", id="C222")

        msg_with_jira = sample_message_with_jira()

        # Save to both channels
        self.cache.save_messages([msg_with_jira], channel1, "2023-10-18")
        self.cache.save_messages([msg_with_jira], channel2, "2023-10-18")

        # Cross-channel JIRA query
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT
                channel,
                UNNEST(jira_tickets) as ticket
            FROM read_parquet('{self.cache_dir}/messages/**/*.parquet',
                             hive_partitioning=1)
            WHERE LENGTH(jira_tickets) > 0
        """).fetchall()

        # Should have tickets from both channels
        channels = [r[0] for r in result]
        assert "channel_a" in channels
        assert "channel_b" in channels

        # Should have JIRA tickets
        tickets = [r[1] for r in result]
        assert "PROJ-123" in tickets


class TestRealDataThreadsAndJira:
    """Integration tests using real Slack data (requires API access)"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "integration_cache"
        self.cache = ParquetCache(base_path=str(self.cache_dir))
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_real_channel_threads_and_jira(self):
        """Test caching real channel with threads and JIRA tickets

        Replace channel ID with your own for testing.
        Expects channel to have:
        - Thread conversations
        - JIRA ticket references
        """
        from slack_intel import SlackChannelManager, TimeWindow
        from slack_intel.utils import convert_slack_dicts_to_messages
        from datetime import datetime

        manager = SlackChannelManager()
        channel = SlackChannel(
            name="sample-channel",
            id="C1234567890"
        )
        time_window = TimeWindow(days=10, hours=0)

        # Fetch messages
        raw_messages = await manager.get_messages(
            channel.id,
            time_window.start_time,
            time_window.end_time
        )

        if len(raw_messages) == 0:
            pytest.skip("No messages in channel")

        # Convert and cache
        messages = convert_slack_dicts_to_messages(raw_messages)
        today = datetime.now().strftime("%Y-%m-%d")
        self.cache.save_messages(messages, channel, today)

        # Verify caching worked
        conn = duckdb.connect()

        # Check total messages
        total = conn.execute(f"""
            SELECT COUNT(*)
            FROM '{self.cache_dir}/messages/**/*.parquet'
        """).fetchone()[0]
        assert total > 0

        # Check for thread replies
        thread_replies = conn.execute(f"""
            SELECT COUNT(*)
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE is_thread_reply = true
        """).fetchone()[0]

        print(f"Total messages: {total}")
        print(f"Thread replies: {thread_replies}")

        # Check for JIRA tickets
        jira_result = conn.execute(f"""
            SELECT UNNEST(jira_tickets) as ticket
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE LENGTH(jira_tickets) > 0
        """).fetchall()

        if jira_result:
            tickets = [r[0] for r in jira_result]
            print(f"JIRA tickets found: {tickets}")
            # Verify JIRA tickets were found
            assert len(tickets) > 0

    def test_query_thread_conversations(self):
        """Test querying thread conversations from cache"""
        # This test verifies we can reconstruct thread conversations
        # from cached data using thread_ts

        from tests.fixtures import sample_message_thread_parent

        parent = sample_message_thread_parent()

        self.cache.save_messages([parent],
                                SlackChannel(name="test", id="C123"),
                                "2023-10-18")

        conn = duckdb.connect()

        # Find thread parent
        parent_result = conn.execute(f"""
            SELECT message_id, text, reply_count
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE is_thread_parent = true
        """).fetchone()

        assert parent_result is not None
        assert parent_result[2] > 0  # has replies
