# Data Integrity Requirements for Idempotent Caching

## Executive Summary

**Current Issue**: Cache operations use **overwrite semantics** that cause data loss on overlapping runs.

**Desired Behavior**: Cache operations should use **upsert semantics** with **exactly-once delivery** guarantees.

**Test Results**: 10/12 tests FAIL - demonstrating critical data integrity gaps.

---

## Data Quality Terminology (The Tech Jargon)

### 1. **Idempotency** ⭐ PRIMARY GOAL
Running the same operation multiple times produces the same result.

```bash
# Idempotent behavior (desired):
cache --days 2  # Result: 1000 messages
cache --days 2  # Result: 1000 messages (same!)

# Non-idempotent behavior (current):
cache --days 2  # Result: 1000 messages
cache --days 1  # Result: 500 messages (overwrites, loses 500!)
```

**Why it matters**: Allows safe retries, recovery, and incremental caching without data loss.

### 2. **Exactly-Once Semantics** ⭐ GOLD STANDARD
Each Slack message appears **exactly once** in the cache - never duplicated, never lost.

This is the holy grail in distributed systems:
- **At-most-once**: May lose data (current system fails this)
- **At-least-once**: May duplicate data (acceptable, can dedupe)
- **Exactly-once**: Perfect integrity (target state)

**Industry Examples**:
- Kafka transactions
- Database ACID properties
- Financial transaction processing

### 3. **Upsert Semantics** (Update + Insert)
Merge operation that intelligently combines new and existing data:

```python
# Upsert logic:
if message_id exists in cache:
    update(message)  # Refresh with latest data
else:
    insert(message)  # Add new message
```

**Current Behavior**: Overwrites entire partition (loses data)
**Desired Behavior**: Merges at message-level granularity

### 4. **Deduplication**
Using `message_id` (Slack's `ts` field) as the **primary key** to eliminate duplicates.

```sql
-- Conceptual SQL equivalent:
INSERT INTO cache (message_id, text, ...)
VALUES ('1697635200.000001', 'Hello', ...)
ON CONFLICT (message_id) DO UPDATE SET ...
```

### 5. **Data Integrity**
The cache accurately reflects Slack's source of truth with:
- **Accuracy**: Messages match Slack API data
- **Completeness**: No missing messages
- **Consistency**: No duplicates or conflicts
- **Timeliness**: Recent data reflects current state

### 6. **Incremental Processing**
Only process new/changed data, not full dataset each time.

**Current**: Re-fetch and overwrite entire partition
**Desired**: Fetch new messages, merge with existing

**Benefit**: Reduces API calls, processing time, and data transfer.

### 7. **Immutability** (Related Concept)
Once written, data doesn't change (mostly - except thread reply_count updates).

**Application**: Slack messages are mostly immutable, so cache should preserve history.

---

## Test Results Analysis

### ✅ PASSING (1 test)
- **test_idempotent_full_recache_same_data**: Writing identical data twice works

### ❌ FAILING (10 tests)

#### **Critical Data Loss Issues**

1. **test_overlapping_cache_preserves_existing_messages**
   ```
   Expected: 120 messages (100 original + 20 new)
   Got: 0 messages
   Impact: TOTAL DATA LOSS on overlapping cache
   ```

2. **test_partial_day_cache_preserves_earlier_messages**
   ```
   Expected: 75 messages (full day)
   Got: 50 messages
   Impact: Lost 25 messages from morning cache run
   ```

3. **test_empty_cache_run_preserves_existing_data**
   ```
   Expected: 2 messages (preserve existing)
   Got: 0 messages
   Impact: Empty API response wipes cache
   ```

#### **Deduplication Failures**

4. **test_no_duplicates_on_overlapping_cache**
   ```
   Expected: 4 unique messages
   Got: 3 messages
   Impact: Lost message #1 on second cache run
   ```

5. **test_deduplicate_by_message_id**
   ```
   Expected: 2 unique messages (dedupe within batch)
   Got: 3 messages
   Impact: Duplicates within same cache operation
   ```

6. **test_deduplicate_across_multiple_cache_runs**
   ```
   Expected: 4 unique messages
   Got: 2 messages
   Impact: Overwrites instead of merging
   ```

#### **Upsert Semantic Failures**

7. **test_upsert_inserts_new_messages**
   ```
   Expected: 5 messages (3 old + 2 new)
   Got: 2 messages
   Impact: Incremental caching impossible
   ```

8. **test_upsert_updates_existing_messages**
   ```
   Expected: 1 message with reply_count=3
   Got: 1 message with reply_count=3
   Status: UNEXPECTED PASS (overwrote correctly by chance)
   ```

9. **test_upsert_preserves_unaffected_messages**
   ```
   Expected: 10 messages (update only msg 5)
   Got: 1 message
   Impact: Surgical updates destroy other data
   ```

#### **Performance Issues**

10. **test_large_overlap_no_memory_explosion**
    ```
    Expected: 10,000 messages
    Got: 9,999 messages
    Impact: Off-by-one error on large datasets
    ```

---

## Real-World Impact Scenarios

### Scenario 1: Daily Incremental Cache
```bash
# Day 1: Cache full day
slack-intel cache --days 1  # ✅ 1000 messages cached

# Day 2: Cache new day
slack-intel cache --days 1  # ✅ 500 new messages
# Expected: 1500 total
# Current: 500 (lost day 1)
```

### Scenario 2: Recovery After Network Error
```bash
# Morning: Cache 12 hours
slack-intel cache --days 0.5  # ✅ 600 messages

# Afternoon: Network error, retry
slack-intel cache --days 0.5  # ⚠️ API returns 0 messages
# Expected: 600 messages (preserve existing)
# Current: 0 messages (wiped!)
```

### Scenario 3: Overlapping Windows
```bash
# Run 1: Cache 7 days
slack-intel cache --days 7  # ✅ 5000 messages

# Run 2: Cache last 3 days (overlaps)
slack-intel cache --days 3  # ✅ 2000 messages (1500 overlap, 500 new)
# Expected: 5500 messages (5000 - 1500 overlap + 500 new)
# Current: 2000 messages (lost 3500!)
```

### Scenario 4: Thread Updates
```bash
# Morning: Thread parent cached (reply_count=0)
slack-intel cache --channel C123 --days 1

# Afternoon: Replies added, re-cache
slack-intel cache --channel C123 --days 1
# Expected: Thread parent updated with reply_count=5
# Current: Works (but only because overwrite updates it)
# Problem: Other messages in partition lost if not re-fetched
```

---

## Required Implementation

### Core Algorithm: Merge-Based Caching

```python
def save_messages(self, messages, channel, date) -> str:
    """Save messages with upsert semantics (merge with existing)"""

    partition_file = self._get_partition_file(channel, date)

    # 1. Load existing data (if file exists)
    existing_messages = {}
    if partition_file.exists():
        existing_table = pq.read_table(str(partition_file))
        existing_data = existing_table.to_pydict()

        # Index by message_id for O(1) lookup
        for i in range(existing_table.num_rows):
            msg_id = existing_data['message_id'][i]
            existing_messages[msg_id] = {
                col: existing_data[col][i]
                for col in existing_data.keys()
            }

    # 2. Upsert new messages (deduplicate + merge)
    new_messages_dict = {msg.ts: msg for msg in messages}

    # Merge: existing + new (new overwrites on conflict)
    merged = existing_messages.copy()

    for msg_id, msg in new_messages_dict.items():
        merged[msg_id] = msg.to_parquet_dict()

    # 3. Convert back to table and write
    merged_list = list(merged.values())

    # Sort by message_id for consistent ordering
    merged_list.sort(key=lambda x: x['message_id'])

    table = pa.Table.from_pylist(merged_list, schema=self.message_schema)

    # Write (overwrites file, but with merged data)
    pq.write_table(table, str(partition_file), compression='snappy')

    return str(partition_file)
```

### Key Implementation Points

1. **Read existing data before writing**
   - Use `pq.read_table()` to load existing partition
   - Handle file-not-exists case gracefully

2. **Merge at message level**
   - Index by `message_id` (primary key)
   - Use dict merge: `existing.update(new)`

3. **Deduplication**
   - Within batch: Use dict (last occurrence wins)
   - Across runs: Merge with existing

4. **Empty batch handling**
   - If `messages == []` and file exists: preserve existing
   - If `messages == []` and file doesn't exist: create empty file

5. **Performance optimization**
   - Use PyArrow's native operations where possible
   - Consider columnar merge for large datasets
   - Benchmark memory usage on 100k+ message partitions

### Edge Cases to Handle

1. **File corruption**: Catch `pq.read_table()` exceptions
2. **Concurrent writes**: Use file locking or atomic rename
3. **Schema evolution**: Handle schema version mismatches
4. **Large merges**: Stream processing for > 1M messages

---

## Acceptance Criteria

All 12 tests in `tests/test_idempotent_cache.py` must pass:

- ✅ Idempotent operations (same input → same output)
- ✅ No data loss on overlapping cache runs
- ✅ No duplicates (exactly-once semantics)
- ✅ Upsert semantics (insert new, update existing)
- ✅ Preserve unaffected messages
- ✅ Handle empty batches gracefully
- ✅ Performance on large datasets (10k+ messages)

---

## Implementation Priority

### Phase 1: Core Merge Logic (HIGH)
- Implement read-merge-write in `ParquetCache.save_messages()`
- Pass basic upsert and deduplication tests

### Phase 2: Edge Cases (MEDIUM)
- Handle empty batches
- File corruption recovery
- Schema validation

### Phase 3: Performance (LOW)
- Optimize large merges
- Benchmark memory usage
- Consider columnar merge strategies

### Phase 4: Concurrency (FUTURE)
- File locking for concurrent writes
- Atomic operations
- Transaction semantics

---

## Related Patterns

### Database Analogy
```sql
-- Current behavior (TRUNCATE + INSERT)
TRUNCATE TABLE messages_2023_10_18;
INSERT INTO messages_2023_10_18 VALUES (...);

-- Desired behavior (MERGE/UPSERT)
MERGE INTO messages_2023_10_18
USING new_messages
ON messages_2023_10_18.message_id = new_messages.message_id
WHEN MATCHED THEN UPDATE SET ...
WHEN NOT MATCHED THEN INSERT ...;
```

### Distributed Systems Analogy
- **Kafka**: Exactly-once producer semantics
- **S3**: Idempotent PUT operations
- **DynamoDB**: Conditional writes with primary key

---

## References

- **Exactly-Once Semantics**: [Confluent Kafka Documentation](https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/)
- **Upsert Patterns**: [PostgreSQL UPSERT](https://www.postgresql.org/docs/current/sql-insert.html#SQL-ON-CONFLICT)
- **Idempotency**: [AWS Well-Architected Framework](https://docs.aws.amazon.com/wellarchitected/latest/reliability-pillar/design-interactions-in-a-distributed-system-to-mitigate-or-withstand-failures.html)
- **PyArrow Merging**: [PyArrow Concat Tables](https://arrow.apache.org/docs/python/generated/pyarrow.concat_tables.html)

---

## Glossary

| Term | Definition | Example |
|------|------------|---------|
| **Idempotency** | Same operation → same result | `f(x) = f(f(x))` |
| **Upsert** | Update OR insert | SQL `ON CONFLICT DO UPDATE` |
| **Exactly-once** | No loss, no duplication | Each message appears once |
| **Primary Key** | Unique identifier | `message_id` (Slack `ts`) |
| **Deduplication** | Remove duplicates | Set union vs list append |
| **Partition** | Data subset by key | `dt=2023-10-18/channel=eng` |
| **Merge semantics** | Combine datasets | Set union with overwrite |
| **Data integrity** | Accuracy + completeness | Cache = source of truth |
| **Incremental** | Process only deltas | New messages only |
| **Immutable** | Doesn't change | Slack messages (mostly) |

---

**Status**: Test suite created ✅
**Next Step**: Implement merge-based `save_messages()` to pass all tests
**Owner**: Engineering
**Priority**: HIGH (data loss prevention)
