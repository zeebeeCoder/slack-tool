"""Unit tests for MessageViewFormatter - TDD approach

Tests formatting structured messages into LLM-optimized text views.
Output should match the format of generate_llm_optimized_text() in slack_channels.py

These tests will FAIL until MessageViewFormatter is implemented.
"""

import pytest
from typing import List, Dict, Any


# This import will fail until we create the module
try:
    from slack_intel.message_view_formatter import MessageViewFormatter, ViewContext
except ImportError:
    MessageViewFormatter = None
    ViewContext = None


class TestBasicFormatting:
    """Test basic message formatting"""

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_format_single_message(self):
        """Test formatting a single standalone message"""
        messages = [
            {
                "message_id": "1697800000.000001",
                "user_real_name": "Alice Smith",
                "text": "Hello world",
                "timestamp": "2023-10-20T10:00:00Z",
                "reactions": [],
                "files": [],
                "jira_tickets": []
            }
        ]

        context = ViewContext(channel_name="engineering", date_range="2023-10-20")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        assert isinstance(view, str)
        assert "engineering" in view
        assert "Alice Smith" in view
        assert "Hello world" in view
        assert "2023-10-20" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_format_includes_header(self):
        """Test formatted view includes channel header"""
        messages = [
            {"message_id": "111", "user_real_name": "Bob", "text": "Test", "timestamp": "2023-10-20T10:00:00Z"}
        ]

        context = ViewContext(channel_name="design", date_range="2023-10-20")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # Should have header section
        assert "SLACK CHANNEL" in view or "Channel" in view
        assert "design" in view
        # Should have separators
        assert "=" in view or "-" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_format_multiple_messages(self):
        """Test formatting multiple standalone messages"""
        messages = [
            {"message_id": "111", "user_real_name": "Alice", "text": "Message 1", "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "222", "user_real_name": "Bob", "text": "Message 2", "timestamp": "2023-10-20T11:00:00Z"},
            {"message_id": "333", "user_real_name": "Charlie", "text": "Message 3", "timestamp": "2023-10-20T12:00:00Z"},
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        assert "Message 1" in view
        assert "Message 2" in view
        assert "Message 3" in view
        assert "Alice" in view
        assert "Bob" in view
        assert "Charlie" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_messages_appear_in_order(self):
        """Test messages appear in chronological order in output"""
        messages = [
            {"message_id": "111", "user_real_name": "Alice", "text": "First", "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "222", "user_real_name": "Bob", "text": "Second", "timestamp": "2023-10-20T11:00:00Z"},
            {"message_id": "333", "user_real_name": "Charlie", "text": "Third", "timestamp": "2023-10-20T12:00:00Z"},
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # Find positions in output
        first_pos = view.index("First")
        second_pos = view.index("Second")
        third_pos = view.index("Third")

        assert first_pos < second_pos < third_pos


class TestThreadFormatting:
    """Test formatting threaded messages"""

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_format_thread_with_replies(self):
        """Test thread replies are nested/indented under parent"""
        messages = [
            {
                "message_id": "111",
                "user_real_name": "Alice",
                "text": "Parent message",
                "timestamp": "2023-10-20T10:00:00Z",
                "replies": [
                    {
                        "message_id": "112",
                        "user_real_name": "Bob",
                        "text": "Reply to Alice",
                        "timestamp": "2023-10-20T10:01:00Z"
                    }
                ]
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        assert "Parent message" in view
        assert "Reply to Alice" in view

        # Thread structure indicators
        assert "THREAD" in view or "REPLIES" in view or "🧵" in view
        # Reply should be visually nested (indented or marked)
        assert "REPLY" in view or "↳" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_multiple_replies_shown(self):
        """Test multiple thread replies are all shown"""
        messages = [
            {
                "message_id": "111",
                "user_real_name": "Alice",
                "text": "Parent",
                "timestamp": "2023-10-20T10:00:00Z",
                "replies": [
                    {"message_id": "112", "user_real_name": "Bob", "text": "Reply 1", "timestamp": "2023-10-20T10:01:00Z"},
                    {"message_id": "113", "user_real_name": "Charlie", "text": "Reply 2", "timestamp": "2023-10-20T10:02:00Z"},
                    {"message_id": "114", "user_real_name": "Diana", "text": "Reply 3", "timestamp": "2023-10-20T10:03:00Z"},
                ]
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        assert "Reply 1" in view
        assert "Reply 2" in view
        assert "Reply 3" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_replies_in_chronological_order(self):
        """Test replies appear in chronological order"""
        messages = [
            {
                "message_id": "111",
                "user_real_name": "Alice",
                "text": "Parent",
                "timestamp": "2023-10-20T10:00:00Z",
                "replies": [
                    {"message_id": "112", "text": "Reply First", "timestamp": "2023-10-20T10:01:00Z"},
                    {"message_id": "113", "text": "Reply Second", "timestamp": "2023-10-20T10:02:00Z"},
                    {"message_id": "114", "text": "Reply Third", "timestamp": "2023-10-20T10:03:00Z"},
                ]
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        first_pos = view.index("Reply First")
        second_pos = view.index("Reply Second")
        third_pos = view.index("Reply Third")

        assert first_pos < second_pos < third_pos


class TestClippedThreads:
    """Test formatting clipped/orphaned threads"""

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_clipped_thread_indicator(self):
        """Test clipped threads show visual indicator"""
        messages = [
            {
                "message_id": "112",
                "user_real_name": "Bob",
                "text": "Orphaned reply",
                "timestamp": "2023-10-20T10:01:00Z",
                "is_clipped_thread": True,  # Marked by ThreadReconstructor
                "is_orphaned_reply": True
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # Should indicate thread is clipped
        assert "clipped" in view.lower() or "orphaned" in view.lower() or "🔗" in view
        # Should suggest widening date range
        assert "widen" in view.lower() or "extends beyond" in view.lower() or "💡" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_parent_with_clipped_replies(self):
        """Test thread parent with some replies outside range"""
        messages = [
            {
                "message_id": "111",
                "user_real_name": "Alice",
                "text": "Thread parent",
                "timestamp": "2023-10-20T10:00:00Z",
                "reply_count": 5,  # Says 5 replies total
                "is_clipped_thread": True,  # But some are missing
                "has_clipped_replies": True,
                "replies": [
                    # Only 2 replies shown, but reply_count is 5
                    {"message_id": "112", "text": "Reply 1", "timestamp": "2023-10-20T10:01:00Z"},
                    {"message_id": "113", "text": "Reply 2", "timestamp": "2023-10-20T10:02:00Z"},
                ]
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # Should show the available replies
        assert "Reply 1" in view
        assert "Reply 2" in view
        # Should indicate more replies exist
        assert "2 of 5" in view or "showing 2" in view.lower() or "clipped" in view.lower()


class TestRichContent:
    """Test formatting reactions, files, JIRA tickets"""

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_format_reactions(self):
        """Test reactions are shown in output"""
        messages = [
            {
                "message_id": "111",
                "user_real_name": "Alice",
                "text": "Great work!",
                "timestamp": "2023-10-20T10:00:00Z",
                "reactions": [
                    {"emoji": "100", "count": 3, "users": ["U1", "U2", "U3"]},
                    {"emoji": "fire", "count": 2, "users": ["U4", "U5"]}
                ]
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # Should show reactions
        assert "100" in view or ":100:" in view
        assert "fire" in view or ":fire:" in view
        # Should show counts
        assert "3" in view
        assert "2" in view
        # Should have reaction indicator
        assert "Reactions" in view or "😊" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_format_files(self):
        """Test file attachments are shown"""
        messages = [
            {
                "message_id": "111",
                "user_real_name": "Alice",
                "text": "Check this out",
                "timestamp": "2023-10-20T10:00:00Z",
                "files": [
                    {"id": "F123", "name": "design.pdf", "mimetype": "application/pdf", "size": 500000}
                ]
            }
        ]

        context = ViewContext(channel_name="design")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        assert "design.pdf" in view
        assert "pdf" in view.lower()
        # Should have file indicator
        assert "Files" in view or "📎" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_format_jira_tickets(self):
        """Test JIRA tickets are highlighted"""
        messages = [
            {
                "message_id": "111",
                "user_real_name": "Bob",
                "text": "Working on PROJ-123",
                "timestamp": "2023-10-20T10:00:00Z",
                "jira_tickets": ["PROJ-123", "PROJ-456"]
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # JIRA tickets should be visible
        assert "PROJ-123" in view
        assert "PROJ-456" in view


class TestSummaryStatistics:
    """Test summary section formatting"""

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_summary_section_included(self):
        """Test formatted view includes summary statistics"""
        messages = [
            {"message_id": "111", "user_real_name": "Alice", "text": "Msg 1", "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "222", "user_real_name": "Bob", "text": "Msg 2", "timestamp": "2023-10-20T11:00:00Z"},
            {
                "message_id": "333",
                "user_real_name": "Alice",
                "text": "Thread parent",
                "timestamp": "2023-10-20T12:00:00Z",
                "replies": [
                    {"message_id": "334", "text": "Reply", "timestamp": "2023-10-20T12:01:00Z"}
                ]
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # Should have summary section
        assert "SUMMARY" in view or "Summary" in view or "📊" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_summary_shows_message_count(self):
        """Test summary shows correct message count"""
        messages = [
            {"message_id": "111", "text": "Msg 1", "timestamp": "2023-10-20T10:00:00Z"},
            {"message_id": "222", "text": "Msg 2", "timestamp": "2023-10-20T11:00:00Z"},
            {"message_id": "333", "text": "Msg 3", "timestamp": "2023-10-20T12:00:00Z"},
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # Should show count of 3 messages
        assert "3" in view
        assert "Messages" in view or "messages" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_summary_shows_thread_count(self):
        """Test summary shows thread count"""
        messages = [
            {
                "message_id": "111",
                "text": "Thread 1",
                "timestamp": "2023-10-20T10:00:00Z",
                "replies": [{"message_id": "112", "text": "R1", "timestamp": "2023-10-20T10:01:00Z"}]
            },
            {
                "message_id": "222",
                "text": "Thread 2",
                "timestamp": "2023-10-20T11:00:00Z",
                "replies": [{"message_id": "223", "text": "R2", "timestamp": "2023-10-20T11:01:00Z"}]
            },
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # Should indicate 2 threads
        assert "Thread" in view or "thread" in view
        assert "2" in view


class TestEmptyAndEdgeCases:
    """Test edge cases and error handling"""

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_format_empty_messages(self):
        """Test formatting empty message list returns informative message"""
        context = ViewContext(channel_name="engineering", date_range="2023-10-20")
        formatter = MessageViewFormatter()
        view = formatter.format([], context)

        assert isinstance(view, str)
        assert len(view) > 0
        # Should indicate no messages
        assert "No messages" in view or "empty" in view.lower() or "0 messages" in view.lower()
        # Should still show channel context
        assert "engineering" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_special_characters_handled(self):
        """Test special characters, emojis, etc. are handled"""
        messages = [
            {
                "message_id": "111",
                "user_real_name": "Alice",
                "text": "Test with emoji 🚀 and <special> chars & symbols",
                "timestamp": "2023-10-20T10:00:00Z"
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view = formatter.format(messages, context)

        # Should preserve special content
        assert "🚀" in view
        assert "Test with emoji" in view

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_missing_optional_fields(self):
        """Test messages with missing optional fields don't crash"""
        messages = [
            {
                "message_id": "111",
                "text": "Minimal message",
                "timestamp": "2023-10-20T10:00:00Z",
                # Missing: user_real_name, reactions, files, jira_tickets
            }
        ]

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        # Should not crash
        view = formatter.format(messages, context)

        assert isinstance(view, str)
        assert "Minimal message" in view


class TestMentionResolution:
    """Tests for user mention resolution"""

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_resolve_mentions_in_text(self):
        """Test that user mentions are resolved from <@USER_ID> to @username"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen",
                "text": "Hey <@U002>, can you review this?",
                "timestamp": "2023-10-20T10:00:00Z",
            },
            {
                "message_id": "2",
                "user_id": "U002",
                "user_name": "bob",
                "user_real_name": "Bob Martinez",
                "text": "Sure <@U001>! Looking at it now.",
                "timestamp": "2023-10-20T10:05:00Z",
            },
        ]

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter()
        output = formatter.format(messages, context)

        # Mentions should be resolved to real names
        assert "@Bob Martinez" in output
        assert "@Alice Chen" in output
        # Raw user IDs should not appear
        assert "<@U001>" not in output
        assert "<@U002>" not in output

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_unresolved_mentions_kept_as_is(self):
        """Test that mentions for users not in dataset are kept as-is"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen",
                "text": "Hey <@U999>, can you help?",  # U999 not in dataset
                "timestamp": "2023-10-20T10:00:00Z",
            },
        ]

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter()
        output = formatter.format(messages, context)

        # Unknown mention should remain as-is
        assert "<@U999>" in output

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_disable_mention_resolution(self):
        """Test that mention resolution can be disabled"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen",
                "text": "Hey <@U002>!",
                "timestamp": "2023-10-20T10:00:00Z",
            },
            {
                "message_id": "2",
                "user_id": "U002",
                "user_name": "bob",
                "user_real_name": "Bob Martinez",
                "text": "Hi!",
                "timestamp": "2023-10-20T10:05:00Z",
            },
        ]

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter(resolve_mentions=False)
        output = formatter.format(messages, context)

        # Mentions should NOT be resolved
        assert "<@U002>" in output
        assert "@Bob Martinez" not in output

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_resolve_mentions_in_thread_replies(self):
        """Test that mentions are resolved in thread replies too"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen",
                "text": "Question about the API",
                "timestamp": "2023-10-20T10:00:00Z",
                "thread_ts": "1",
                "is_thread_parent": True,
                "replies": [
                    {
                        "message_id": "2",
                        "user_id": "U002",
                        "user_name": "bob",
                        "user_real_name": "Bob Martinez",
                        "text": "<@U001> here's the answer",
                        "timestamp": "2023-10-20T10:05:00Z",
                        "is_thread_reply": True,
                    }
                ],
            },
        ]

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter()
        output = formatter.format(messages, context)

        # Mention in reply should be resolved
        assert "@Alice Chen" in output
        assert "<@U001>" not in output


class TestViewContext:
    """Test ViewContext dataclass"""

    @pytest.mark.skipif(ViewContext is None, reason="ViewContext not implemented yet")
    def test_view_context_creation(self):
        """Test creating ViewContext with different parameters"""
        # Minimal context
        ctx1 = ViewContext(channel_name="engineering")
        assert ctx1.channel_name == "engineering"

        # With date range
        ctx2 = ViewContext(channel_name="design", date_range="2023-10-18 to 2023-10-20")
        assert ctx2.date_range == "2023-10-18 to 2023-10-20"

    @pytest.mark.skipif(ViewContext is None, reason="ViewContext not implemented yet")
    def test_multi_channel_context(self):
        """Test context for multi-channel views"""
        ctx = ViewContext(
            channel_name="Multi-Channel",
            channels=["engineering", "design", "product"]
        )

        assert "engineering" in ctx.channels
        assert "design" in ctx.channels
        assert "product" in ctx.channels


class TestCachedUserMentionResolution:
    """Test mention resolution using cached users"""

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_resolve_mentions_from_cached_users(self):
        """Test mentions are resolved using cached users (users not in messages)"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen",
                "text": "Hey <@U003>, can you help?",  # U003 not an author
                "timestamp": "2023-10-20T10:00:00Z",
            },
        ]

        # Cached users include U003
        cached_users = {
            "U003": {
                "user_id": "U003",
                "user_name": "carol",
                "user_real_name": "Carol Williams",
                "user_email": "carol@example.com"
            }
        }

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter()
        output = formatter.format(messages, context, cached_users=cached_users)

        # Should resolve U003 from cached users
        assert "@Carol Williams" in output
        assert "<@U003>" not in output

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_message_authors_override_cached_users(self):
        """Test that message authors have fresher data and override cached users"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen (Updated)",  # Fresher name
                "text": "Mentioning <@U001>",  # Self-mention
                "timestamp": "2023-10-20T10:00:00Z",
            },
        ]

        # Cached users has old name for U001
        cached_users = {
            "U001": {
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen (Old)",  # Old name
                "user_email": "alice@example.com"
            }
        }

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter()
        output = formatter.format(messages, context, cached_users=cached_users)

        # Should use fresher name from message author, not cached
        assert "@Alice Chen (Updated)" in output
        assert "@Alice Chen (Old)" not in output

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_cached_users_with_empty_dict(self):
        """Test that empty cached_users dict is handled gracefully"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen",
                "text": "Hey <@U999>!",  # Unknown user
                "timestamp": "2023-10-20T10:00:00Z",
            },
        ]

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter()
        output = formatter.format(messages, context, cached_users={})

        # Unknown mention should remain unresolved
        assert "<@U999>" in output

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_cached_users_none(self):
        """Test that None cached_users is handled (backwards compatibility)"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen",
                "text": "Hey <@U002>!",
                "timestamp": "2023-10-20T10:00:00Z",
            },
            {
                "message_id": "2",
                "user_id": "U002",
                "user_name": "bob",
                "user_real_name": "Bob Martinez",
                "text": "Hi!",
                "timestamp": "2023-10-20T10:05:00Z",
            },
        ]

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter()
        output = formatter.format(messages, context, cached_users=None)

        # Should still resolve from message authors
        assert "@Bob Martinez" in output
        assert "<@U002>" not in output

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_cached_users_with_replies(self):
        """Test cached users work with thread replies"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen",
                "text": "Question about the API",
                "timestamp": "2023-10-20T10:00:00Z",
                "replies": [
                    {
                        "message_id": "2",
                        "user_id": "U002",
                        "user_name": "bob",
                        "user_real_name": "Bob Martinez",
                        "text": "Thanks <@U003> for the help!",  # U003 not an author
                        "timestamp": "2023-10-20T10:05:00Z",
                    }
                ],
            },
        ]

        # Cached users include U003
        cached_users = {
            "U003": {
                "user_id": "U003",
                "user_name": "carol",
                "user_real_name": "Carol Williams",
            }
        }

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter()
        output = formatter.format(messages, context, cached_users=cached_users)

        # Should resolve U003 from cached users in reply
        assert "@Carol Williams" in output
        assert "<@U003>" not in output

    @pytest.mark.skipif(MessageViewFormatter is None, reason="MessageViewFormatter not implemented yet")
    def test_multiple_cached_users(self):
        """Test resolving mentions for multiple users from cache"""
        messages = [
            {
                "message_id": "1",
                "user_id": "U001",
                "user_name": "alice",
                "user_real_name": "Alice Chen",
                "text": "CC <@U003> <@U004> <@U005>",  # All not in messages
                "timestamp": "2023-10-20T10:00:00Z",
            },
        ]

        # Cached users for all mentioned users
        cached_users = {
            "U003": {"user_id": "U003", "user_real_name": "Carol Williams"},
            "U004": {"user_id": "U004", "user_real_name": "David Lee"},
            "U005": {"user_id": "U005", "user_real_name": "Eve Anderson"},
        }

        context = ViewContext(channel_name="test")
        formatter = MessageViewFormatter()
        output = formatter.format(messages, context, cached_users=cached_users)

        # All mentions should be resolved
        assert "@Carol Williams" in output
        assert "@David Lee" in output
        assert "@Eve Anderson" in output
        assert "<@U003>" not in output
        assert "<@U004>" not in output
        assert "<@U005>" not in output
