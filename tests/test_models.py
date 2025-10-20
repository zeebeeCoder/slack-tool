"""Test Pydantic models"""

import pytest
from datetime import datetime

from slack_intel import (
    SlackChannel,
    TimeWindow,
    SlackMessage,
)


class TestSlackChannel:
    """Test SlackChannel model"""

    def test_valid_channel(self):
        """Test creating a valid channel"""
        channel = SlackChannel(name="test-channel", id="C0123456789")
        assert channel.name == "test-channel"
        assert channel.id == "C0123456789"

    def test_invalid_channel_id(self):
        """Test that channel ID must start with C"""
        with pytest.raises(ValueError, match="Channel ID must start with C"):
            SlackChannel(name="test", id="X0123456789")


class TestTimeWindow:
    """Test TimeWindow model"""

    def test_default_window(self):
        """Test default time window"""
        window = TimeWindow()
        assert window.days == 0
        assert window.hours == 4

    def test_custom_window(self):
        """Test custom time window"""
        window = TimeWindow(days=7, hours=12)
        assert window.days == 7
        assert window.hours == 12

    def test_timestamps(self):
        """Test timestamp calculation"""
        window = TimeWindow(days=1, hours=0)
        assert window.start_time > 0
        assert window.end_time > window.start_time
        # End time should be approximately now
        assert abs(window.end_time - datetime.now().timestamp()) < 1


class TestSlackMessage:
    """Test SlackMessage model"""

    def test_basic_message(self):
        """Test basic message creation"""
        msg = SlackMessage(
            ts="1234567890.123456",
            user="U0123456789",
            text="Test message"
        )
        assert msg.ts == "1234567890.123456"
        assert msg.user == "U0123456789"
        assert msg.text == "Test message"

    def test_timestamp_property(self):
        """Test timestamp conversion"""
        msg = SlackMessage(
            ts="1234567890.123456",
            text="Test"
        )
        timestamp = msg.timestamp
        assert isinstance(timestamp, datetime)
        assert timestamp.timestamp() == 1234567890.123456

    def test_thread_detection(self):
        """Test thread parent/reply detection"""
        # Standalone message
        standalone = SlackMessage(ts="123.456", text="Standalone")
        assert not standalone.is_thread_parent
        assert not standalone.is_thread_reply

        # Thread reply
        reply = SlackMessage(
            ts="123.789",
            thread_ts="123.456",  # Different from ts
            text="Reply"
        )
        assert not reply.is_thread_parent
        assert reply.is_thread_reply
