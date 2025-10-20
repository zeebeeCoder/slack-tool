"""Integration tests for full message view pipeline

Tests the complete flow:
  Parquet → ParquetMessageReader → ThreadReconstructor → MessageViewFormatter → Output

Uses realistic synthetic data to verify end-to-end functionality.
"""

import pytest
from pathlib import Path
from datetime import datetime
import pyarrow as pa
import pyarrow.parquet as pq

from slack_intel.parquet_message_reader import ParquetMessageReader
from slack_intel.thread_reconstructor import ThreadReconstructor
from slack_intel.message_view_formatter import MessageViewFormatter, ViewContext


@pytest.fixture
def realistic_parquet_cache(tmp_path):
    """Create realistic Parquet cache mimicking actual Slack data"""
    base_path = tmp_path / "cache" / "raw" / "messages"

    # Schema matching our Parquet schema
    schema = pa.schema([
        ("message_id", pa.string()),
        ("user_id", pa.string()),
        ("text", pa.string()),
        ("timestamp", pa.string()),
        ("thread_ts", pa.string()),
        ("is_thread_parent", pa.bool_()),
        ("is_thread_reply", pa.bool_()),
        ("reply_count", pa.int64()),
        ("user_name", pa.string()),
        ("user_real_name", pa.string()),
        ("user_email", pa.string()),
        ("user_is_bot", pa.bool_()),
        ("reactions", pa.list_(pa.struct([
            ("emoji", pa.string()),
            ("count", pa.int64()),
            ("users", pa.list_(pa.string()))
        ]))),
        ("files", pa.list_(pa.struct([
            ("id", pa.string()),
            ("name", pa.string()),
            ("mimetype", pa.string()),
            ("url", pa.string()),
            ("size", pa.int64())
        ]))),
        ("jira_tickets", pa.list_(pa.string())),
        ("has_reactions", pa.bool_()),
        ("has_files", pa.bool_()),
        ("has_thread", pa.bool_()),
    ])

    # Realistic engineering channel data for 2025-10-20
    engineering_messages = [
        # Morning standup
        {
            "message_id": "1729411200.000001",
            "user_id": "U001",
            "text": "Good morning team! Starting the day with PROJ-456 implementation",
            "timestamp": "2025-10-20T08:00:00Z",
            "thread_ts": None,
            "is_thread_parent": False,
            "is_thread_reply": False,
            "reply_count": 0,
            "user_name": "alice",
            "user_real_name": "Alice Chen",
            "user_email": "alice@example.com",
            "user_is_bot": False,
            "reactions": [{"emoji": "coffee", "count": 3, "users": ["U002", "U003", "U004"]}],
            "files": [],
            "jira_tickets": ["PROJ-456"],
            "has_reactions": True,
            "has_files": False,
            "has_thread": False,
        },

        # Code review request - thread parent
        {
            "message_id": "1729414800.000002",
            "user_id": "U002",
            "text": "Can someone review my PR for PROJ-123? It fixes the authentication bug we discussed yesterday.",
            "timestamp": "2025-10-20T09:00:00Z",
            "thread_ts": "1729414800.000002",
            "is_thread_parent": True,
            "is_thread_reply": False,
            "reply_count": 3,
            "user_name": "bob",
            "user_real_name": "Bob Martinez",
            "user_email": "bob@example.com",
            "user_is_bot": False,
            "reactions": [{"emoji": "eyes", "count": 2, "users": ["U001", "U003"]}],
            "files": [],
            "jira_tickets": ["PROJ-123"],
            "has_reactions": True,
            "has_files": False,
            "has_thread": True,
        },

        # Reply 1 to code review
        {
            "message_id": "1729415100.000003",
            "user_id": "U001",
            "text": "Looking at it now! Will have feedback in 10 min",
            "timestamp": "2025-10-20T09:05:00Z",
            "thread_ts": "1729414800.000002",
            "is_thread_parent": False,
            "is_thread_reply": True,
            "reply_count": 0,
            "user_name": "alice",
            "user_real_name": "Alice Chen",
            "user_email": "alice@example.com",
            "user_is_bot": False,
            "reactions": [{"emoji": "+1", "count": 1, "users": ["U002"]}],
            "files": [],
            "jira_tickets": [],
            "has_reactions": True,
            "has_files": False,
            "has_thread": False,
        },

        # Reply 2 to code review
        {
            "message_id": "1729415700.000004",
            "user_id": "U001",
            "text": "LGTM! Left a few minor comments on the error handling. Otherwise looks great 🚀",
            "timestamp": "2025-10-20T09:15:00Z",
            "thread_ts": "1729414800.000002",
            "is_thread_parent": False,
            "is_thread_reply": True,
            "reply_count": 0,
            "user_name": "alice",
            "user_real_name": "Alice Chen",
            "user_email": "alice@example.com",
            "user_is_bot": False,
            "reactions": [{"emoji": "100", "count": 2, "users": ["U002", "U003"]}],
            "files": [],
            "jira_tickets": [],
            "has_reactions": True,
            "has_files": False,
            "has_thread": False,
        },

        # Reply 3 to code review
        {
            "message_id": "1729416000.000005",
            "user_id": "U002",
            "text": "Thanks! Addressed your comments and pushing now. Merging after CI passes.",
            "timestamp": "2025-10-20T09:20:00Z",
            "thread_ts": "1729414800.000002",
            "is_thread_parent": False,
            "is_thread_reply": True,
            "reply_count": 0,
            "user_name": "bob",
            "user_real_name": "Bob Martinez",
            "user_email": "bob@example.com",
            "user_is_bot": False,
            "reactions": [],
            "files": [],
            "jira_tickets": [],
            "has_reactions": False,
            "has_files": False,
            "has_thread": False,
        },

        # Design discussion with file attachment
        {
            "message_id": "1729425600.000006",
            "user_id": "U003",
            "text": "Updated the API design doc based on our conversation. Thoughts on the new schema?",
            "timestamp": "2025-10-20T12:00:00Z",
            "thread_ts": None,
            "is_thread_parent": False,
            "is_thread_reply": False,
            "reply_count": 0,
            "user_name": "charlie",
            "user_real_name": "Charlie Davis",
            "user_email": "charlie@example.com",
            "user_is_bot": False,
            "reactions": [],
            "files": [
                {
                    "id": "F123456",
                    "name": "api-design-v2.pdf",
                    "mimetype": "application/pdf",
                    "url": "https://files.slack.com/F123456",
                    "size": 245000
                }
            ],
            "jira_tickets": ["DESIGN-789"],
            "has_reactions": False,
            "has_files": True,
            "has_thread": False,
        },

        # Deployment notification from bot
        {
            "message_id": "1729432800.000007",
            "user_id": "UBOT001",
            "text": "✅ Deployment to staging successful!\nBuild: #342\nCommit: abc123def\nJIRA: PROJ-123, PROJ-456",
            "timestamp": "2025-10-20T14:00:00Z",
            "thread_ts": None,
            "is_thread_parent": False,
            "is_thread_reply": False,
            "reply_count": 0,
            "user_name": "deploybot",
            "user_real_name": "Deploy Bot",
            "user_email": None,
            "user_is_bot": True,
            "reactions": [
                {"emoji": "rocket", "count": 4, "users": ["U001", "U002", "U003", "U004"]},
                {"emoji": "tada", "count": 2, "users": ["U001", "U002"]}
            ],
            "files": [],
            "jira_tickets": ["PROJ-123", "PROJ-456"],
            "has_reactions": True,
            "has_files": False,
            "has_thread": False,
        },
    ]

    # Write to Parquet
    partition_dir = base_path / "dt=2025-10-20" / "channel=engineering"
    partition_dir.mkdir(parents=True, exist_ok=True)

    table = pa.Table.from_pylist(engineering_messages, schema=schema)
    pq.write_table(table, partition_dir / "data.parquet", compression='snappy')

    return str(tmp_path / "cache")


@pytest.mark.integration
class TestFullMessageViewPipeline:
    """Integration tests for complete message view pipeline"""

    def test_end_to_end_pipeline(self, realistic_parquet_cache):
        """Test complete pipeline: Read → Reconstruct → Format"""
        # Step 1: Read from Parquet
        reader = ParquetMessageReader(base_path=realistic_parquet_cache)
        flat_messages = reader.read_channel("engineering", "2025-10-20")

        assert len(flat_messages) == 7, "Should read all 7 messages"

        # Step 2: Reconstruct threads
        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)

        # Should have fewer top-level messages (thread replies nested)
        assert len(structured_messages) == 4, "Should have 4 top-level items (3 replies nested)"

        # Verify thread reconstruction
        thread_parent = next(m for m in structured_messages if m.get("is_thread_parent"))
        assert len(thread_parent["replies"]) == 3, "Code review thread should have 3 replies"

        # Step 3: Format view
        context = ViewContext(
            channel_name="engineering",
            date_range="2025-10-20"
        )
        formatter = MessageViewFormatter()
        view_output = formatter.format(structured_messages, context)

        # Verify output contains expected elements
        assert "engineering" in view_output
        assert "2025-10-20" in view_output
        assert "Alice Chen" in view_output
        assert "Bob Martinez" in view_output
        assert "PROJ-123" in view_output
        assert "PROJ-456" in view_output
        assert "THREAD REPLIES" in view_output
        assert "CONVERSATION SUMMARY" in view_output

        return view_output  # Return for inspection

    def test_view_output_structure(self, realistic_parquet_cache):
        """Test that view output has expected structure"""
        reader = ParquetMessageReader(base_path=realistic_parquet_cache)
        flat_messages = reader.read_channel("engineering", "2025-10-20")

        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)

        context = ViewContext(channel_name="engineering", date_range="2025-10-20")
        formatter = MessageViewFormatter()
        view_output = formatter.format(structured_messages, context)

        # Check structural elements
        assert view_output.startswith("="), "Should start with header separator"
        assert "📱 SLACK CHANNEL" in view_output
        assert "💬 MESSAGE #" in view_output
        assert "👤" in view_output  # User indicator
        assert "📊 CONVERSATION SUMMARY" in view_output
        assert "Total Messages: 4" in view_output  # 4 top-level
        assert "Total Thread Replies: 3" in view_output
        assert "Active Threads: 1" in view_output

    def test_rich_content_in_view(self, realistic_parquet_cache):
        """Test that reactions, files, JIRA tickets appear in view"""
        reader = ParquetMessageReader(base_path=realistic_parquet_cache)
        flat_messages = reader.read_channel("engineering", "2025-10-20")

        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view_output = formatter.format(structured_messages, context)

        # Check reactions
        assert "😊 Reactions:" in view_output
        assert "coffee" in view_output
        assert "rocket" in view_output

        # Check files
        assert "📎 Files:" in view_output
        assert "api-design-v2.pdf" in view_output

        # Check JIRA tickets
        assert "🎫 JIRA:" in view_output or "PROJ-123" in view_output
        assert "DESIGN-789" in view_output

    def test_thread_visualization(self, realistic_parquet_cache):
        """Test that threads are properly visualized with nesting"""
        reader = ParquetMessageReader(base_path=realistic_parquet_cache)
        flat_messages = reader.read_channel("engineering", "2025-10-20")

        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view_output = formatter.format(structured_messages, context)

        # Check thread formatting
        assert "🧵 THREAD REPLIES:" in view_output
        assert "↳ REPLY #1:" in view_output
        assert "↳ REPLY #2:" in view_output
        assert "↳ REPLY #3:" in view_output

        # Verify replies appear after parent
        parent_text = "Can someone review my PR for PROJ-123"
        reply_text = "Looking at it now! Will have feedback in 10 min"

        parent_pos = view_output.index(parent_text)
        reply_pos = view_output.index(reply_text)
        assert reply_pos > parent_pos, "Reply should appear after parent"

    def test_chronological_ordering(self, realistic_parquet_cache):
        """Test that messages appear in chronological order"""
        reader = ParquetMessageReader(base_path=realistic_parquet_cache)
        flat_messages = reader.read_channel("engineering", "2025-10-20")

        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)

        context = ViewContext(channel_name="engineering")
        formatter = MessageViewFormatter()
        view_output = formatter.format(structured_messages, context)

        # Find positions of messages (by unique text snippets)
        morning_msg = "Good morning team!"
        review_msg = "Can someone review my PR"
        design_msg = "Updated the API design doc"
        deploy_msg = "Deployment to staging successful"

        positions = {
            "morning": view_output.index(morning_msg),
            "review": view_output.index(review_msg),
            "design": view_output.index(design_msg),
            "deploy": view_output.index(deploy_msg),
        }

        # Verify chronological order (as per timestamps)
        assert positions["morning"] < positions["review"]
        assert positions["review"] < positions["design"]
        assert positions["design"] < positions["deploy"]

    def test_empty_channel_view(self, tmp_path):
        """Test view for channel with no messages"""
        # Create empty cache
        cache_path = tmp_path / "cache"

        reader = ParquetMessageReader(base_path=str(cache_path))
        flat_messages = reader.read_channel("empty-channel", "2025-10-20")

        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)

        context = ViewContext(channel_name="empty-channel", date_range="2025-10-20")
        formatter = MessageViewFormatter()
        view_output = formatter.format(structured_messages, context)

        assert "No messages found" in view_output
        assert "empty-channel" in view_output


# Utility function to generate and save sample output for manual inspection
def generate_sample_output(tmp_path_factory):
    """Helper to generate sample output file for inspection"""
    tmp_path = tmp_path_factory.mktemp("sample_output")

    # Create the cache (reusing fixture logic)
    cache_path = tmp_path / "cache"
    # ... (would need to recreate the cache setup)

    # For now, this is just a placeholder
    # In actual use, you'd run this to generate output to a file
    pass


if __name__ == "__main__":
    # Allow running this file directly to generate sample output
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        # This would generate sample output for inspection
        print("Run via pytest to generate integration test output")
