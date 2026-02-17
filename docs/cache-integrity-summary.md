# Cache Data Integrity - Quick Summary

## The Problem in One Picture

```
Current Behavior (OVERWRITE):
─────────────────────────────

Day 1:
Cache --days 2
│
├─ dt=2025-11-01/channel_X/data.parquet  [100 msgs] ✅
└─ dt=2025-11-02/channel_X/data.parquet  [120 msgs] ✅

Day 2:
Cache --days 0.5 (overlaps Nov 2)
│
├─ dt=2025-11-01/channel_X/data.parquet  [100 msgs] ✅ (untouched)
└─ dt=2025-11-02/channel_X/data.parquet  [50 msgs]  ❌ OVERWROTE!

Result: Lost 70 messages from Nov 2! 💀
```

```
Desired Behavior (UPSERT/MERGE):
────────────────────────────────

Day 1:
Cache --days 2
│
├─ dt=2025-11-01/channel_X/data.parquet  [100 msgs] ✅
└─ dt=2025-11-02/channel_X/data.parquet  [120 msgs] ✅

Day 2:
Cache --days 0.5 (overlaps Nov 2)
│
├─ dt=2025-11-01/channel_X/data.parquet  [100 msgs] ✅ (untouched)
└─ dt=2025-11-02/channel_X/data.parquet  [140 msgs] ✅ MERGED!
                                          (120 existing + 20 new)

Result: All data preserved! ✅
```

## Tech Jargon Cheat Sheet

| Term | What It Means | Why You Care |
|------|--------------|--------------|
| **Idempotency** | Run it twice = same result | Safe to retry without data loss |
| **Exactly-Once** | Each message appears once | No dupes, no loss (gold standard) |
| **Upsert** | Update OR insert | Merge new data with existing |
| **Deduplication** | Remove duplicates by ID | Use `message_id` as primary key |
| **Data Integrity** | Cache = accurate + complete | Trust your data |
| **Merge Semantics** | Combine datasets intelligently | Not just overwrite |
| **Incremental Processing** | Only process new/changed data | Faster, cheaper |

## Test Results at a Glance

```
Total Tests: 12
├─ ✅ PASS: 1   (idempotent same data)
├─ ❌ FAIL: 10  (data loss, duplicates, upsert issues)
└─ ⏭️  SKIP: 1   (concurrent operations - future)

Critical Failures:
├─ Data Loss:     3 tests ❌❌❌
├─ Deduplication: 3 tests ❌❌❌
├─ Upsert Logic:  3 tests ❌❌❌
└─ Performance:   1 test  ❌
```

## The Fix (High Level)

**Current Code** (`parquet_cache.py:198-206`):
```python
def save_messages(self, messages, channel, date):
    table = pa.Table.from_pylist(data, schema=self.message_schema)

    # ❌ PROBLEM: Direct overwrite
    pq.write_table(table, file_path, compression='snappy')
```

**Desired Code**:
```python
def save_messages(self, messages, channel, date):
    # 1. Load existing data (if exists)
    existing = self._load_existing_partition(file_path)

    # 2. Merge by message_id (primary key)
    merged = self._merge_messages(existing, messages)

    # 3. Deduplicate
    deduplicated = self._dedupe_by_message_id(merged)

    # 4. Write merged result
    table = pa.Table.from_pylist(deduplicated, schema=self.message_schema)
    pq.write_table(table, file_path, compression='snappy')
```

## What You Get

### Before (Current)
```bash
$ slack-intel cache --days 2
✅ Cached 1000 messages

$ slack-intel cache --days 1  # Oops, overlap!
❌ Cached 500 messages (LOST 500!)
```

### After (Fixed)
```bash
$ slack-intel cache --days 2
✅ Cached 1000 messages

$ slack-intel cache --days 1  # Overlap? No problem!
✅ Cached 1200 messages (merged 1000 + 200 new)

$ slack-intel cache --days 2  # Run it again? Still safe!
✅ Cached 1200 messages (idempotent!)
```

## Industry Comparison

| System | Semantics | Our Target |
|--------|-----------|------------|
| **PostgreSQL UPSERT** | `ON CONFLICT DO UPDATE` | ✅ This! |
| **Kafka** | Exactly-once producer | ✅ This! |
| **S3 Sync** | Idempotent PUT | ✅ This! |
| **Git** | Merge commits | ✅ This! |
| **Current Cache** | Overwrite (TRUNCATE + INSERT) | ❌ Replace! |

## Next Steps

1. **Run tests** to see current failures:
   ```bash
   uv run pytest tests/test_idempotent_cache.py -v
   ```

2. **Implement merge logic** in `parquet_cache.py:save_messages()`

3. **Verify all tests pass**:
   ```bash
   uv run pytest tests/test_idempotent_cache.py -v
   # Expected: 11 PASS, 1 SKIP, 0 FAIL
   ```

4. **Update existing tests** in `test_parquet_cache.py`:
   - Change `test_overwrite_existing_partition` to `test_merge_existing_partition`
   - Update assertions to expect merge behavior

## Files Created

- ✅ `tests/test_idempotent_cache.py` - 12 TDD tests defining desired behavior
- ✅ `docs/data-integrity-requirements.md` - Full technical spec
- ✅ `docs/cache-integrity-summary.md` - This quick reference

## Questions?

**Q: Won't merging be slower than overwriting?**
A: Slightly, but:
- Only reads existing file once per partition
- Uses efficient PyArrow operations
- Prevents re-fetching from Slack API (bigger win)

**Q: What about really large partitions (100k+ messages)?**
A: Phase 3 optimization:
- Stream processing
- Columnar merge
- Benchmark and tune

**Q: Does this match how databases work?**
A: Yes! This is standard UPSERT/MERGE pattern:
- SQL: `INSERT ... ON CONFLICT DO UPDATE`
- MongoDB: `updateOne` with `upsert: true`
- DynamoDB: `PutItem` (overwrites by primary key)

**Q: Why not append-only?**
A: Slack messages can update (reply_count, reactions), so we need UPDATE capability.

---

**Status**: Ready to implement 🚀
**Risk**: HIGH (current system loses data)
**Effort**: Medium (1-2 days)
**Tests**: Written and failing (TDD complete)
