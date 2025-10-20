# Parquet Schema Documentation

**Date:** 2025-10-19
**Version:** 1.0.0 (Phase 1)

---

## Overview

This document describes the Parquet schema for caching Slack and JIRA data in columnar format. The schema is designed for:
- Efficient filtering by user, channel, time
- Cross-channel analysis
- DuckDB/Polars queries
- LLM-optimized data preparation

---

## Partitioning Strategy

### Partition Format
```
cache/raw/{entity_type}/dt={YYYY-MM-DD}/channel={channel_name}/data.parquet
```

### Example Paths
```
cache/raw/messages/dt=2023-10-18/channel=engineering/data.parquet
cache/raw/messages/dt=2023-10-18/channel=random/data.parquet
cache/raw/messages/dt=2023-10-19/channel=engineering/data.parquet
```

### Partition Keys
- **`dt`**: Date in YYYY-MM-DD format (extracted from Slack timestamp)
- **`channel`**: Human-readable channel name (e.g., `engineering`)

### Rationale
- **Date partitioning**: Enables time-based filtering and incremental updates
- **Channel partitioning**: Isolates data by source for efficient single-channel queries
- **Both**: Supports cross-channel analysis while maintaining performance

---

## Entity Schemas

### 1. SlackMessage (`messages.parquet`)

**Purpose:** Store individual Slack messages with metadata

**Schema:**

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `message_id` | string | No | Slack message timestamp (unique ID) |
| `user_id` | string | Yes | Slack user ID (e.g., "U012ABC3DEF") |
| `text` | string | No | Message content |
| `timestamp` | string | No | ISO 8601 datetime (e.g., "2023-10-18T17:38:41Z") |
| `thread_ts` | string | Yes | Thread parent timestamp (null for standalone) |
| `is_thread_parent` | boolean | No | True if this message starts a thread |
| `is_thread_reply` | boolean | No | True if this is a reply in a thread |
| `reply_count` | int | No | Number of replies (0 for non-parents) |
| `user_name` | string | Yes | Slack username (e.g., "john.doe") |
| `user_real_name` | string | Yes | Full name (e.g., "John Doe") |
| `user_email` | string | Yes | Email address |
| `user_is_bot` | boolean | Yes | True if posted by a bot |
| `reactions` | list<struct> | No | Reactions on this message (see below) |
| `files` | list<struct> | No | File attachments (see below) |
| `jira_tickets` | list<string> | No | Extracted JIRA ticket IDs (e.g., ["PROJ-123"]) |
| `has_reactions` | boolean | No | True if message has any reactions |
| `has_files` | boolean | No | True if message has file attachments |
| `has_thread` | boolean | No | True if this message has a thread |

**Nested Types:**

**`reactions` (list<struct>):**
```
- emoji: string          # Emoji name (e.g., "100")
- count: int             # Number of reactions
- users: list<string>    # User IDs who reacted
```

**`files` (list<struct>):**
```
- id: string             # File ID
- name: string           # Filename
- mimetype: string       # MIME type
- url: string            # Private URL
- size: int              # File size in bytes
```

**Example Row:**
```json
{
  "message_id": "1697654321.123456",
  "user_id": "U012ABC3DEF",
  "text": "PROJ-123: Deployed fix! 🚀",
  "timestamp": "2023-10-18T17:38:41Z",
  "thread_ts": null,
  "is_thread_parent": false,
  "is_thread_reply": false,
  "reply_count": 0,
  "user_name": "john.doe",
  "user_real_name": "John Doe",
  "user_email": "john.doe@example.com",
  "user_is_bot": false,
  "reactions": [{"emoji": "100", "count": 3, "users": ["U012ABC3DEF", "U987ZYX6WVU"]}],
  "files": [],
  "jira_tickets": ["PROJ-123"],
  "has_reactions": true,
  "has_files": false,
  "has_thread": false
}
```

---

### 2. JiraTicket (`jira_tickets.parquet`)

**Purpose:** Store JIRA ticket metadata enriched from API

**Schema:**

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `ticket_id` | string | No | JIRA ticket ID (e.g., "PROJ-123") |
| `summary` | string | No | Ticket title/summary |
| `status` | string | No | Current status (e.g., "In Progress") |
| `priority` | string | No | Priority level (e.g., "High") |
| `issue_type` | string | No | Type (e.g., "Bug", "Story") |
| `assignee` | string | No | Assignee email |
| `due_date` | string | Yes | Due date (YYYY-MM-DD) |
| `story_points` | int | Yes | Story points estimate |
| `created` | string | No | Created datetime (ISO 8601) |
| `updated` | string | No | Last updated datetime (ISO 8601) |
| `blocks` | list<string> | No | Ticket IDs this blocks |
| `blocked_by` | list<string> | No | Ticket IDs blocking this |
| `depends_on` | list<string> | No | Ticket IDs this depends on |
| `related` | list<string> | No | Related ticket IDs |
| `components` | list<string> | No | Components (e.g., ["Backend", "Auth"]) |
| `labels` | list<string> | No | Labels/tags |
| `fix_versions` | list<string> | No | Target versions |
| `resolution` | string | Yes | Resolution status |
| `progress_total` | int | No | Total work (flattened from progress) |
| `progress_done` | int | No | Work completed |
| `progress_percentage` | float | No | Completion percentage |
| `project` | string | No | Project key (e.g., "COTO") |
| `team` | string | Yes | Team name |
| `epic_link` | string | Yes | Epic ticket ID |
| `comments` | map<string,int> | No | Comment counts by user |
| `total_comments` | int | No | Total comment count |
| `sprints` | list<struct> | No | Sprint information (see below) |

**Nested Types:**

**`sprints` (list<struct>):**
```
- name: string           # Sprint name (e.g., "Sprint 42")
- state: string          # Sprint state (e.g., "active")
```

**Example Row:**
```json
{
  "ticket_id": "PROJ-456",
  "summary": "Implement user authentication",
  "status": "In Progress",
  "priority": "High",
  "issue_type": "Story",
  "assignee": "john.doe@example.com",
  "due_date": "2023-10-25",
  "story_points": 8,
  "created": "2023-10-10T09:00:00Z",
  "updated": "2023-10-18T16:00:00Z",
  "blocks": ["PROJ-789"],
  "blocked_by": [],
  "depends_on": ["PROJ-200", "PROJ-300"],
  "related": [],
  "components": ["Backend", "Auth"],
  "labels": ["security"],
  "fix_versions": ["v2.0.0"],
  "resolution": null,
  "progress_total": 100,
  "progress_done": 65,
  "progress_percentage": 65.0,
  "project": "COTO",
  "team": "Backend Team",
  "epic_link": "PROJ-1000",
  "comments": {"john.doe": 3, "jane.smith": 2},
  "total_comments": 5,
  "sprints": [{"name": "Sprint 42", "state": "active"}]
}
```

---

### 3. SlackUser (`users.parquet`)

**Purpose:** Store Slack user profiles

**Schema:**

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `user_id` | string | No | Slack user ID |
| `user_name` | string | Yes | Username |
| `real_name` | string | Yes | Full name |
| `display_name` | string | Yes | Display name |
| `email` | string | Yes | Email address |
| `is_bot` | boolean | No | True if bot account |

**Example Row:**
```json
{
  "user_id": "U012ABC3DEF",
  "user_name": "john.doe",
  "real_name": "John Doe",
  "display_name": "Johnny",
  "email": "john.doe@example.com",
  "is_bot": false
}
```

---

### 4. SlackThread (`threads.parquet`)

**Purpose:** Store thread-level aggregates and metadata

**Schema:**

| Field | Type | Nullable | Description |
|-------|------|----------|-------------|
| `thread_id` | string | No | Parent message timestamp (thread ID) |
| `reply_count` | int | No | Number of replies |
| `participant_count` | int | No | Number of unique participants |
| `participants` | list<string> | No | List of participant names |
| `jira_tickets` | list<string> | No | JIRA tickets mentioned in thread |
| `duration_minutes` | float | No | Thread duration in minutes |

**Example Row:**
```json
{
  "thread_id": "1697654321.123456",
  "reply_count": 5,
  "participant_count": 3,
  "participants": ["John Doe", "Jane Smith", "Bob Johnson"],
  "jira_tickets": ["PROJ-123"],
  "duration_minutes": 45.5
}
```

---

## Query Examples

### DuckDB Queries

**1. Find all messages from a specific user:**
```sql
SELECT channel_name, timestamp, text
FROM read_parquet('cache/raw/messages/**/*.parquet')
WHERE user_name = 'john.doe'
ORDER BY timestamp DESC
LIMIT 50;
```

**2. Cross-channel JIRA ticket analysis:**
```sql
SELECT
    jira_ticket,
    COUNT(DISTINCT channel_name) as channel_count,
    COUNT(*) as mention_count,
    LIST(DISTINCT channel_name) as channels
FROM (
    SELECT
        channel_name,
        UNNEST(jira_tickets) as jira_ticket
    FROM read_parquet('cache/raw/messages/**/*.parquet')
)
WHERE jira_ticket IS NOT NULL
GROUP BY jira_ticket
HAVING channel_count > 1
ORDER BY mention_count DESC;
```

**3. Messages with reactions in last 7 days:**
```sql
SELECT user_real_name, text, reactions
FROM read_parquet('cache/raw/messages/**/*.parquet')
WHERE has_reactions = true
  AND timestamp >= CURRENT_DATE - INTERVAL '7 days'
ORDER BY timestamp DESC;
```

**4. Active threads (> 5 replies):**
```sql
SELECT
    m.channel_name,
    m.user_real_name as starter,
    m.text as topic,
    m.reply_count,
    m.timestamp
FROM read_parquet('cache/raw/messages/**/*.parquet') m
WHERE m.is_thread_parent = true
  AND m.reply_count > 5
ORDER BY m.reply_count DESC;
```

**5. Bot vs Human messages:**
```sql
SELECT
    user_is_bot,
    COUNT(*) as message_count,
    COUNT(DISTINCT user_id) as unique_users
FROM read_parquet('cache/raw/messages/**/*.parquet')
GROUP BY user_is_bot;
```

---

## Data Types & Parquet Mapping

### Primitive Types
| Python Type | Parquet Type | Notes |
|-------------|--------------|-------|
| `str` | `string` | UTF-8 encoded |
| `int` | `int64` | Signed integer |
| `float` | `double` | 64-bit float |
| `bool` | `boolean` | True/False |
| `None` | `null` | Missing value |

### Complex Types
| Python Type | Parquet Type | Example |
|-------------|--------------|---------|
| `list[str]` | `list<string>` | `["PROJ-123", "PROJ-456"]` |
| `list[dict]` | `list<struct>` | `[{"emoji": "100", "count": 2}]` |
| `dict[str, int]` | `map<string, int64>` | `{"john": 3, "jane": 2}` |

### DateTime Handling
- **Storage:** ISO 8601 string format with `Z` suffix (UTC)
- **Example:** `"2023-10-18T17:38:41Z"`
- **Rationale:** Human-readable, timezone-aware, DuckDB compatible

---

## Schema Evolution Strategy

### Version 1.0.0 (Current - Phase 1)
- Basic schema with flattened structures
- Essential fields for cross-channel analysis
- Partition by date and channel

### Future Versions
- **v1.1.0**: Add `channel_id` to messages for disambiguation
- **v1.2.0**: Add `mentioned_users` array extracted from text
- **v2.0.0**: Add graph layer foreign keys (if implementing Layer 2)

### Handling Schema Changes
1. **Backward compatible**: Add new nullable fields
2. **Breaking changes**: Increment major version, create migration script
3. **Test compatibility**: Run integration tests across versions

---

## Best Practices

### When Writing Parquet
1. **Batch writes**: Collect 100-1000 rows before writing (avoid tiny files)
2. **Compression**: Use `snappy` for good balance (speed vs size)
3. **Row groups**: Keep row group size 100-500 MB for optimal queries
4. **Partitioning**: Always partition by date and channel

### When Querying
1. **Use partitions**: Filter on `dt` and `channel` when possible
2. **Select only needed columns**: `SELECT user_name, text` vs `SELECT *`
3. **Push-down filters**: DuckDB optimizes partition filters automatically
4. **Avoid scanning all partitions**: Use date range filters

### Data Quality
1. **Validate before write**: Check for null required fields
2. **Deduplicate**: Check `message_id` uniqueness before appending
3. **Handle missing data**: Use explicit `null` not empty strings
4. **Type consistency**: Ensure booleans are `true`/`false` not `1`/`0`

---

## File Organization

```
cache/
├── raw/                              # Source of truth
│   ├── messages/                     # Slack messages
│   │   ├── dt=2023-10-18/
│   │   │   ├── channel=engineering/
│   │   │   │   └── data.parquet     # ~100-500 MB per file
│   │   │   ├── channel=random/
│   │   │   │   └── data.parquet
│   │   ├── dt=2023-10-19/
│   │   │   └── channel=engineering/
│   │   │       └── data.parquet
│   ├── threads/
│   │   └── data.parquet              # Not partitioned (smaller dataset)
│   ├── jira_tickets/
│   │   └── data.parquet              # Not partitioned
│   └── users/
│       └── data.parquet               # Not partitioned
```

---

## Testing Schema

### Unit Tests
See `tests/test_parquet_models.py`:
- ✅ Schema conversion (nested → flat)
- ✅ Type validation (strings, lists, booleans)
- ✅ Partition key generation
- ✅ Required field presence

### Integration Tests
Future Phase 2:
- Write Parquet file and read back
- Verify DuckDB can query partitions
- Test schema evolution (add new fields)

---

## References

- **DuckDB Parquet docs**: https://duckdb.org/docs/data/parquet
- **Apache Parquet format**: https://parquet.apache.org/docs/
- **Pydantic to Parquet**: https://arrow.apache.org/docs/python/parquet.html
- **Partition strategies**: https://duckdb.org/docs/data/partitioning/hive_partitioning.html

---

## Next Steps (Phase 2)

1. Implement `ParquetCache` class to write Parquet files
2. Add DuckDB query layer
3. Test incremental updates (append vs overwrite)
4. Benchmark query performance on real data
5. Implement cache invalidation strategy

**Phase 1 Complete:** Schema design and conversion methods implemented with full test coverage (27/27 tests passing).
