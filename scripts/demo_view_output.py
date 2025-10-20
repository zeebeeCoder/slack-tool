"""Demo script to generate and display sample message view output

Run this to see what the formatted view looks like with realistic data.
"""

import tempfile
from pathlib import Path
import pyarrow as pa
import pyarrow.parquet as pq

from slack_intel.parquet_message_reader import ParquetMessageReader
from slack_intel.thread_reconstructor import ThreadReconstructor
from slack_intel.message_view_formatter import MessageViewFormatter, ViewContext


def create_sample_data(cache_dir: Path):
    """Create realistic sample Parquet data"""
    base_path = cache_dir / "raw" / "messages"

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

    messages = [
        # Morning standup
        {
            "message_id": "1729411200.000001",
            "user_id": "U001",
            "text": "Good morning team! 🌅 Starting work on PROJ-456 (API refactoring)",
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

        # Code review thread parent
        {
            "message_id": "1729414800.000002",
            "user_id": "U002",
            "text": "Can someone review my PR for PROJ-123? It fixes the auth bug we discussed yesterday. Main changes:\n• Updated token validation logic\n• Added rate limiting\n• Improved error messages",
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

        # Thread reply 1
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

        # Thread reply 2
        {
            "message_id": "1729415700.000004",
            "user_id": "U001",
            "text": "LGTM! 🚀 Left a few minor comments on the error handling. The rate limiting implementation looks solid. One suggestion: add tests for the edge cases.",
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

        # Thread reply 3
        {
            "message_id": "1729416000.000005",
            "user_id": "U002",
            "text": "Thanks Alice! Addressed your comments and added the edge case tests. Pushing now. Will merge after CI passes ✅",
            "timestamp": "2025-10-20T09:20:00Z",
            "thread_ts": "1729414800.000002",
            "is_thread_parent": False,
            "is_thread_reply": True,
            "reply_count": 0,
            "user_name": "bob",
            "user_real_name": "Bob Martinez",
            "user_email": "bob@example.com",
            "user_is_bot": False,
            "reactions": [{"emoji": "rocket", "count": 1, "users": ["U001"]}],
            "files": [],
            "jira_tickets": [],
            "has_reactions": True,
            "has_files": False,
            "has_thread": False,
        },

        # Design discussion with file
        {
            "message_id": "1729425600.000006",
            "user_id": "U003",
            "text": "Updated the API design doc based on our conversation. Key changes:\n• Switched to REST from GraphQL for simplicity\n• Added versioning strategy (v1, v2)\n• Updated authentication flow\n\nThoughts on the new schema? cc @alice @bob",
            "timestamp": "2025-10-20T12:00:00Z",
            "thread_ts": None,
            "is_thread_parent": False,
            "is_thread_reply": False,
            "reply_count": 0,
            "user_name": "charlie",
            "user_real_name": "Charlie Davis",
            "user_email": "charlie@example.com",
            "user_is_bot": False,
            "reactions": [{"emoji": "thinking_face", "count": 2, "users": ["U001", "U002"]}],
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
            "has_reactions": True,
            "has_files": True,
            "has_thread": False,
        },

        # Deployment notification from bot
        {
            "message_id": "1729432800.000007",
            "user_id": "UBOT001",
            "text": "✅ Deployment to staging successful!\n\nBuild: #342\nCommit: abc123def456\nDuration: 3m 24s\nJIRA Tickets: PROJ-123, PROJ-456\n\nAll tests passed! Ready for production deployment.",
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
                {"emoji": "tada", "count": 2, "users": ["U001", "U002"]},
                {"emoji": "fire", "count": 1, "users": ["U003"]}
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

    table = pa.Table.from_pylist(messages, schema=schema)
    pq.write_table(table, partition_dir / "data.parquet", compression='snappy')


def main():
    """Generate and display sample view output"""
    print("=" * 80)
    print("SLACK MESSAGE VIEW - DEMO OUTPUT")
    print("=" * 80)
    print()

    with tempfile.TemporaryDirectory() as tmpdir:
        cache_dir = Path(tmpdir) / "cache"

        # Create sample data
        print("📝 Creating sample Parquet data...")
        create_sample_data(cache_dir)

        # Step 1: Read from Parquet
        print("📖 Reading messages from Parquet...")
        reader = ParquetMessageReader(base_path=str(cache_dir))
        flat_messages = reader.read_channel("engineering", "2025-10-20")
        print(f"   Found {len(flat_messages)} messages")

        # Step 2: Reconstruct threads
        print("🧵 Reconstructing thread structure...")
        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)
        print(f"   Organized into {len(structured_messages)} top-level items")

        # Step 3: Format view
        print("🎨 Formatting view output...")
        context = ViewContext(
            channel_name="engineering",
            date_range="2025-10-20"
        )
        formatter = MessageViewFormatter()
        view_output = formatter.format(structured_messages, context)

        print("\n" + "=" * 80)
        print("GENERATED VIEW OUTPUT:")
        print("=" * 80)
        print()
        print(view_output)
        print()
        print("=" * 80)
        print("✅ Demo complete!")
        print("=" * 80)


if __name__ == "__main__":
    main()
