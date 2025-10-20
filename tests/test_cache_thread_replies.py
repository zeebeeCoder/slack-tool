"""
Test that cache pipeline fetches thread replies from Slack API.

When caching a channel, if a message is a thread parent, the cache pipeline
calls conversations_replies to fetch ALL thread replies and cache them.

THREAD PARENT DETECTION LOGIC (from slack_channels.py:559-562):
    A message is a thread parent when:
        thread_ts == ts AND reply_count > 0

    Examples:
        ✓ Thread parent:     ts=1.0, thread_ts=1.0, reply_count=2  → FETCH REPLIES
        ✗ Regular message:   ts=1.0, thread_ts=None, reply_count=0 → SKIP
        ✗ Thread reply:      ts=2.0, thread_ts=1.0, reply_count=0  → SKIP (points to parent)
        ✗ Empty parent:      ts=1.0, thread_ts=1.0, reply_count=0  → SKIP (no replies yet)

Implementation: Fetches timeline messages via conversations_history, then automatically
fetches thread replies via conversations_replies for each thread parent found.
"""

import pytest
import tempfile
import shutil
from datetime import datetime
from unittest.mock import AsyncMock, patch, MagicMock
from slack_intel.slack_channels import SlackChannelManager, SlackChannel
from slack_intel.parquet_cache import ParquetCache
from slack_intel.parquet_message_reader import ParquetMessageReader


class TestCacheThreadRepliesFetching:
    """Test that cache pipeline fetches thread replies from Slack API"""

    @pytest.fixture
    def temp_cache_dir(self):
        """Create a temporary cache directory"""
        temp_dir = tempfile.mkdtemp()
        yield temp_dir
        shutil.rmtree(temp_dir)

    @pytest.fixture
    def cache(self, temp_cache_dir):
        """Create a ParquetCache instance"""
        from pathlib import Path
        raw_path = Path(temp_cache_dir) / "raw"
        return ParquetCache(base_path=str(raw_path))

    @pytest.fixture
    def channel(self):
        """Create a test channel"""
        return SlackChannel(name="test_channel", id="C12345")

    @pytest.mark.asyncio
    async def test_cache_fetches_thread_replies_for_thread_parents(
        self, cache, channel, temp_cache_dir
    ):
        """
        CRITICAL TEST: Cache should fetch thread replies when:
          thread_ts == ts AND reply_count > 0

        This matches the thread parent detection logic from slack_channels.py:559-562

        Scenario:
          Given a channel has a parent message where thread_ts == ts AND reply_count=2
          When caching the channel
          Then conversations_replies should be called with (channel_id, thread_ts)
          And all thread replies should be saved to cache
          And replies should have proper thread_ts linking to parent

        Verifies: Both conversations_history and conversations_replies are called correctly
        """
        # Mock Slack API responses
        with patch.object(SlackChannelManager, '_validate_env', return_value=None), \
             patch.object(SlackChannelManager, '_init_jira', return_value=None):

            manager = SlackChannelManager()

            # Mock conversations_history response - returns parent message with reply_count
            history_response = MagicMock()
            history_response.data = {
                "messages": [
                    {
                        "ts": "1697654321.123456",
                        "user": "U001",
                        "text": "Can someone review this PR?",
                        "thread_ts": "1697654321.123456",  # Parent: thread_ts == ts
                        "reply_count": 2,  # HAS REPLIES
                        "reply_users_count": 2,
                        "latest_reply": "1697654400.789012",
                        "user_info": {
                            "id": "U001",
                            "name": "alice",
                            "real_name": "Alice Chen",
                            "is_bot": False
                        }
                    }
                ]
            }

            # Mock conversations_replies response - returns parent + 2 replies
            replies_response = MagicMock()
            replies_response.data = {
                "messages": [
                    # First message is the parent (repeated)
                    {
                        "ts": "1697654321.123456",
                        "user": "U001",
                        "text": "Can someone review this PR?",
                        "thread_ts": "1697654321.123456",
                        "user_info": {
                            "id": "U001",
                            "name": "alice",
                            "real_name": "Alice Chen",
                            "is_bot": False
                        }
                    },
                    # Reply 1
                    {
                        "ts": "1697654350.456789",
                        "user": "U002",
                        "text": "Looking at it now",
                        "thread_ts": "1697654321.123456",  # Points to parent
                        "user_info": {
                            "id": "U002",
                            "name": "bob",
                            "real_name": "Bob Martinez",
                            "is_bot": False
                        }
                    },
                    # Reply 2
                    {
                        "ts": "1697654400.789012",
                        "user": "U003",
                        "text": "LGTM! Approved.",
                        "thread_ts": "1697654321.123456",  # Points to parent
                        "user_info": {
                            "id": "U003",
                            "name": "charlie",
                            "real_name": "Charlie Davis",
                            "is_bot": False
                        }
                    }
                ]
            }

            # Setup mocks
            manager.client = AsyncMock()
            manager.client.conversations_history = AsyncMock(return_value=history_response)
            manager.client.conversations_replies = AsyncMock(return_value=replies_response)

            # Fetch messages (this is what the cache pipeline does)
            from datetime import timedelta
            current_time = datetime.now()
            start_time = (current_time - timedelta(days=1)).timestamp()
            end_time = current_time.timestamp()

            raw_messages = await manager.get_messages(
                channel.id,
                start_time,
                end_time
            )

            # ASSERTION 1: conversations_history was called
            manager.client.conversations_history.assert_called_once()

            # ASSERTION 2: conversations_replies SHOULD be called for thread parent
            # This is the MISSING functionality that causes test to FAIL
            manager.client.conversations_replies.assert_called_once_with(
                channel=channel.id,
                ts="1697654321.123456"  # Thread parent timestamp
            )

            # ASSERTION 3: All messages (parent + replies) should be returned
            assert len(raw_messages) == 3, \
                f"Expected 3 messages (1 parent + 2 replies), got {len(raw_messages)}"

            # ASSERTION 4: Verify message structure
            parent = next(m for m in raw_messages if m["ts"] == "1697654321.123456")
            reply1 = next(m for m in raw_messages if m["ts"] == "1697654350.456789")
            reply2 = next(m for m in raw_messages if m["ts"] == "1697654400.789012")

            # Parent should have reply_count
            assert parent.get("reply_count") == 2, "Parent should have reply_count=2"
            assert parent.get("thread_ts") == parent.get("ts"), "Parent: thread_ts == ts"

            # Replies should point to parent
            assert reply1.get("thread_ts") == "1697654321.123456", "Reply 1 should link to parent"
            assert reply2.get("thread_ts") == "1697654321.123456", "Reply 2 should link to parent"

            # ASSERTION 5: When cached and read back, all 3 messages should be present
            from slack_intel.slack_channels import SlackMessage, SlackUser

            messages = [
                SlackMessage(
                    ts=msg["ts"],
                    user=msg["user"],
                    text=msg["text"],
                    thread_ts=msg.get("thread_ts"),
                    replies_count=msg.get("reply_count", 0),
                    user_info=SlackUser(
                        id=msg["user_info"]["id"],
                        name=msg["user_info"]["name"],
                        real_name=msg["user_info"]["real_name"],
                        is_bot=msg["user_info"]["is_bot"]
                    ) if msg.get("user_info") else None
                )
                for msg in raw_messages
            ]

            cache.save_messages(messages, channel, "2025-10-20")

            # Read back from cache
            reader = ParquetMessageReader(base_path=temp_cache_dir)
            cached_messages = reader.read_channel("test_channel", "2025-10-20")

            assert len(cached_messages) == 3, \
                f"Expected 3 cached messages, got {len(cached_messages)}"

            # Verify parent is marked correctly
            cached_parent = next(m for m in cached_messages if m["message_id"] == "1697654321.123456")
            assert cached_parent["reply_count"] == 2, "Cached parent should have reply_count=2"
            assert cached_parent["is_thread_parent"] is True, "Should be marked as thread parent"

            # Verify replies are marked correctly
            cached_reply1 = next(m for m in cached_messages if m["message_id"] == "1697654350.456789")
            assert cached_reply1["is_thread_reply"] is True, "Reply 1 should be marked as reply"
            assert cached_reply1["thread_ts"] == "1697654321.123456", "Reply 1 should link to parent"

    @pytest.mark.asyncio
    async def test_cache_handles_multiple_threads(
        self, cache, channel, temp_cache_dir
    ):
        """
        Test that cache fetches replies for MULTIPLE thread parents in same channel

        Scenario:
          Given a channel has 2 parent messages, each with replies
          When caching the channel
          Then conversations_replies should be called TWICE (once per parent)
          And all thread replies from both threads should be cached
        """
        with patch.object(SlackChannelManager, '_validate_env', return_value=None), \
             patch.object(SlackChannelManager, '_init_jira', return_value=None):

            manager = SlackChannelManager()

            # Mock conversations_history - returns 2 thread parents
            history_response = MagicMock()
            history_response.data = {
                "messages": [
                    # Thread 1 parent
                    {
                        "ts": "1697654321.111111",
                        "user": "U001",
                        "text": "Thread 1 parent",
                        "thread_ts": "1697654321.111111",
                        "reply_count": 1,
                        "user_info": {"id": "U001", "name": "alice", "real_name": "Alice", "is_bot": False}
                    },
                    # Thread 2 parent
                    {
                        "ts": "1697654321.222222",
                        "user": "U002",
                        "text": "Thread 2 parent",
                        "thread_ts": "1697654321.222222",
                        "reply_count": 2,
                        "user_info": {"id": "U002", "name": "bob", "real_name": "Bob", "is_bot": False}
                    }
                ]
            }

            # Mock conversations_replies responses
            def mock_replies(channel, ts):
                if ts == "1697654321.111111":
                    # Thread 1 replies
                    response = MagicMock()
                    response.data = {
                        "messages": [
                            {"ts": "1697654321.111111", "user": "U001", "text": "Thread 1 parent",
                             "thread_ts": "1697654321.111111", "user_info": {"id": "U001", "name": "alice", "real_name": "Alice", "is_bot": False}},
                            {"ts": "1697654321.111112", "user": "U002", "text": "Thread 1 reply 1",
                             "thread_ts": "1697654321.111111", "user_info": {"id": "U002", "name": "bob", "real_name": "Bob", "is_bot": False}}
                        ]
                    }
                    return response
                elif ts == "1697654321.222222":
                    # Thread 2 replies
                    response = MagicMock()
                    response.data = {
                        "messages": [
                            {"ts": "1697654321.222222", "user": "U002", "text": "Thread 2 parent",
                             "thread_ts": "1697654321.222222", "user_info": {"id": "U002", "name": "bob", "real_name": "Bob", "is_bot": False}},
                            {"ts": "1697654321.222223", "user": "U003", "text": "Thread 2 reply 1",
                             "thread_ts": "1697654321.222222", "user_info": {"id": "U003", "name": "charlie", "real_name": "Charlie", "is_bot": False}},
                            {"ts": "1697654321.222224", "user": "U001", "text": "Thread 2 reply 2",
                             "thread_ts": "1697654321.222222", "user_info": {"id": "U001", "name": "alice", "real_name": "Alice", "is_bot": False}}
                        ]
                    }
                    return response

            manager.client = AsyncMock()
            manager.client.conversations_history = AsyncMock(return_value=history_response)
            manager.client.conversations_replies = AsyncMock(side_effect=mock_replies)

            # Fetch messages
            from datetime import timedelta
            current_time = datetime.now()
            start_time = (current_time - timedelta(days=1)).timestamp()
            end_time = current_time.timestamp()

            raw_messages = await manager.get_messages(channel.id, start_time, end_time)

            # ASSERTION: conversations_replies called TWICE (once per thread)
            assert manager.client.conversations_replies.call_count == 2, \
                f"Expected 2 calls to conversations_replies, got {manager.client.conversations_replies.call_count}"

            # ASSERTION: Total messages = 2 parents + 1 reply + 2 replies = 5
            assert len(raw_messages) == 5, \
                f"Expected 5 total messages (2 parents + 3 replies), got {len(raw_messages)}"

    @pytest.mark.asyncio
    async def test_cache_skips_conversations_replies_for_non_parents(
        self, cache, channel, temp_cache_dir
    ):
        """
        Test that cache does NOT call conversations_replies for messages that are NOT parents

        Scenario:
          Given a channel has messages where thread_ts != ts OR reply_count == 0
          When caching the channel
          Then conversations_replies should NOT be called

        Examples of non-parents:
          - Regular messages (no thread_ts, no reply_count)
          - Thread replies (thread_ts != ts)
          - Empty thread parents (thread_ts == ts but reply_count == 0)
        """
        with patch.object(SlackChannelManager, '_validate_env', return_value=None), \
             patch.object(SlackChannelManager, '_init_jira', return_value=None):

            manager = SlackChannelManager()

            # Mock conversations_history - returns non-parent messages
            history_response = MagicMock()
            history_response.data = {
                "messages": [
                    # Case 1: Regular message (no thread_ts, no reply_count)
                    {
                        "ts": "1697654321.111111",
                        "user": "U001",
                        "text": "Regular message",
                        "user_info": {"id": "U001", "name": "alice", "real_name": "Alice", "is_bot": False}
                    },
                    # Case 2: Thread reply (thread_ts != ts)
                    {
                        "ts": "1697654321.222222",
                        "user": "U002",
                        "text": "This is a reply to another thread",
                        "thread_ts": "1697654320.000000",  # Points to different parent
                        "user_info": {"id": "U002", "name": "bob", "real_name": "Bob", "is_bot": False}
                    },
                    # Case 3: Empty thread parent (thread_ts == ts but reply_count == 0)
                    {
                        "ts": "1697654321.333333",
                        "user": "U003",
                        "text": "Thread parent with no replies yet",
                        "thread_ts": "1697654321.333333",  # thread_ts == ts
                        "reply_count": 0,  # But no replies
                        "user_info": {"id": "U003", "name": "charlie", "real_name": "Charlie", "is_bot": False}
                    }
                ]
            }

            manager.client = AsyncMock()
            manager.client.conversations_history = AsyncMock(return_value=history_response)
            manager.client.conversations_replies = AsyncMock()

            # Fetch messages
            from datetime import timedelta
            current_time = datetime.now()
            start_time = (current_time - timedelta(days=1)).timestamp()
            end_time = current_time.timestamp()

            raw_messages = await manager.get_messages(channel.id, start_time, end_time)

            # ASSERTION: conversations_replies should NOT be called for any of these
            manager.client.conversations_replies.assert_not_called()

            # ASSERTION: Should return 3 messages (all non-parents)
            assert len(raw_messages) == 3, \
                f"Expected 3 messages (all non-parents), got {len(raw_messages)}"
