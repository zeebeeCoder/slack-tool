# Parquet Cache Usage Guide

**Date:** 2025-10-19
**Phase:** 2a Complete (Write-Only)

---

## Quick Start

```python
from slack_intel import ParquetCache, SlackChannel

# Initialize cache
cache = ParquetCache(base_path="cache/raw")

# Save messages
messages = [msg1, msg2, msg3]  # List[SlackMessage]
channel = SlackChannel(name="engineering", id="C9876543210")
file_path = cache.save_messages(messages, channel, "2023-10-18")

print(f"Saved to: {file_path}")
# Output: cache/raw/messages/dt=2023-10-18/channel=engineering/data.parquet
```

---

## ParquetCache API

### `ParquetCache(base_path="cache/raw")`
Initialize cache with base directory.

### `save_messages(messages, channel, date) -> str`
Save messages to partitioned Parquet file.

**Parameters:**
- `messages`: List[SlackMessage]
- `channel`: SlackChannel object
- `date`: str in YYYY-MM-DD format

**Returns:** Path to written Parquet file

**Behavior:** Overwrites existing partition if it exists.

### `get_partition_info() -> Dict`
Get statistics about cached partitions.

**Returns:**
```python
{
    "total_partitions": 5,
    "total_messages": 247,
    "total_size_bytes": 124567,
    "partitions": [...]
}
```

---

## Querying with DuckDB

### Basic Query
```python
import duckdb

conn = duckdb.connect()
result = conn.execute("""
    SELECT user_real_name, text, timestamp
    FROM 'cache/raw/messages/**/*.parquet'
    WHERE user_name = 'john.doe'
    ORDER BY timestamp DESC
    LIMIT 10
""").df()

print(result)
```

### Cross-Channel Analysis
```python
# Find JIRA tickets mentioned across multiple channels
conn.execute("""
    SELECT
        jira_ticket,
        COUNT(DISTINCT channel) as channel_count,
        COUNT(*) as mention_count
    FROM (
        SELECT
            UNNEST(jira_tickets) as jira_ticket,
            dt, channel
        FROM read_parquet('cache/raw/messages/**/*.parquet',
                         hive_partitioning=1)
    )
    WHERE jira_ticket IS NOT NULL
    GROUP BY jira_ticket
    HAVING channel_count > 1
    ORDER BY mention_count DESC
""").show()
```

### Filter by Date Range
```python
conn.execute("""
    SELECT user_real_name, COUNT(*) as msg_count
    FROM 'cache/raw/messages/**/*.parquet'
    WHERE timestamp >= '2023-10-18T00:00:00Z'
      AND timestamp <= '2023-10-25T23:59:59Z'
    GROUP BY user_real_name
    ORDER BY msg_count DESC
""").show()
```

---

## File Structure

```
cache/raw/
└── messages/
    ├── dt=2023-10-18/
    │   ├── channel=engineering/
    │   │   └── data.parquet
    │   └── channel=random/
    │       └── data.parquet
    └── dt=2023-10-19/
        └── channel=engineering/
            └── data.parquet
```

---

## Common Use Cases

### 1. Daily Message Archive
```python
from datetime import datetime

cache = ParquetCache()
date = datetime.now().strftime("%Y-%m-%d")

# Fetch and cache messages
manager = SlackChannelManager()
messages = await manager.get_messages(channel_id, start_time, end_time)

cache.save_messages(messages, channel, date)
```

### 2. Query User Activity
```python
import duckdb

# Find most active users
conn = duckdb.connect()
active_users = conn.execute("""
    SELECT
        user_real_name,
        COUNT(*) as messages,
        COUNT(DISTINCT dt) as active_days
    FROM read_parquet('cache/raw/messages/**/*.parquet', hive_partitioning=1)
    WHERE user_is_bot = false
    GROUP BY user_real_name
    ORDER BY messages DESC
    LIMIT 10
""").df()
```

### 3. Find Trending Topics
```python
# Count messages with reactions
trending = conn.execute("""
    SELECT
        text,
        LENGTH(reactions) as reaction_count,
        user_real_name,
        timestamp
    FROM 'cache/raw/messages/**/*.parquet'
    WHERE has_reactions = true
    ORDER BY reaction_count DESC
    LIMIT 20
""").df()
```

---

## Best Practices

1. **Partition by date**: Use YYYY-MM-DD format for date partitioning
2. **Batch saves**: Collect messages before saving to reduce write operations
3. **DuckDB filtering**: Use WHERE clauses to filter by date/channel for faster queries
4. **Schema validation**: Schema enforced by PyArrow automatically

---

## Limitations (Phase 2a)

- **Write-only**: No Python read API (use DuckDB for queries)
- **Overwrite mode**: Saving to existing partition overwrites data
- **Single format**: Only messages.parquet (no threads/users/jira yet)

---

## Next Phase (2b)

- Read API: `cache.load_messages(channel, date_range)`
- Incremental updates with deduplication
- Additional entity types (threads, users, JIRA)
- Query wrapper class (Python API for DuckDB)

---

## Troubleshooting

### Empty Results
```python
# Check partition info
info = cache.get_partition_info()
print(f"Total messages: {info['total_messages']}")
print(f"Partitions: {info['total_partitions']}")
```

### Schema Errors
If you get PyArrow schema errors, ensure messages have been converted via `to_parquet_dict()`.

### Date Format
Date must be YYYY-MM-DD. Invalid formats raise `ValueError`.

---

## Testing

See `tests/test_parquet_cache.py` and `tests/test_parquet_validation.py` for examples.

**Run tests:**
```bash
uv run pytest tests/test_parquet_cache.py -v
uv run pytest tests/test_parquet_validation.py -v
```
