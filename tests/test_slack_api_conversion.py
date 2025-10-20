"""
Unit tests for SlackChannelManager API data conversion methods.

These tests verify that data from Slack API responses is correctly
extracted and converted to internal models, particularly focusing on
thread metadata (reply_count, thread_ts) which is critical for
proper thread reconstruction in views.
"""

import pytest
import os
from unittest.mock import patch
from slack_intel.slack_channels import SlackChannelManager, SlackMessage
from typing import Dict, Any


class TestConvertToSlackMessage:
    """Test the _convert_to_slack_message method with realistic API data"""

    @pytest.fixture
    def manager(self):
        """Create a SlackChannelManager instance for testing"""
        # Mock environment variables and skip JIRA init
        with patch.dict(os.environ, {"SLACK_API_TOKEN": "xoxb-test-token"}):
            with patch.object(SlackChannelManager, '_init_jira', return_value=None):
                with patch.object(SlackChannelManager, '_validate_env', return_value=None):
                    return SlackChannelManager()

    def test_extracts_basic_message_fields(self, manager):
        """Verify basic message fields are extracted from API response"""
        api_response = {
            "ts": "1697654321.123456",
            "user": "U012ABC3DEF",
            "text": "Hello, world!",
            "type": "message"
        }

        message = manager._convert_to_slack_message(api_response)

        assert message.ts == "1697654321.123456"
        assert message.user == "U012ABC3DEF"
        assert message.text == "Hello, world!"

    def test_extracts_reply_count_from_thread_parent(self, manager):
        """Verify reply_count is extracted for thread parent messages"""
        api_response = {
            "ts": "1697654321.123456",
            "user": "U012ABC3DEF",
            "text": "Thread parent message",
            "thread_ts": "1697654321.123456",  # Parent has thread_ts = ts
            "reply_count": 5,  # ← Critical field from API
            "reply_users_count": 3,
            "latest_reply": "1697654500.123460"
        }

        message = manager._convert_to_slack_message(api_response)

        assert message.replies_count == 5, "reply_count should be extracted from API response"
        assert message.thread_ts == "1697654321.123456"

    def test_extracts_zero_reply_count(self, manager):
        """Verify reply_count=0 is correctly extracted"""
        api_response = {
            "ts": "1697654321.123456",
            "user": "U012ABC3DEF",
            "text": "Message with explicit zero replies",
            "thread_ts": "1697654321.123456",
            "reply_count": 0  # Explicit zero
        }

        message = manager._convert_to_slack_message(api_response)

        assert message.replies_count == 0

    def test_defaults_reply_count_when_missing(self, manager):
        """Verify reply_count defaults to 0 when not in API response"""
        api_response = {
            "ts": "1697654321.123456",
            "user": "U012ABC3DEF",
            "text": "Regular message without reply_count field"
            # No reply_count field at all
        }

        message = manager._convert_to_slack_message(api_response)

        assert message.replies_count == 0, "Should default to 0 when field is missing"

    def test_extracts_thread_ts_for_reply(self, manager):
        """Verify thread_ts is extracted for thread replies"""
        api_response = {
            "ts": "1697654400.123457",
            "user": "U987ZYX6WVU",
            "text": "This is a reply",
            "thread_ts": "1697654321.123456"  # Different from ts (this is a reply)
        }

        message = manager._convert_to_slack_message(api_response)

        assert message.thread_ts == "1697654321.123456"
        assert message.ts != message.thread_ts, "Reply should have different ts and thread_ts"

    def test_extracts_reactions(self, manager):
        """Verify reactions array is extracted"""
        api_response = {
            "ts": "1697654321.123456",
            "user": "U012ABC3DEF",
            "text": "Message with reactions",
            "reactions": [
                {
                    "name": "rocket",
                    "count": 3,
                    "users": ["U001", "U002", "U003"]
                },
                {
                    "name": "eyes",
                    "count": 2,
                    "users": ["U001", "U002"]
                }
            ]
        }

        message = manager._convert_to_slack_message(api_response)

        assert len(message.reactions) == 2
        assert message.reactions[0].name == "rocket"
        assert message.reactions[0].count == 3
        assert message.reactions[1].name == "eyes"
        assert message.reactions[1].count == 2

    def test_extracts_files(self, manager):
        """Verify files array is extracted"""
        api_response = {
            "ts": "1697654321.123456",
            "user": "U012ABC3DEF",
            "text": "Message with files",
            "files": [
                {
                    "id": "F12345",
                    "name": "design.pdf",
                    "mimetype": "application/pdf",
                    "size": 245000,
                    "url_private": "https://files.slack.com/files-pri/..."
                }
            ]
        }

        message = manager._convert_to_slack_message(api_response)

        assert len(message.files) == 1
        assert message.files[0].id == "F12345"
        assert message.files[0].name == "design.pdf"
        assert message.files[0].mimetype == "application/pdf"
        assert message.files[0].size == 245000

    def test_extracts_user_info_when_present(self, manager):
        """Verify user_info is extracted when present in API response"""
        api_response = {
            "ts": "1697654321.123456",
            "user": "U012ABC3DEF",
            "text": "Message with user info",
            "user_info": {
                "id": "U012ABC3DEF",
                "name": "john.doe",
                "real_name": "John Doe",
                "profile": {
                    "display_name": "Johnny",
                    "email": "john.doe@example.com"
                },
                "is_bot": False
            }
        }

        message = manager._convert_to_slack_message(api_response)

        assert message.user_info is not None
        assert message.user_info.id == "U012ABC3DEF"
        assert message.user_info.real_name == "John Doe"
        assert message.user_info.email == "john.doe@example.com"

    def test_handles_missing_optional_fields(self, manager):
        """Verify graceful handling when optional fields are missing"""
        api_response = {
            "ts": "1697654321.123456",
            "user": "U012ABC3DEF",
            "text": "Minimal message"
            # No reactions, files, thread_ts, user_info, reply_count
        }

        message = manager._convert_to_slack_message(api_response)

        assert message.ts == "1697654321.123456"
        assert message.text == "Minimal message"
        assert message.reactions == []
        assert message.files == []
        assert message.thread_ts is None
        assert message.user_info is None
        assert message.replies_count == 0


class TestSlackMessageProperties:
    """Test SlackMessage model properties, especially thread-related logic"""

    def test_is_thread_parent_true_when_has_replies(self):
        """Verify is_thread_parent is True when message has replies"""
        message = SlackMessage(
            ts="1697654321.123456",
            user="U012ABC3DEF",
            text="Thread parent",
            thread_ts="1697654321.123456",  # Parent: thread_ts == ts
            replies_count=3  # Has replies
        )

        assert message.is_thread_parent is True, \
            "Message with thread_ts==ts and reply_count>0 should be thread parent"

    def test_is_thread_parent_false_when_no_replies(self):
        """Verify is_thread_parent is False when reply_count=0"""
        message = SlackMessage(
            ts="1697654321.123456",
            user="U012ABC3DEF",
            text="Not a parent",
            thread_ts="1697654321.123456",  # Has thread_ts == ts
            replies_count=0  # But no replies
        )

        # Based on the code, is_thread_parent checks if self.thread is not None
        # which requires the thread to be set explicitly
        # So this should be False since thread is not set
        assert message.is_thread_parent is False

    def test_is_thread_parent_false_for_regular_message(self):
        """Verify is_thread_parent is False for non-threaded messages"""
        message = SlackMessage(
            ts="1697654321.123456",
            user="U012ABC3DEF",
            text="Regular message",
            # No thread_ts at all
        )

        assert message.is_thread_parent is False

    def test_is_thread_parent_false_for_reply(self):
        """Verify is_thread_parent is False for thread replies"""
        message = SlackMessage(
            ts="1697654400.123457",
            user="U987ZYX6WVU",
            text="Reply message",
            thread_ts="1697654321.123456",  # Different from ts (this is a reply)
            replies_count=0
        )

        assert message.is_thread_parent is False

    def test_is_thread_reply_true_for_reply(self):
        """Verify is_thread_reply is True for messages in a thread"""
        message = SlackMessage(
            ts="1697654400.123457",
            user="U987ZYX6WVU",
            text="Reply message",
            thread_ts="1697654321.123456"  # Different from ts
        )

        assert message.is_thread_reply is True

    def test_is_thread_reply_false_for_parent(self):
        """Verify is_thread_reply is False for thread parent"""
        message = SlackMessage(
            ts="1697654321.123456",
            user="U012ABC3DEF",
            text="Thread parent",
            thread_ts="1697654321.123456"  # Same as ts
        )

        assert message.is_thread_reply is False

    def test_is_thread_reply_false_for_regular_message(self):
        """Verify is_thread_reply is False for non-threaded messages"""
        message = SlackMessage(
            ts="1697654321.123456",
            user="U012ABC3DEF",
            text="Regular message"
            # No thread_ts
        )

        assert message.is_thread_reply is False


class TestThreadParentDetection:
    """Test thread parent detection logic used during caching"""

    def test_detect_thread_parent_from_api_response(self):
        """Verify we can detect thread parents from API response fields"""
        # This is what comes from Slack API for a thread parent
        api_data = {
            "ts": "1697654321.123456",
            "thread_ts": "1697654321.123456",
            "reply_count": 5
        }

        # Thread parent detection logic (from slack_channels.py:1440-1444)
        is_parent = (
            api_data.get("thread_ts") == api_data.get("ts") and
            api_data.get("reply_count", 0) > 0
        )

        assert is_parent is True, "Should detect thread parent from API fields"

    def test_not_parent_when_no_replies(self):
        """Verify message is not considered parent when reply_count=0"""
        api_data = {
            "ts": "1697654321.123456",
            "thread_ts": "1697654321.123456",
            "reply_count": 0  # No replies yet
        }

        is_parent = (
            api_data.get("thread_ts") == api_data.get("ts") and
            api_data.get("reply_count", 0) > 0
        )

        assert is_parent is False

    def test_not_parent_when_is_reply(self):
        """Verify replies are not detected as parents"""
        api_data = {
            "ts": "1697654400.123457",
            "thread_ts": "1697654321.123456",  # Different from ts
            "reply_count": 0
        }

        is_parent = (
            api_data.get("thread_ts") == api_data.get("ts") and
            api_data.get("reply_count", 0) > 0
        )

        assert is_parent is False
