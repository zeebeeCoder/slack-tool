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

    @pytest.mark.skipif(
        not os.getenv("JIRA_API_TOKEN"),
        reason="JIRA_API_TOKEN not set"
    )
    async def test_fetch_jira_tickets_batch(self):
        """Test batch fetching JIRA tickets"""
        manager = SlackChannelManager()

        # Get some real ticket IDs from Slack messages first
        channels = load_test_channels()
        if not channels:
            pytest.skip("No .slack-intel.yaml config found")

        channel = channels[0]
        time_window = TimeWindow(days=7, hours=0)  # Look back 7 days

        # Fetch messages
        raw_messages = await manager.get_messages(
            channel.id,
            time_window.start_time,
            time_window.end_time
        )

        if not raw_messages:
            pytest.skip("No messages to extract JIRA tickets from")

        # Extract JIRA ticket IDs
        all_tickets = set()
        for msg in raw_messages:
            text = msg.get("text", "")
            tickets = manager.extract_jira_tickets(text)
            if tickets:
                all_tickets.update(tickets)

        if not all_tickets:
            pytest.skip("No JIRA tickets found in messages")

        # Fetch tickets in batch
        ticket_list = list(all_tickets)[:10]  # Limit to 10 for test
        jira_tickets = await manager.fetch_jira_tickets_batch(ticket_list)

        # Verify results (some may fail due to permissions, that's ok)
        assert isinstance(jira_tickets, list)
        print(f"\n✓ Requested {len(ticket_list)} tickets")
        print(f"✓ Successfully fetched {len(jira_tickets)} tickets")

        # If we got any tickets, verify structure
        if jira_tickets:
            ticket = jira_tickets[0]
            assert hasattr(ticket, "ticket")
            assert hasattr(ticket, "summary")
            assert hasattr(ticket, "status")
            print(f"\n✓ Sample ticket: {ticket.ticket} - {ticket.summary[:50]}...")


@pytest.mark.asyncio
class TestJiraEnrichmentIntegration:
    """Integration tests for end-to-end JIRA enrichment pipeline"""

    @pytest.fixture(autouse=True)
    def setup_teardown(self, tmp_path):
        """Setup test cache directory"""
        self.cache_dir = tmp_path / "jira_integration_cache"
        self.cache = ParquetCache(base_path=str(self.cache_dir))
        yield
        # Cleanup
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)

    @pytest.mark.skipif(
        not os.getenv("JIRA_API_TOKEN"),
        reason="JIRA_API_TOKEN not set"
    )
    async def test_slack_jira_enrichment_pipeline(self):
        """Test full pipeline: Slack messages → Extract tickets → Enrich JIRA → Cache"""
        channels = load_test_channels()
        if not channels:
            pytest.skip("No .slack-intel.yaml config found")

        manager = SlackChannelManager()
        channel = channels[0]
        time_window = TimeWindow(days=7, hours=0)  # Look back 7 days
        today = datetime.now().strftime("%Y-%m-%d")

        # Step 1: Fetch Slack messages
        raw_messages = await manager.get_messages(
            channel.id,
            time_window.start_time,
            time_window.end_time
        )

        if not raw_messages:
            pytest.skip("No messages found")

        messages = convert_slack_dicts_to_messages(raw_messages)

        # Step 2: Save messages to cache
        msg_path = self.cache.save_messages(messages, channel, today)
        assert Path(msg_path).exists()
        print(f"\n✓ Cached {len(messages)} messages")

        # Step 3: Extract JIRA ticket IDs
        all_ticket_ids = set()
        for msg in messages:
            parquet_dict = msg.to_parquet_dict()
            if parquet_dict.get("jira_tickets"):
                all_ticket_ids.update(parquet_dict["jira_tickets"])

        if not all_ticket_ids:
            pytest.skip("No JIRA tickets found in messages")

        print(f"✓ Found {len(all_ticket_ids)} unique JIRA tickets")

        # Step 4: Fetch JIRA tickets
        jira_tickets = await manager.fetch_jira_tickets_batch(list(all_ticket_ids))

        if not jira_tickets:
            print("⚠ No JIRA tickets were successfully fetched (may be permissions issue)")
            pytest.skip("No JIRA tickets fetched")

        print(f"✓ Enriched {len(jira_tickets)} JIRA tickets")

        # Step 5: Save JIRA tickets to cache
        jira_path = self.cache.save_jira_tickets(jira_tickets, today)
        assert Path(jira_path).exists()
        print(f"✓ Saved JIRA tickets to {jira_path}")

        # Step 6: Verify JIRA cache with DuckDB
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT
                COUNT(*) as total_tickets,
                COUNT(DISTINCT ticket_id) as unique_tickets,
                COUNT(DISTINCT status) as unique_statuses
            FROM '{self.cache_dir}/jira/**/*.parquet'
        """).fetchone()

        total, unique, statuses = result
        assert total == len(jira_tickets)
        assert unique == len(jira_tickets)
        assert statuses >= 1

        print(f"\n✓ JIRA cache validation:")
        print(f"  Total tickets: {total}")
        print(f"  Unique tickets: {unique}")
        print(f"  Unique statuses: {statuses}")

    @pytest.mark.skipif(
        not os.getenv("JIRA_API_TOKEN"),
        reason="JIRA_API_TOKEN not set"
    )
    async def test_message_jira_join_query(self):
        """Test JOIN query between messages and JIRA tickets"""
        channels = load_test_channels()
        if not channels:
            pytest.skip("No .slack-intel.yaml config found")

        manager = SlackChannelManager()
        channel = channels[0]
        time_window = TimeWindow(days=7, hours=0)
        today = datetime.now().strftime("%Y-%m-%d")

        # Fetch and cache messages
        raw_messages = await manager.get_messages(
            channel.id,
            time_window.start_time,
            time_window.end_time
        )

        if not raw_messages:
            pytest.skip("No messages found")

        messages = convert_slack_dicts_to_messages(raw_messages)
        self.cache.save_messages(messages, channel, today)

        # Extract and enrich JIRA tickets
        all_ticket_ids = set()
        for msg in messages:
            parquet_dict = msg.to_parquet_dict()
            if parquet_dict.get("jira_tickets"):
                all_ticket_ids.update(parquet_dict["jira_tickets"])

        if not all_ticket_ids:
            pytest.skip("No JIRA tickets found")

        jira_tickets = await manager.fetch_jira_tickets_batch(list(all_ticket_ids))

        if not jira_tickets:
            pytest.skip("No JIRA tickets fetched")

        self.cache.save_jira_tickets(jira_tickets, today)

        # Execute JOIN query
        conn = duckdb.connect()
        result = conn.execute(f"""
            SELECT
                m.text,
                m.user_real_name,
                j.ticket_id,
                j.summary,
                j.status,
                j.assignee
            FROM '{self.cache_dir}/messages/**/*.parquet' m,
                 UNNEST(m.jira_tickets) AS t(ticket)
            JOIN '{self.cache_dir}/jira/**/*.parquet' j
                ON j.ticket_id = ticket
            LIMIT 10
        """).fetchall()

        # Verify JOIN worked
        assert len(result) > 0, "JOIN query should return results"

        print(f"\n✓ JOIN query returned {len(result)} rows")
        print("\n✓ Sample results:")
        for row in result[:3]:
            text, user, ticket, summary, status, assignee = row
            print(f"  User: {user}")
            print(f"  Ticket: {ticket} - {summary[:50]}...")
            print(f"  Status: {status} | Assignee: {assignee}")
            print(f"  Message: {text[:100]}...")
            print()

    async def test_jira_schema_validation(self):
        """Test that JIRA Parquet schema matches expected structure"""
        from slack_intel.parquet_cache import _create_jira_schema

        schema = _create_jira_schema()

        # Verify all required fields exist
        required_fields = [
            "ticket_id", "summary", "priority", "issue_type", "status",
            "assignee", "due_date", "story_points", "blocks", "blocked_by",
            "components", "labels", "progress_total", "progress_percentage",
            "project", "sprints", "cached_at"
        ]

        schema_names = [field.name for field in schema]
        for field_name in required_fields:
            assert field_name in schema_names, f"Missing field: {field_name}"

        print(f"\n✓ JIRA schema has {len(schema_names)} fields")
        print(f"✓ All {len(required_fields)} required fields present")


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

    async def test_user_cache_created_with_mentions(self):
        """Test that user cache (users.parquet) is created with mentioned users"""
        import re
        import pyarrow as pa
        import pyarrow.parquet as pq
        from datetime import datetime as dt

        channels = load_test_channels()
        if not channels:
            pytest.skip("No .slack-intel.yaml config found")

        manager = SlackChannelManager()
        channel = channels[0]
        time_window = TimeWindow(days=2, hours=0)  # Last 2 days

        # Fetch messages
        raw_messages = await manager.get_messages(
            channel.id,
            time_window.start_time,
            time_window.end_time
        )

        if len(raw_messages) == 0:
            pytest.skip("No messages in time window - skipping user cache test")

        # Convert to SlackMessage objects
        messages = convert_slack_dicts_to_messages(raw_messages)

        # Extract user mentions (same logic as cache command)
        all_mentioned_user_ids = set()
        mention_pattern = r'<@(U[A-Z0-9]+)>'
        for message in messages:
            message_text = message.text if hasattr(message, 'text') else ""
            if message_text:
                mentions = re.findall(mention_pattern, message_text)
                all_mentioned_user_ids.update(mentions)

        # If no mentions found, skip
        if not all_mentioned_user_ids:
            pytest.skip("No user mentions found in messages - skipping user cache test")

        print(f"\n✓ Found {len(all_mentioned_user_ids)} unique user mentions")

        # Fetch user profiles (simulate cache command behavior)
        import asyncio
        semaphore = asyncio.Semaphore(10)

        async def fetch_user_safe(user_id: str):
            """Fetch user info with rate limiting"""
            async with semaphore:
                if user_id not in manager.user_cache:
                    try:
                        await manager.get_user_info(user_id)
                    except Exception:
                        pass  # Silently skip failures

        await asyncio.gather(*[fetch_user_safe(uid) for uid in all_mentioned_user_ids])

        # Save to users.parquet (simulate cache command)
        # Note: cache command saves to parent of cache_dir (e.g., cache/users.parquet when cache_dir=cache/raw)
        # For this test, cache_dir is just the temp dir, so we save directly to it
        users_cache_path = Path(self.cache_dir) / "users.parquet"

        if manager.user_cache:
            cached_at = dt.now().isoformat()
            users_list = []
            for user_id, user_data in manager.user_cache.items():
                users_list.append({
                    'user_id': user_id,
                    'user_name': user_data.get('name'),
                    'user_real_name': user_data.get('real_name'),
                    'user_email': user_data.get('profile', {}).get('email') if isinstance(user_data, dict) else None,
                    'is_bot': user_data.get('is_bot', False) if isinstance(user_data, dict) else False,
                    'cached_at': cached_at
                })

            # Save to Parquet
            table = pa.Table.from_pylist(users_list)
            pq.write_table(table, str(users_cache_path))

            print(f"✓ Cached {len(users_list)} users to {users_cache_path}")

            # Verify file exists
            assert users_cache_path.exists(), "users.parquet file was not created"
            assert users_cache_path.stat().st_size > 0, "users.parquet file is empty"

            # Verify with DuckDB
            conn = duckdb.connect()
            result = conn.execute(f"""
                SELECT
                    COUNT(*) as total_users,
                    COUNT(DISTINCT user_id) as unique_users,
                    COUNT(DISTINCT user_real_name) as unique_names
                FROM '{users_cache_path}'
            """).fetchone()

            total_users, unique_users, unique_names = result

            assert total_users > 0, "No users in cache"
            assert unique_users == total_users, "Duplicate user_ids found"

            print(f"\n✓ User cache validation:")
            print(f"  Total users: {total_users}")
            print(f"  Unique IDs: {unique_users}")
            print(f"  Unique names: {unique_names}")

            # Verify schema
            schema_result = conn.execute(f"""
                DESCRIBE SELECT * FROM '{users_cache_path}'
            """).fetchall()

            schema_fields = [row[0] for row in schema_result]
            required_fields = ['user_id', 'user_name', 'user_real_name', 'user_email', 'is_bot', 'cached_at']

            for field in required_fields:
                assert field in schema_fields, f"Missing required field: {field}"

            print(f"✓ Schema has all {len(required_fields)} required fields")
        else:
            pytest.skip("No users were cached (may be API errors)")


if __name__ == "__main__":
    # Allow running this file directly for quick testing
    pytest.main([__file__, "-v", "-s"])
