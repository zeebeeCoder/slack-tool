"""Unit tests for ThreadReconstructor - TDD approach

Tests rebuilding thread structure from flat Parquet message data.
These tests will FAIL until ThreadReconstructor is implemented.
"""

import pytest
from typing import List, Dict, Any


# This import will fail until we create the module
try:
    from slack_intel.thread_reconstructor import ThreadReconstructor
except ImportError:
    ThreadReconstructor = None


class TestBasicThreadReconstruction:
    """Test basic thread reconstruction logic"""

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_single_standalone_message(self):
        """Test single standalone message passes through unchanged"""
        flat_messages = [
            {
                "message_id": "111",
                "text": "Standalone message",
                "thread_ts": None,
                "is_thread_parent": False,
                "is_thread_reply": False,
                "timestamp": "2023-10-20T10:00:00Z"
            }
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        assert len(result) == 1
        assert result[0]["message_id"] == "111"
        assert "replies" not in result[0] or result[0]["replies"] == []

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_multiple_standalone_messages(self):
        """Test multiple standalone messages remain separate"""
        flat_messages = [
            {"message_id": "111", "text": "Message 1", "thread_ts": None, "is_thread_parent": False, "is_thread_reply": False, "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "222", "text": "Message 2", "thread_ts": None, "is_thread_parent": False, "is_thread_reply": False, "timestamp": "2023-10-20T11:00:00Z"},
            {"message_id": "333", "text": "Message 3", "thread_ts": None, "is_thread_parent": False, "is_thread_reply": False, "timestamp": "2023-10-20T12:00:00Z"},
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        assert len(result) == 3
        assert all("replies" not in msg or msg["replies"] == [] for msg in result)

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_simple_thread_with_one_reply(self):
        """Test thread parent with single reply gets nested correctly"""
        flat_messages = [
            {
                "message_id": "1697654321.123456",
                "text": "Parent message",
                "thread_ts": "1697654321.123456",
                "is_thread_parent": True,
                "is_thread_reply": False,
                "timestamp": "2023-10-18T17:38:41Z"
            },
            {
                "message_id": "1697654400.123457",
                "text": "Reply 1",
                "thread_ts": "1697654321.123456",
                "is_thread_parent": False,
                "is_thread_reply": True,
                "timestamp": "2023-10-18T17:40:00Z"
            }
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        # Should have 1 parent with 1 reply nested
        assert len(result) == 1
        parent = result[0]
        assert parent["message_id"] == "1697654321.123456"
        assert "replies" in parent
        assert len(parent["replies"]) == 1
        assert parent["replies"][0]["message_id"] == "1697654400.123457"
        assert parent["replies"][0]["text"] == "Reply 1"

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_thread_with_multiple_replies(self):
        """Test thread parent with multiple replies"""
        flat_messages = [
            {"message_id": "111", "text": "Parent", "thread_ts": "111", "is_thread_parent": True, "is_thread_reply": False, "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "112", "text": "Reply 1", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:01:00Z"},
            {"message_id": "113", "text": "Reply 2", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:02:00Z"},
            {"message_id": "114", "text": "Reply 3", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:03:00Z"},
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        assert len(result) == 1
        parent = result[0]
        assert len(parent["replies"]) == 3
        assert parent["replies"][0]["text"] == "Reply 1"
        assert parent["replies"][1]["text"] == "Reply 2"
        assert parent["replies"][2]["text"] == "Reply 3"

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_replies_chronologically_sorted(self):
        """Test replies within thread are sorted chronologically"""
        # Intentionally out of order
        flat_messages = [
            {"message_id": "111", "text": "Parent", "thread_ts": "111", "is_thread_parent": True, "is_thread_reply": False, "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "114", "text": "Reply 3", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:03:00Z"},
            {"message_id": "112", "text": "Reply 1", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:01:00Z"},
            {"message_id": "113", "text": "Reply 2", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:02:00Z"},
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        parent = result[0]
        reply_timestamps = [r["timestamp"] for r in parent["replies"]]
        assert reply_timestamps == sorted(reply_timestamps)


class TestMultipleThreads:
    """Test handling multiple independent threads"""

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_two_independent_threads(self):
        """Test two independent threads are kept separate"""
        flat_messages = [
            # Thread 1
            {"message_id": "111", "text": "Thread 1 parent", "thread_ts": "111", "is_thread_parent": True, "is_thread_reply": False, "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "112", "text": "Thread 1 reply", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:01:00Z"},
            # Thread 2
            {"message_id": "222", "text": "Thread 2 parent", "thread_ts": "222", "is_thread_parent": True, "is_thread_reply": False, "timestamp": "2023-10-20T11:00:00Z"},
            {"message_id": "223", "text": "Thread 2 reply", "thread_ts": "222", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T11:01:00Z"},
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        assert len(result) == 2

        # Verify both threads have their replies
        thread1 = next(t for t in result if t["message_id"] == "111")
        thread2 = next(t for t in result if t["message_id"] == "222")

        assert len(thread1["replies"]) == 1
        assert thread1["replies"][0]["message_id"] == "112"

        assert len(thread2["replies"]) == 1
        assert thread2["replies"][0]["message_id"] == "223"

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_mixed_threads_and_standalone(self):
        """Test mix of threaded and standalone messages"""
        flat_messages = [
            # Standalone 1
            {"message_id": "100", "text": "Standalone 1", "thread_ts": None, "is_thread_parent": False, "is_thread_reply": False, "timestamp": "2023-10-20T09:00:00Z"},
            # Thread
            {"message_id": "111", "text": "Thread parent", "thread_ts": "111", "is_thread_parent": True, "is_thread_reply": False, "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "112", "text": "Thread reply", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:01:00Z"},
            # Standalone 2
            {"message_id": "200", "text": "Standalone 2", "thread_ts": None, "is_thread_parent": False, "is_thread_reply": False, "timestamp": "2023-10-20T11:00:00Z"},
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        assert len(result) == 3  # 2 standalone + 1 thread parent

        # Find the thread
        threaded = next(t for t in result if t["message_id"] == "111")
        assert len(threaded["replies"]) == 1

        # Find standalone messages
        standalones = [t for t in result if t["message_id"] in ["100", "200"]]
        assert len(standalones) == 2


class TestOrphanedReplies:
    """Test handling orphaned replies (parent missing)"""

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_orphaned_reply_marked_as_clipped(self):
        """Test reply without parent is marked as orphaned/clipped"""
        flat_messages = [
            # Orphaned reply (parent "111" not in dataset)
            {
                "message_id": "112",
                "text": "Orphaned reply",
                "thread_ts": "111",  # Parent not present
                "is_thread_parent": False,
                "is_thread_reply": True,
                "timestamp": "2023-10-20T10:01:00Z"
            },
            # Normal message
            {
                "message_id": "200",
                "text": "Normal message",
                "thread_ts": None,
                "is_thread_parent": False,
                "is_thread_reply": False,
                "timestamp": "2023-10-20T11:00:00Z"
            }
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        # Should have orphaned reply and normal message
        assert len(result) >= 1

        # Find the orphaned reply
        orphaned = next((m for m in result if m["message_id"] == "112"), None)
        assert orphaned is not None
        assert orphaned.get("is_clipped_thread") is True or orphaned.get("is_orphaned_reply") is True

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_multiple_orphaned_replies_same_parent(self):
        """Test multiple orphaned replies with same missing parent"""
        flat_messages = [
            {"message_id": "112", "text": "Reply 1", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:01:00Z"},
            {"message_id": "113", "text": "Reply 2", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:02:00Z"},
            {"message_id": "114", "text": "Reply 3", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:03:00Z"},
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        # All should be marked as orphaned
        assert len(result) == 3
        assert all(m.get("is_clipped_thread") or m.get("is_orphaned_reply") for m in result)

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_orphaned_replies_different_parents(self):
        """Test orphaned replies with different missing parents"""
        flat_messages = [
            {"message_id": "112", "text": "Reply to 111", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:01:00Z"},
            {"message_id": "223", "text": "Reply to 222", "thread_ts": "222", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T11:01:00Z"},
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        assert len(result) == 2
        # Both should be marked as orphaned
        assert all(m.get("is_clipped_thread") or m.get("is_orphaned_reply") for m in result)


class TestThreadMetadata:
    """Test thread metadata is preserved/calculated"""

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_parent_metadata_preserved(self):
        """Test parent message metadata is preserved"""
        flat_messages = [
            {
                "message_id": "111",
                "user_id": "U001",
                "user_real_name": "Alice",
                "text": "Parent",
                "thread_ts": "111",
                "is_thread_parent": True,
                "is_thread_reply": False,
                "reply_count": 2,
                "reactions": [{"emoji": "fire", "count": 3}],
                "jira_tickets": ["PROJ-123"],
                "timestamp": "2023-10-20T10:00:00Z"
            },
            {"message_id": "112", "text": "Reply", "thread_ts": "111", "is_thread_parent": False, "is_thread_reply": True, "timestamp": "2023-10-20T10:01:00Z"},
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        parent = result[0]
        # All original fields should be preserved
        assert parent["user_id"] == "U001"
        assert parent["user_real_name"] == "Alice"
        assert parent["reply_count"] == 2
        assert len(parent["reactions"]) == 1
        assert parent["jira_tickets"] == ["PROJ-123"]

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_reply_metadata_preserved(self):
        """Test reply message metadata is preserved"""
        flat_messages = [
            {"message_id": "111", "text": "Parent", "thread_ts": "111", "is_thread_parent": True, "is_thread_reply": False, "timestamp": "2023-10-20T10:00:00Z"},
            {
                "message_id": "112",
                "user_id": "U002",
                "user_real_name": "Bob",
                "text": "Reply with file",
                "thread_ts": "111",
                "is_thread_parent": False,
                "is_thread_reply": True,
                "files": [{"id": "F123", "name": "doc.pdf"}],
                "timestamp": "2023-10-20T10:01:00Z"
            },
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        parent = result[0]
        reply = parent["replies"][0]
        # Reply metadata should be preserved
        assert reply["user_id"] == "U002"
        assert reply["user_real_name"] == "Bob"
        assert len(reply["files"]) == 1


class TestEdgeCases:
    """Test edge cases and error handling"""

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_empty_message_list(self):
        """Test empty message list returns empty result"""
        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct([])

        assert result == []

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_thread_parent_without_replies(self):
        """Test thread parent that has no replies in dataset"""
        flat_messages = [
            {
                "message_id": "111",
                "text": "Thread parent with no replies in dataset",
                "thread_ts": "111",
                "is_thread_parent": True,
                "is_thread_reply": False,
                "reply_count": 5,  # Says 5 replies, but none present
                "timestamp": "2023-10-20T10:00:00Z"
            }
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        assert len(result) == 1
        parent = result[0]
        # Should still be present, just with empty or no replies
        assert len(parent.get("replies", [])) == 0
        # Should be marked as clipped since reply_count > 0 but no replies present
        assert parent.get("is_clipped_thread") is True or parent.get("has_clipped_replies") is True

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_maintains_chronological_order_of_parents(self):
        """Test parent messages maintain chronological order"""
        flat_messages = [
            # Out of chronological order
            {"message_id": "333", "text": "Message 3", "thread_ts": None, "is_thread_parent": False, "is_thread_reply": False, "timestamp": "2023-10-20T12:00:00Z"},
            {"message_id": "111", "text": "Message 1", "thread_ts": None, "is_thread_parent": False, "is_thread_reply": False, "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "222", "text": "Message 2", "thread_ts": None, "is_thread_parent": False, "is_thread_reply": False, "timestamp": "2023-10-20T11:00:00Z"},
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        # Should be reordered chronologically
        message_ids = [m["message_id"] for m in result]
        assert message_ids == ["111", "222", "333"]

    @pytest.mark.skipif(ThreadReconstructor is None, reason="ThreadReconstructor not implemented yet")
    def test_message_with_thread_ts_but_no_flags_treated_as_standalone(self):
        """Test messages with thread_ts but neither parent nor reply flag are treated as standalone

        This edge case occurs in real Slack data where Slack sets thread_ts on messages
        that aren't actually part of a thread conversation. These should be treated as
        standalone messages, not dropped.
        """
        flat_messages = [
            # Message with thread_ts but NOT a parent and NOT a reply
            {
                "message_id": "111",
                "text": "Has thread_ts but not parent/reply",
                "thread_ts": "111",  # Has thread_ts
                "is_thread_parent": False,  # Not marked as parent
                "is_thread_reply": False,  # Not marked as reply
                "timestamp": "2023-10-20T10:00:00Z",
                "user_id": "U001",
                "user_real_name": "Alice"
            },
            # Normal standalone for comparison
            {
                "message_id": "222",
                "text": "Normal standalone",
                "thread_ts": None,
                "is_thread_parent": False,
                "is_thread_reply": False,
                "timestamp": "2023-10-20T11:00:00Z",
                "user_id": "U002",
                "user_real_name": "Bob"
            }
        ]

        reconstructor = ThreadReconstructor()
        result = reconstructor.reconstruct(flat_messages)

        # Should have BOTH messages (not drop the first one!)
        assert len(result) == 2, f"Expected 2 messages but got {len(result)} - message was dropped!"

        # First message should be present and treated as standalone
        msg_111 = next((m for m in result if m["message_id"] == "111"), None)
        assert msg_111 is not None, "Message 111 was dropped!"
        assert msg_111["text"] == "Has thread_ts but not parent/reply"
        assert "replies" not in msg_111 or msg_111["replies"] == []

        # Second message should be present
        msg_222 = next((m for m in result if m["message_id"] == "222"), None)
        assert msg_222 is not None, "Message 222 was dropped!"
