"""Integration tests for Slack message sourcing"""

import pytest
import os
import shutil
import yaml
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
import duckdb

from slack_intel import (
    SlackChannelManager,
    SlackChannel,
    TimeWindow,
    ParquetCache,
    convert_slack_dicts_to_messages,
)

# Load environment variables
load_dotenv()

# Mark all tests in this module as integration tests
# and skip if credentials are not available
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.getenv("SLACK_API_TOKEN"),
        reason="SLACK_API_TOKEN not set - skipping integration tests"
    )
]


def load_test_channels() -> list[SlackChannel]:
    """Load channels from .slack-intel.yaml config file

    Returns:
        List of SlackChannel objects from config, or empty list if no config
    """
    config_paths = [
        Path(".slack-intel.yaml"),
        Path.home() / ".slack-intel.yaml",
    ]

    for config_path in config_paths:
        if config_path.exists():
            with open(config_path) as f:
                config = yaml.safe_load(f)
                if config and "channels" in config:
                    return [
                        SlackChannel(name=ch["name"], id=ch["id"])
                        for ch in config["channels"]
                    ]
    return []


@pytest.mark.asyncio
class TestSlackIntegration:
    """Integration tests that hit real Slack API"""

    async def test_manager_initialization(self):
        """Test that SlackChannelManager can be initialized with real credentials"""
        manager = SlackChannelManager()
        assert manager.client is not None
        assert manager.jira_client is not None
        assert isinstance(manager.user_cache, dict)
        assert isinstance(manager.ticket_cache, dict)

    async def test_fetch_messages_from_channel(self):
        """Test fetching real messages from a Slack channel"""
        channels = load_test_channels()
        if not channels:
            pytest.skip("No .slack-intel.yaml config found")

        manager = SlackChannelManager()
        channel = channels[0]  # Use first channel from config
        time_window = TimeWindow(days=0, hours=2)  # Just last 2 hours

        # Fetch messages
        messages = await manager.get_messages(
            channel.id,
            time_window.start_time,
            time_window.end_time
        )

        # Verify we got a response (may be empty if no messages in window)
        assert isinstance(messages, list)
        print(f"\n✓ Fetched {len(messages)} messages from {channel.name}")

    async def test_generate_llm_optimized_text(self):
        """Test generating LLM-optimized text from a real channel"""
        channels = load_test_channels()
        if not channels:
            pytest.skip("No .slack-intel.yaml config found")

        manager = SlackChannelManager()
        channel = channels[0]  # Use first channel from config
        time_window = TimeWindow(days=2, hours=0)  # Last 2 days

        # Generate LLM-optimized text
        llm_text = await manager.generate_llm_optimized_text(channel, time_window)

        # Verify output structure
        assert isinstance(llm_text, str)
        assert len(llm_text) > 0
        # Check for either format (with or without messages)
        assert ("SLACK CHANNEL:" in llm_text) or ("Channel:" in llm_text)
        assert channel.name in llm_text

        print(f"\n✓ Generated {len(llm_text)} chars of LLM-optimized text")
        print(f"Preview (first 500 chars):\n{llm_text[:500]}...")

    async def test_process_channels_structured(self):
        """Test processing multiple channels with structured output"""
        channels = load_test_channels()
        if len(channels) < 2:
            pytest.skip("Need at least 2 channels in .slack-intel.yaml config")

        manager = SlackChannelManager()
        time_window = TimeWindow(days=0, hours=2)

        # Process channels
        analytics = await manager.process_channels_structured(channels, time_window)

        # Verify structure
        assert isinstance(analytics, dict)
        assert len(analytics) <= len(channels)  # May be fewer if some channels empty

        for channel_name, channel_analytics in analytics.items():
            assert channel_analytics.channel_name == channel_name
            assert isinstance(channel_analytics.messages, list)
            assert isinstance(channel_analytics.users, list)
            assert isinstance(channel_analytics.jira_items, list)

            print(f"\n✓ Channel '{channel_name}':")
            print(f"  - Messages: {channel_analytics.messages_count}")
            print(f"  - Active users: {channel_analytics.active_users_count}")
            print(f"  - JIRA tickets: {channel_analytics.jira_tickets_count}")


@pytest.mark.asyncio
class TestJiraIntegration:
    """Integration tests for JIRA functionality"""

    @pytest.mark.skipif(
        not os.getenv("JIRA_API_TOKEN"),
        reason="JIRA_API_TOKEN not set"
    )
    async def test_jira_ticket_extraction(self):
        """Test extracting JIRA ticket IDs from text"""
        manager = SlackChannelManager()

        # Test text with JIRA tickets
        text = "Working on PROJ-123 and PROJ-456 today"
        tickets = manager.extract_jira_tickets(text)

        assert tickets is not None
        assert "PROJ-123" in tickets
        assert "PROJ-456" in tickets
        print(f"\n✓ Extracted tickets: {tickets}")


@pytest.mark.asyncio
class TestParquetCacheIntegration:
    """Integration tests for Slack → ParquetCache → DuckDB pipeline"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "integration_cache"
        self.cache = ParquetCache(base_path=str(self.cache_dir))
        yield
        # Cleanup
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    async def test_slack_to_parquet_cache(self):
        """Test fetching from Slack and saving to ParquetCache"""
        channels = load_test_channels()
        if not channels:
            pytest.skip("No .slack-intel.yaml config found")

        manager = SlackChannelManager()
        channel = channels[0]  # Use first channel from config
        time_window = TimeWindow(days=2, hours=0)  # Last 2 days

        raw_messages = await manager.get_messages(
            channel.id,
            time_window.start_time,
            time_window.end_time
        )

        # Skip if no messages (avoid empty cache test failures)
        if len(raw_messages) == 0:
            pytest.skip("No messages in time window - skipping cache test")

        # Convert to SlackMessage objects
        messages = convert_slack_dicts_to_messages(raw_messages)

        # Save to ParquetCache
        today = datetime.now().strftime("%Y-%m-%d")
        file_path = self.cache.save_messages(messages, channel, today)

        # Verify file was created
        assert Path(file_path).exists()
        assert f"dt={today}" in file_path
        assert f"channel={channel.name}" in file_path

        print(f"\n✓ Saved {len(messages)} messages to cache")
        print(f"  Cache file: {file_path}")

    async def test_slack_to_cache_to_duckdb_query(self):
        """Test full pipeline: Slack → ParquetCache → DuckDB query"""
        channels = load_test_channels()
        if not channels:
            pytest.skip("No .slack-intel.yaml config found")

        manager = SlackChannelManager()
        channel = channels[0]  # Use first channel from config
        time_window = TimeWindow(days=2, hours=0)

        raw_messages = await manager.get_messages(
            channel.id,
            time_window.start_time,
            time_window.end_time
        )

        if len(raw_messages) == 0:
            pytest.skip("No messages in time window - skipping query test")

        # Convert to SlackMessage objects
        messages = convert_slack_dicts_to_messages(raw_messages)

        # Save to cache
        today = datetime.now().strftime("%Y-%m-%d")
        self.cache.save_messages(messages, channel, today)

        # Query with DuckDB
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT
                COUNT(*) as total_messages,
                COUNT(DISTINCT user_id) as unique_users,
                COUNT(DISTINCT dt) as unique_dates
            FROM '{self.cache_dir}/messages/**/*.parquet'
        """).fetchone()

        total_messages, unique_users, unique_dates = result

        # Verify results
        assert total_messages == len(messages)
        assert unique_users >= 1
        assert unique_dates == 1  # We only saved one date

        print(f"\n✓ DuckDB query successful:")
        print(f"  Total messages: {total_messages}")
        print(f"  Unique users: {unique_users}")
        print(f"  Date partitions: {unique_dates}")

    async def test_multi_channel_cache_and_cross_channel_query(self):
        """Test caching multiple channels and cross-channel DuckDB query"""
        channels = load_test_channels()
        if len(channels) < 2:
            pytest.skip("Need at least 2 channels in .slack-intel.yaml config")

        manager = SlackChannelManager()
        time_window = TimeWindow(days=1, hours=0)
        today = datetime.now().strftime("%Y-%m-%d")

        total_cached = 0
        for channel in channels:
            raw_messages = await manager.get_messages(
                channel.id,
                time_window.start_time,
                time_window.end_time
            )

            if len(raw_messages) > 0:
                # Convert to SlackMessage objects
                messages = convert_slack_dicts_to_messages(raw_messages)
                self.cache.save_messages(messages, channel, today)
                total_cached += len(messages)
                print(f"\n✓ Cached {len(messages)} messages from {channel.name}")

        if total_cached == 0:
            pytest.skip("No messages in any channel - skipping cross-channel test")

        # Cross-channel query with DuckDB
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT
                channel,
                COUNT(*) as msg_count
            FROM read_parquet('{self.cache_dir}/messages/**/*.parquet',
                             hive_partitioning=1)
            GROUP BY channel
            ORDER BY msg_count DESC
        """).fetchall()

        # Verify we got results
        assert len(result) > 0

        print(f"\n✓ Cross-channel query results:")
        for channel_name, msg_count in result:
            print(f"  {channel_name}: {msg_count} messages")

    async def test_cache_partition_info(self):
        """Test getting cache partition statistics"""
        channels = load_test_channels()
        if not channels:
            pytest.skip("No .slack-intel.yaml config found")

        manager = SlackChannelManager()
        channel = channels[0]  # Use first channel from config
        time_window = TimeWindow(days=1, hours=0)

        raw_messages = await manager.get_messages(
            channel.id,
            time_window.start_time,
            time_window.end_time
        )

        if len(raw_messages) == 0:
            pytest.skip("No messages - skipping partition info test")

        # Convert to SlackMessage objects
        messages = convert_slack_dicts_to_messages(raw_messages)

        today = datetime.now().strftime("%Y-%m-%d")
        self.cache.save_messages(messages, channel, today)

        # Get partition info
        info = self.cache.get_partition_info()

        # Verify statistics
        assert info["total_partitions"] >= 1
        assert info["total_messages"] == len(messages)
        assert info["total_size_bytes"] > 0
        assert len(info["partitions"]) >= 1

        print(f"\n✓ Cache partition info:")
        print(f"  Total partitions: {info['total_partitions']}")
        print(f"  Total messages: {info['total_messages']}")
        print(f"  Total size: {info['total_size_bytes']:,} bytes")


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v", "-s"])
