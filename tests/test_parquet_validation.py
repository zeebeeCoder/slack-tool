"""DuckDB validation tests for Parquet cache

These tests write Parquet files using ParquetCache and validate
data integrity by querying with DuckDB.
"""

import pytest
import shutil
from pathlib import Path
import duckdb

from slack_intel import ParquetCache
from slack_intel import SlackChannel
from tests.fixtures import (
    sample_message_basic,
    sample_message_with_user_info,
    sample_message_with_reactions,
    sample_message_with_jira,
    sample_message_thread_parent,
)


class TestDuckDBValidation:
    """Test Parquet data can be queried with DuckDB"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "test_cache"
        self.cache = ParquetCache(base_path=str(self.cache_dir))
        self.channel = SlackChannel(name="test_channel", id="C123TEST")
        yield
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    def test_query_basic_message_data(self):
        """Test basic SELECT query on Parquet"""
        # Save message
        msg = sample_message_with_user_info()
        self.cache.save_messages([msg], self.channel, "2023-10-18")

        # Query with DuckDB
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT message_id, user_real_name, text
            FROM '{self.cache_dir}/messages/**/*.parquet'
        """).fetchall()

        assert len(result) == 1
        assert result[0][0] == msg.ts  # message_id
        assert result[0][1] == "John Doe"  # user_real_name
        assert "Message with user details" in result[0][2]  # text

    def test_filter_by_user(self):
        """Test filtering messages by user_name"""
        # Save multiple messages
        messages = [
            sample_message_basic(),
            sample_message_with_user_info(),
        ]
        self.cache.save_messages(messages, self.channel, "2023-10-18")

        # Query for specific user
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT user_real_name, COUNT(*) as msg_count
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE user_name = 'john.doe'
            GROUP BY user_real_name
        """).fetchall()

        # Only one message has user_info with john.doe
        assert len(result) == 1
        assert result[0][1] == 1  # msg_count

    def test_cross_channel_query(self):
        """Test querying across multiple channels"""
        channel1 = SlackChannel(name="channel_a", id="C111")
        channel2 = SlackChannel(name="channel_b", id="C222")

        # Save to different channels
        self.cache.save_messages([sample_message_basic()], channel1, "2023-10-18")
        self.cache.save_messages([sample_message_basic()], channel2, "2023-10-18")

        # Query all channels
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT COUNT(DISTINCT dt) as date_count,
                   COUNT(*) as total_messages
            FROM read_parquet('{self.cache_dir}/messages/**/*.parquet',
                             hive_partitioning=1)
        """).fetchone()

        assert result[0] == 1  # One unique date
        assert result[1] == 2  # Two messages total

    def test_jira_ticket_extraction(self):
        """Test querying JIRA tickets from array field"""
        msg = sample_message_with_jira()
        self.cache.save_messages([msg], self.channel, "2023-10-18")

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT jira_tickets
            FROM '{self.cache_dir}/messages/**/*.parquet'
        """).fetchone()

        # Should have extracted JIRA tickets
        jira_tickets = result[0]
        assert isinstance(jira_tickets, list)
        assert "PROJ-123" in jira_tickets
        assert "PROJ-456" in jira_tickets

    def test_nested_reactions_structure(self):
        """Test querying nested reactions structure"""
        msg = sample_message_with_reactions()
        self.cache.save_messages([msg], self.channel, "2023-10-18")

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT reactions
            FROM '{self.cache_dir}/messages/**/*.parquet'
        """).fetchone()

        reactions = result[0]
        assert len(reactions) == 2
        assert reactions[0]['emoji'] == '100'
        assert reactions[0]['count'] == 2

    def test_boolean_flags_filtering(self):
        """Test filtering by boolean flags"""
        messages = [
            sample_message_basic(),  # No reactions
            sample_message_with_reactions(),  # Has reactions
        ]
        self.cache.save_messages(messages, self.channel, "2023-10-18")

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT COUNT(*) as count
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE has_reactions = true
        """).fetchone()

        assert result[0] == 1  # Only one message has reactions

    def test_timestamp_range_query(self):
        """Test querying by timestamp range"""
        msg = sample_message_basic()
        self.cache.save_messages([msg], self.channel, "2023-10-18")

        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT timestamp
            FROM '{self.cache_dir}/messages/**/*.parquet'
            WHERE timestamp >= '2023-10-18T00:00:00Z'
              AND timestamp <= '2023-10-19T00:00:00Z'
        """).fetchall()

        assert len(result) == 1
