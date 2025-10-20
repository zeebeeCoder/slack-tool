# Message View System Documentation

## Overview

The Message View System reads cached Slack messages from Parquet files, reconstructs thread relationships, and formats them into human-readable and LLM-optimized text views.

## Architecture

### Component Pipeline

```
┌─────────────┐
│   Parquet   │  Messages stored by date partition
│    Cache    │  dt=YYYY-MM-DD/channel=name/data.parquet
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│ ParquetMessageReader│  Reads messages from partitions
│                     │  - Single date: read_channel()
│                     │  - Date range: read_channel_range()
│                     │  - Multi-channel: read_all_channels()
└──────┬──────────────┘
       │ Flat message list (chronological)
       ▼
┌─────────────────────┐
│ ThreadReconstructor │  Rebuilds thread structure
│                     │  - Groups by thread_ts
│                     │  - Nests replies under parents
│                     │  - Marks orphaned/clipped threads
└──────┬──────────────┘
       │ Structured messages (nested threads)
       ▼
┌─────────────────────┐
│MessageViewFormatter │  Formats into readable text
│                     │  - Resolves user mentions
│                     │  - Formats reactions, files, JIRA
│                     │  - Adds visual markers (💬, 🧵, ↳)
└──────┬──────────────┘
       │
       ▼
  ┌────────┐
  │  Text  │  LLM-optimized view output
  │  View  │
  └────────┘
```

### Data Flow Example

```python
# 1. Read from Parquet
reader = ParquetMessageReader(base_path="cache")
flat_messages = reader.read_channel("engineering", "2025-10-20")
# Returns: [msg1, msg2, reply1, reply2, msg3, ...]

# 2. Reconstruct threads
reconstructor = ThreadReconstructor()
structured = reconstructor.reconstruct(flat_messages)
# Returns: [msg1, msg2{replies: [reply1, reply2]}, msg3, ...]

# 3. Format view
context = ViewContext(channel_name="engineering", date_range="2025-10-20")
formatter = MessageViewFormatter()
output = formatter.format(structured, context)
# Returns: Formatted text with headers, threads, summary
```

## Key Features

### 1. Date-Based Partitioning

Messages are **partitioned by their timestamp date**, not the cache date:

```
cache/raw/messages/
├── dt=2025-10-15/
│   ├── channel=engineering/data.parquet
│   └── channel=general/data.parquet
├── dt=2025-10-16/
│   ├── channel=engineering/data.parquet
│   └── channel=general/data.parquet
```

**Why?** Enables efficient querying by message date:
- `--date 2025-10-15` reads only `dt=2025-10-15` partition
- `--start-date 2025-10-15 --end-date 2025-10-17` reads 3 partitions
- No need to scan all messages

### 2. Thread Reconstruction

Converts flat message lists into nested structures:

**Input (Flat):**
```
[
  {id: "1", is_thread_parent: True, thread_ts: "1", reply_count: 2},
  {id: "2", is_thread_reply: True, thread_ts: "1"},
  {id: "3", is_thread_reply: True, thread_ts: "1"},
  {id: "4", standalone message}
]
```

**Output (Nested):**
```
[
  {
    id: "1",
    is_thread_parent: True,
    replies: [
      {id: "2", ...},
      {id: "3", ...}
    ]
  },
  {id: "4", ...}
]
```

**Handles Edge Cases:**
- **Orphaned replies**: Parent message outside time window
- **Clipped threads**: Some replies outside time window
- **Partial data**: Missing parent or incomplete reply list

### 3. User Mention Resolution

Automatically resolves Slack user IDs to readable names:

**Before:**
```
Hey <@U02JRGK9TCG>, can you review this? cc <@U04S24AAQ7Q>
```

**After:**
```
Hey <@U02JRGK9TCG>, can you review this? cc @Rey
```

**How it works:**
1. Scans all messages to build user_id → name mapping
2. Replaces `<@USER_ID>` with `@Real Name` in message text
3. Keeps unknown user IDs as-is (users who never posted)

### 4. Channel Name Auto-Detection

Handles both named channels and raw channel IDs:

```bash
# Named channel (from config)
slack-intel view --channel engineering --date 2025-10-20

# Raw channel ID (from CLI --channel flag during cache)
slack-intel view --channel C05713KTQF9 --date 2025-10-20
# Auto-tries: C05713KTQF9 → channel_C05713KTQF9
```

### 5. Rich Content Display

Preserves and displays Slack metadata:

```markdown
💬 MESSAGE #1
👤 Alice Chen at 2025-10-20 10:00:
   Check out the new design doc!
   😊 Reactions: rocket(3), eyes(2)
   📎 Files: design-v2.pdf (application/pdf)
   🎫 JIRA: PROJ-123, PROJ-456
```

## CLI Usage

### Caching Messages

```bash
# Cache last 7 days from configured channels
slack-intel cache --days 7

# Cache specific channel by ID
slack-intel cache --channel C05713KTQF9 --days 20

# Cache with JIRA enrichment
slack-intel cache --enrich-jira --days 7
```

**Key Point:** Messages are automatically partitioned by their timestamp date.

### Viewing Messages

```bash
# View single day
slack-intel view --channel engineering --date 2025-10-20

# View date range
slack-intel view -c general --start-date 2025-10-15 --end-date 2025-10-17

# Save to file
slack-intel view -c engineering --date 2025-10-20 -o report.txt

# Check available data
slack-intel stats
```

## Configuration

### Channel Configuration (.slack-intel.yaml)

```yaml
channels:
  - name: engineering
    id: C05713KTQF9
  - name: general
    id: C0123456789
  - name: design
    id: C9876543210
```

When caching via config, channels are stored as `channel=engineering`.
When caching via CLI ID, channels are stored as `channel=channel_C05713KTQF9`.

The view command auto-detects both naming patterns.

## Output Format

### View Structure

```
================================================================================
📱 SLACK CHANNEL: engineering
⏰ TIME WINDOW: 2025-10-20
================================================================================

💬 MESSAGE #1
👤 User Name at 2025-10-20 10:00:
   Message text here with @mention resolution
   😊 Reactions: emoji(count), emoji(count)
   📎 Files: file.pdf (type)
   🎫 JIRA: PROJ-123

------------------------------------------------------------

💬 MESSAGE #2 (🔗 Thread clipped)
👤 User Name at 2025-10-20 10:30:
   Parent message text

  🧵 THREAD REPLIES (showing 2 of 5+ replies):
    ↳ REPLY #1: User at 2025-10-20 10:35:
       Reply text here
    ↳ REPLY #2: User at 2025-10-20 10:40:
       Another reply

  💡 Thread may have additional replies outside this time range

------------------------------------------------------------

📊 CONVERSATION SUMMARY:
   • Total Messages: 2
   • Total Thread Replies: 2
   • Active Threads: 1
```

### Visual Markers

- `💬` - Message
- `🧵` - Thread with replies
- `↳` - Thread reply
- `😊` - Reactions
- `📎` - File attachments
- `🎫` - JIRA tickets
- `🔗` - Clipped thread indicator
- `💡` - Hint about missing data

## Performance Characteristics

### Partitioning Benefits

- **Query by date**: Only reads relevant date partitions
- **Incremental caching**: New messages added to today's partition
- **Storage efficiency**: Snappy compression on Parquet files
- **Schema evolution**: Parquet schema allows adding fields

### Typical Sizes

- 100 messages ≈ 25-30 KB (compressed Parquet)
- Date range queries: Linear with number of days
- Channel overhead: Minimal (separate partition per channel/date)

## Error Handling

### Common Scenarios

1. **No cache found**: Prompts to run `slack-intel cache`
2. **Date has no messages**: Shows "No messages found", suggests checking `slack-intel stats`
3. **Channel not found**: Auto-tries both naming conventions, then fails gracefully
4. **Orphaned threads**: Marks as clipped, suggests widening date range
5. **Invalid timestamps**: Falls back to cache date for partitioning

## Implementation Details

### Thread Detection Logic

```python
# Message is thread parent if:
is_thread_parent = (
    msg.get("thread_ts") == msg.get("message_id") and
    msg.get("reply_count", 0) > 0
)

# Message is thread reply if:
is_thread_reply = (
    msg.get("thread_ts") is not None and
    msg.get("thread_ts") != msg.get("message_id")
)
```

### Partition Path Format

```
{base_path}/messages/dt={YYYY-MM-DD}/channel={channel_name}/data.parquet
```

Example:
```
cache/raw/messages/dt=2025-10-20/channel=engineering/data.parquet
```

### Mention Resolution Pattern

```python
# Regex pattern for Slack user mentions
pattern = r'<@(U[A-Z0-9]+)>'

# Replacement logic
if user_id in user_mapping:
    return f"@{user_mapping[user_id]}"  # @Alice Chen
else:
    return match.group(0)  # <@U123...> (keep original)
```

## Testing

The system includes comprehensive test coverage:

- **Unit Tests**: 123 tests covering readers, reconstructors, formatters
- **Integration Tests**: 6 tests for end-to-end pipeline
- **Test Types**:
  - Partition reading and filtering
  - Thread reconstruction with edge cases
  - Mention resolution
  - Rich content formatting
  - Date range queries
  - Multi-channel reads

Run tests:
```bash
# Unit tests only
pytest tests/ -v -m "not integration"

# All tests including integration
pytest tests/ -v
```
