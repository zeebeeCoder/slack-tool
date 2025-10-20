# Solution Trees for: User Mention Resolution in Message View System

## Context
The Message View System needs to resolve user mentions (`<@USER_ID>`) to readable names (`@username`), but currently fails for users who are mentioned but haven't posted messages within the viewed date range. The system builds a user mapping from message authors only, missing users who are mentioned in message text.

**Current Architecture:**
- Messages cached in Parquet: `cache/raw/messages/dt=YYYY-MM-DD/channel=NAME/data.parquet`
- Each message has: `user_id`, `user_name`, `user_real_name`, `text` (containing mentions)
- `MessageViewFormatter._build_user_mapping()` builds `user_id → display_name` from message authors
- `MessageViewFormatter._resolve_mentions()` replaces `<@USER_ID>` patterns with `@name`

**Problem:** Users mentioned in `text` field but not in `user_id` field (message author) cannot be resolved.

---

## Tree 1: Extract Mentions from Message Text (Simplest Solution)

### Approach Summary
Scan all message text in the current date range for user mentions, extract unique user IDs, then fetch their information from Slack API at view generation time. This is a minimal-code solution that works within the existing architecture without modifying the cache structure or caching pipeline.

### Tree Structure
```
Root: Resolve user mentions for non-posting users
├── Branch 1: Extend user mapping building process
│   ├── Leaf 1.1: Add mention extraction to _build_user_mapping() {est: 2h, deps: none}
│   │   - Scan all message text for <@USER_ID> patterns
│   │   - Extract unique user IDs not in current mapping
│   │   - Return list of missing user IDs
│   ├── Leaf 1.2: Create Slack API user lookup utility {est: 2h, deps: 1.1}
│   │   - Add method to fetch user info from Slack API (users.info)
│   │   - Handle API errors gracefully (rate limits, deleted users)
│   │   - Return user name or fallback to user_id
│   └── Leaf 1.3: Integrate API lookup into formatter {est: 1h, deps: 1.2}
│       - Call Slack API for missing user IDs
│       - Add results to user_mapping dictionary
│       - Cache results in formatter instance for session
├── Branch 2: Add Slack client dependency to MessageViewFormatter
│   ├── Leaf 2.1: Add optional slack_client parameter to __init__ {est: 1h, deps: none}
│   │   - Accept AsyncWebClient or None
│   │   - Store in instance variable
│   │   - Default to None for backward compatibility
│   └── Leaf 2.2: Add lazy client initialization {est: 2h, deps: 2.1}
│       - Check for SLACK_BOT_TOKEN in environment
│       - Create AsyncWebClient if token available
│       - Handle async context properly
└── Integration: Testing & Error Handling
    ├── Leaf I.1: Add unit tests for mention extraction {est: 2h, deps: 1.1}
    │   - Test regex pattern matching
    │   - Test deduplication of user IDs
    │   - Test handling of malformed mentions
    ├── Leaf I.2: Add integration test with mock Slack API {est: 3h, deps: 1.3, 2.2}
    │   - Mock users.info API responses
    │   - Test successful resolution
    │   - Test API error handling
    └── Leaf I.3: Add rate limiting protection {est: 2h, deps: 1.2}
        - Batch API calls if many missing users
        - Add exponential backoff for rate limits
        - Log warnings for API failures
```

### Task Specifications

**T1.1: Add mention extraction to _build_user_mapping()**
- **Task**: Extract user IDs from `<@USER_ID>` patterns in message text
- **Deliverable**: Modified `_build_user_mapping()` that returns set of missing user IDs
- **Dependencies**: None
- **Estimated Duration**: 2 hours
- **Required Context**: `message_view_formatter.py`, understanding of regex patterns
- **Implementation Details**:
  - Add regex scan: `r'<@(U[A-Z0-9]+)>'` to extract all mentions
  - Deduplicate user IDs across all messages and replies
  - Return `Set[str]` of user IDs not in current mapping

**T1.2: Create Slack API user lookup utility**
- **Task**: Implement async method to fetch user info from Slack API
- **Deliverable**: New method `_fetch_user_info(user_ids: Set[str]) -> Dict[str, str]`
- **Dependencies**: T1.1
- **Estimated Duration**: 2 hours
- **Required Context**: `slack_sdk` documentation, existing `slack_channels.py` for API patterns
- **Implementation Details**:
  - Use `client.users_info(user=user_id)` for each ID
  - Extract `real_name` or `name` from response
  - Handle SlackApiError for deleted/deactivated users
  - Return dict mapping user_id → display_name

**T1.3: Integrate API lookup into formatter**
- **Task**: Connect mention extraction to API lookup in format() method
- **Deliverable**: Modified `format()` method that resolves all mentions
- **Dependencies**: T1.2
- **Estimated Duration**: 1 hour
- **Required Context**: Existing `format()` flow in `message_view_formatter.py`
- **Implementation Details**:
  - After initial mapping, call mention extraction
  - If missing users found and slack_client available, fetch from API
  - Update self.user_mapping with API results
  - Continue to existing _resolve_mentions() step

**T2.1: Add optional slack_client parameter to __init__**
- **Task**: Add dependency injection for Slack client
- **Deliverable**: Modified `__init__` signature with optional client parameter
- **Dependencies**: None
- **Estimated Duration**: 1 hour
- **Required Context**: `message_view_formatter.py` class structure
- **Implementation Details**:
  - Add parameter: `slack_client: Optional[AsyncWebClient] = None`
  - Store as `self.slack_client = slack_client`
  - Update docstring with new parameter

**T2.2: Add lazy client initialization**
- **Task**: Auto-create Slack client if not provided but token available
- **Deliverable**: Method to initialize client from environment
- **Dependencies**: T2.1
- **Estimated Duration**: 2 hours
- **Required Context**: Environment variable handling, async context
- **Implementation Details**:
  - Add `_ensure_slack_client()` method
  - Check `os.getenv("SLACK_BOT_TOKEN")`
  - Create AsyncWebClient if token present
  - Handle async/sync context appropriately

**TI.1: Add unit tests for mention extraction**
- **Task**: Write tests for regex extraction logic
- **Deliverable**: New test file or extended `test_message_view_formatter.py`
- **Dependencies**: T1.1
- **Estimated Duration**: 2 hours
- **Required Context**: Existing test patterns in `tests/`
- **Implementation Details**:
  - Test extracting multiple mentions from single message
  - Test deduplication across messages
  - Test ignoring non-user mentions (channels, etc.)
  - Test malformed mention patterns

**TI.2: Add integration test with mock Slack API**
- **Task**: End-to-end test with mocked Slack responses
- **Deliverable**: Integration test showing full mention resolution flow
- **Dependencies**: T1.3, T2.2
- **Estimated Duration**: 3 hours
- **Required Context**: Python mocking patterns, async testing
- **Implementation Details**:
  - Mock AsyncWebClient.users_info()
  - Test successful resolution of mentioned non-posters
  - Test fallback when API unavailable
  - Test error handling for deleted users

**TI.3: Add rate limiting protection**
- **Task**: Prevent API rate limit issues with many mentions
- **Deliverable**: Rate limiting logic in API fetch method
- **Dependencies**: T1.2
- **Estimated Duration**: 2 hours
- **Required Context**: Slack API rate limits (Tier 3: 50+ calls/minute)
- **Implementation Details**:
  - Batch user lookups if >10 missing users
  - Add retry logic with exponential backoff
  - Log warnings when rate limited
  - Consider using `users.list` if >50 missing users

### Integration Points
- `MessageViewFormatter.format()` calls `_build_user_mapping()` → enhanced to extract mentions
- `_build_user_mapping()` returns missing IDs → triggers API lookup
- Slack client injected via constructor or environment → enables API calls

---

## Tree 2: Cache Users During Message Collection (Most Comprehensive)

### Approach Summary
Modify the caching pipeline to extract and cache user information alongside messages. When messages are fetched from Slack API, scan for all mentioned user IDs and fetch their information proactively. Store user data in a separate Parquet table. This eliminates runtime API calls and provides complete user data coverage.

### Tree Structure
```
Root: Resolve user mentions for non-posting users
├── Branch 1: Extract mentions during message caching
│   ├── Leaf 1.1: Add mention extraction to SlackChannel class {est: 2h, deps: none}
│   │   - Add method to extract user IDs from message text
│   │   - Scan messages for <@USER_ID> patterns
│   │   - Return unique user IDs
│   ├── Leaf 1.2: Fetch mentioned users during caching {est: 2h, deps: 1.1}
│   │   - After fetching messages, extract all mentioned user IDs
│   │   - Fetch user info via users.info API
│   │   - Build SlackUser objects for mentioned users
│   └── Leaf 1.3: Add mentioned users to message metadata {est: 1h, deps: 1.2}
│       - Store mentioned user IDs in message record
│       - Or maintain separate mentioned_users collection
├── Branch 2: Create user cache Parquet table
│   ├── Leaf 2.1: Define user Parquet schema {est: 1h, deps: none}
│   │   - Schema: user_id, user_name, real_name, email, is_bot
│   │   - Partition by dt=YYYY-MM-DD
│   │   - No channel partition needed (users are workspace-wide)
│   ├── Leaf 2.2: Implement user cache save method {est: 2h, deps: 2.1}
│   │   - Add save_users() to ParquetCache
│   │   - Accept List[SlackUser] and date
│   │   - Write to cache/raw/users/dt=YYYY-MM-DD/data.parquet
│   └── Leaf 2.3: Integrate user caching into pipeline {est: 2h, deps: 1.3, 2.2}
│       - In CLI cache command, save users after messages
│       - Deduplicate users across channels
│       - Log user cache statistics
├── Branch 3: Create user reader for view generation
│   ├── Leaf 3.1: Add ParquetUserReader class {est: 3h, deps: 2.2}
│   │   - Mirror ParquetMessageReader API
│   │   - Methods: read_users(date), read_users_range(start, end)
│   │   - Return List[Dict] of user data
│   ├── Leaf 3.2: Build user mapping from cache {est: 2h, deps: 3.1}
│   │   - Modify MessageViewFormatter to accept pre-built mapping
│   │   - Or add method to load mapping from cache
│   │   - Merge cached users with message-author users
│   └── Leaf 3.3: Update CLI view command to use user cache {est: 1h, deps: 3.2}
│       - Load users from cache for date range
│       - Pass user mapping to formatter
│       - Fallback to old behavior if cache missing
└── Integration: Schema updates and migrations
    ├── Leaf I.1: Update PARQUET_SCHEMA.md documentation {est: 1h, deps: 2.1}
    │   - Document new user cache structure
    │   - Document partition layout
    │   - Add example queries
    ├── Leaf I.2: Add integration tests for user caching {est: 3h, deps: 2.3}
    │   - Test user extraction from messages
    │   - Test deduplication across channels
    │   - Test user cache read/write
    └── Leaf I.3: Add cache validation utility {est: 2h, deps: 3.1}
        - Script to check user cache coverage
        - Report missing users for date range
        - Suggest re-caching if gaps found
```

### Task Specifications

**T1.1: Add mention extraction to SlackChannel class**
- **Task**: Create utility method to extract user mentions from messages
- **Deliverable**: New method in `slack_channels.py` or standalone utility
- **Dependencies**: None
- **Estimated Duration**: 2 hours
- **Required Context**: `slack_channels.py`, SlackMessage structure
- **Implementation Details**:
  - Method signature: `extract_mentioned_users(messages: List[SlackMessage]) -> Set[str]`
  - Scan each message.text for `<@USER_ID>` pattern
  - Scan reply text if present
  - Return unique user IDs

**T1.2: Fetch mentioned users during caching**
- **Task**: Integrate user fetching into message caching pipeline
- **Deliverable**: Modified caching logic in `slack_channels.py` or CLI
- **Dependencies**: T1.1
- **Estimated Duration**: 2 hours
- **Required Context**: Existing cache pipeline in `cli.py` and `slack_channels.py`
- **Implementation Details**:
  - After fetching messages, call extract_mentioned_users()
  - Filter out user IDs already in message authors
  - Call `client.users_info()` for remaining IDs
  - Build SlackUser objects from responses

**T1.3: Add mentioned users to message metadata**
- **Task**: Store relationship between messages and mentioned users
- **Deliverable**: Updated message structure or separate collection
- **Dependencies**: T1.2
- **Estimated Duration**: 1 hour
- **Required Context**: Current message storage patterns
- **Implementation Details**:
  - Option A: Add `mentioned_user_ids` field to messages (requires schema change)
  - Option B: Store users separately, reference by date
  - Recommend Option B for simplicity

**T2.1: Define user Parquet schema**
- **Task**: Create PyArrow schema for user cache
- **Deliverable**: Schema definition in `parquet_cache.py`
- **Dependencies**: None
- **Estimated Duration**: 1 hour
- **Required Context**: Existing `_create_message_schema()` pattern
- **Implementation Details**:
  - Mirror SlackUser.to_parquet_dict() fields
  - Fields: user_id, user_name, real_name, display_name, email, is_bot
  - Add cached_at timestamp
  - No nested types needed

**T2.2: Implement user cache save method**
- **Task**: Add save_users() method to ParquetCache
- **Deliverable**: New method in `parquet_cache.py`
- **Dependencies**: T2.1
- **Estimated Duration**: 2 hours
- **Required Context**: Existing `save_messages()` implementation
- **Implementation Details**:
  - Method: `save_users(users: List[SlackUser], date: str) -> str`
  - Partition path: `cache/raw/users/dt=YYYY-MM-DD/data.parquet`
  - Deduplicate users by user_id before saving
  - Return file path

**T2.3: Integrate user caching into pipeline**
- **Task**: Add user caching to CLI cache command
- **Deliverable**: Modified `cli.py` cache command
- **Dependencies**: T1.3, T2.2
- **Estimated Duration**: 2 hours
- **Required Context**: Current CLI cache flow
- **Implementation Details**:
  - After caching messages for all channels on a date
  - Collect all mentioned users across channels
  - Deduplicate by user_id
  - Call cache.save_users()
  - Log count of cached users

**T3.1: Add ParquetUserReader class**
- **Task**: Create reader class for user cache
- **Deliverable**: New file `parquet_user_reader.py` or addition to existing reader
- **Dependencies**: T2.2
- **Estimated Duration**: 3 hours
- **Required Context**: `parquet_message_reader.py` patterns
- **Implementation Details**:
  - Class: `ParquetUserReader(base_path="cache")`
  - Method: `read_users(date: str) -> List[Dict]`
  - Method: `read_users_range(start: str, end: str) -> List[Dict]`
  - Sort and deduplicate by user_id

**T3.2: Build user mapping from cache**
- **Task**: Integrate cached users into MessageViewFormatter
- **Deliverable**: Modified `_build_user_mapping()` or new method
- **Dependencies**: T3.1
- **Estimated Duration**: 2 hours
- **Required Context**: Current `_build_user_mapping()` implementation
- **Implementation Details**:
  - Add optional parameter: `cached_users: Optional[List[Dict]] = None`
  - If cached_users provided, add to mapping first
  - Then overlay with message-author users (they're more recent)
  - Merge logic: cached users as base, authors override

**T3.3: Update CLI view command to use user cache**
- **Task**: Load and use cached users in view generation
- **Deliverable**: Modified CLI view command
- **Dependencies**: T3.2
- **Estimated Duration**: 1 hour
- **Required Context**: Current CLI view command flow
- **Implementation Details**:
  - Create ParquetUserReader instance
  - Load users for date range
  - Pass to MessageViewFormatter as cached_users
  - Handle missing cache gracefully (log warning)

**TI.1: Update PARQUET_SCHEMA.md documentation**
- **Task**: Document new user cache structure
- **Deliverable**: Updated documentation file
- **Dependencies**: T2.1
- **Estimated Duration**: 1 hour
- **Required Context**: Existing `PARQUET_SCHEMA.md` if exists, or create new
- **Implementation Details**:
  - Document user schema fields
  - Document partition strategy: dt=YYYY-MM-DD
  - Add example read queries
  - Note relationship to message cache

**TI.2: Add integration tests for user caching**
- **Task**: End-to-end tests for user cache pipeline
- **Deliverable**: New test file `test_user_cache_integration.py`
- **Dependencies**: T2.3
- **Estimated Duration**: 3 hours
- **Required Context**: Existing integration test patterns
- **Implementation Details**:
  - Test extracting users from messages with mentions
  - Test saving to cache
  - Test reading from cache
  - Test deduplication across channels
  - Mock Slack API for user fetching

**TI.3: Add cache validation utility**
- **Task**: Tool to check user cache health
- **Deliverable**: Script or CLI command to validate cache
- **Dependencies**: T3.1
- **Estimated Duration**: 2 hours
- **Required Context**: Cache structure and expected coverage
- **Implementation Details**:
  - Read all messages for date range
  - Extract all mentioned user IDs
  - Read user cache for same range
  - Report missing users
  - Suggest re-caching specific dates

### Integration Points
- CLI cache command → extracts mentions → fetches users → saves to cache
- ParquetUserReader → reads user cache → provides to MessageViewFormatter
- MessageViewFormatter → loads cached users → merges with message authors → resolves mentions
- Cache validation → checks coverage → identifies gaps

---

## Tree 3: Hybrid In-Memory Cache (Balanced Solution)

### Approach Summary
Build an in-memory user lookup cache that persists across view generations within a session. On first mention resolution failure, fetch the user from Slack API and cache it in memory (and optionally to disk as JSON). Subsequent views reuse the cached data. This provides fast lookups without modifying the Parquet schema or main caching pipeline.

### Tree Structure
```
Root: Resolve user mentions for non-posting users
├── Branch 1: Create in-memory user cache
│   ├── Leaf 1.1: Add UserCache class with dict-based storage {est: 2h, deps: none}
│   │   - Class with methods: get(user_id), put(user_id, user_data), load(), save()
│   │   - Store in memory: Dict[str, Dict[str, str]]
│   │   - Thread-safe access if needed
│   ├── Leaf 1.2: Add JSON persistence for user cache {est: 2h, deps: 1.1}
│   │   - Save to cache/users.json on updates
│   │   - Load from cache/users.json on init
│   │   - Format: {"USER_ID": {"name": "...", "real_name": "..."}}
│   └── Leaf 1.3: Add cache TTL and refresh logic {est: 2h, deps: 1.2}
│       - Store cached_at timestamp per user
│       - Refresh users older than 7 days
│       - Configurable TTL via parameter
├── Branch 2: Integrate cache with mention resolution
│   ├── Leaf 2.1: Modify _resolve_mentions to check cache {est: 2h, deps: 1.1}
│   │   - Before returning unresolved mention, check UserCache
│   │   - If found, use cached name
│   │   - If not found, trigger API fetch
│   ├── Leaf 2.2: Add async user fetch with caching {est: 2h, deps: 2.1}
│   │   - Fetch from Slack API: client.users_info()
│   │   - Store result in UserCache
│   │   - Return resolved name or fallback to ID
│   └── Leaf 2.3: Add batch prefetch on mapping build {est: 2h, deps: 2.2}
│       - During _build_user_mapping(), extract all mentions
│       - Check which are missing from both mapping and cache
│       - Batch fetch from API (up to 50 at once)
│       - Populate cache before resolution phase
├── Branch 3: Add cache management utilities
│   ├── Leaf 3.1: Add CLI command to view cache stats {est: 1h, deps: 1.2}
│   │   - Show total cached users
│   │   - Show cache file size
│   │   - Show oldest/newest entries
│   ├── Leaf 3.2: Add CLI command to clear cache {est: 1h, deps: 1.2}
│   │   - Delete cache/users.json
│   │   - Clear in-memory cache
│   │   - Confirm before clearing
│   └── Leaf 3.3: Add CLI command to preload cache {est: 2h, deps: 2.3}
│       - Accept date range parameter
│       - Scan all messages for mentions
│       - Batch fetch all users
│       - Populate cache proactively
└── Integration: Testing and edge cases
    ├── Leaf I.1: Add unit tests for UserCache class {est: 2h, deps: 1.3}
    │   - Test get/put operations
    │   - Test JSON load/save
    │   - Test TTL expiration
    ├── Leaf I.2: Add integration tests with formatter {est: 3h, deps: 2.3}
    │   - Test cache-hit scenario (no API call)
    │   - Test cache-miss scenario (triggers API)
    │   - Test batch prefetch
    │   - Mock Slack API
    └── Leaf I.3: Add error handling for cache corruption {est: 2h, deps: 1.2}
        - Handle malformed JSON gracefully
        - Rebuild cache if corrupted
        - Log warnings on parse errors
```

### Task Specifications

**T1.1: Add UserCache class with dict-based storage**
- **Task**: Create simple in-memory user cache
- **Deliverable**: New class in `user_cache.py`
- **Dependencies**: None
- **Estimated Duration**: 2 hours
- **Required Context**: Python dict patterns, basic caching concepts
- **Implementation Details**:
  - Class: `UserCache(cache_path: Optional[str] = "cache/users.json")`
  - Storage: `self._cache: Dict[str, Dict[str, Any]]`
  - Methods: `get(user_id) -> Optional[Dict]`, `put(user_id, data) -> None`
  - Methods: `load() -> None`, `save() -> None`
  - Auto-load on init if cache file exists

**T1.2: Add JSON persistence for user cache**
- **Task**: Implement save/load for user cache JSON file
- **Deliverable**: Persistence methods in UserCache class
- **Dependencies**: T1.1
- **Estimated Duration**: 2 hours
- **Required Context**: JSON serialization, file I/O patterns
- **Implementation Details**:
  - Format: `{"U123": {"name": "alice", "real_name": "Alice Smith", "cached_at": "2025-10-20T10:00:00"}}`
  - Use json.dump() for saving (pretty-printed)
  - Use json.load() for loading
  - Create parent directory if needed
  - Handle FileNotFoundError on load

**T1.3: Add cache TTL and refresh logic**
- **Task**: Implement time-based cache invalidation
- **Deliverable**: TTL checking in get() method
- **Dependencies**: T1.2
- **Estimated Duration**: 2 hours
- **Required Context**: Datetime handling, cache invalidation patterns
- **Implementation Details**:
  - Add `cached_at` timestamp to each cache entry
  - Default TTL: 7 days (configurable)
  - In `get()`: check if entry expired, return None if so
  - Add method: `refresh_stale(slack_client) -> int` (returns count refreshed)

**T2.1: Modify _resolve_mentions to check cache**
- **Task**: Integrate UserCache into mention resolution
- **Deliverable**: Modified `_resolve_mentions()` method
- **Dependencies**: T1.1
- **Estimated Duration**: 2 hours
- **Required Context**: Current `_resolve_mentions()` implementation
- **Implementation Details**:
  - Add `self.user_cache = UserCache()` to formatter init
  - In replace_mention callback: first check self.user_mapping
  - If not found, check self.user_cache.get(user_id)
  - If found in cache, use it and update self.user_mapping
  - If not found anywhere, keep original mention

**T2.2: Add async user fetch with caching**
- **Task**: Fetch missing users from API and cache them
- **Deliverable**: New method `_fetch_and_cache_user(user_id: str) -> Optional[str]`
- **Dependencies**: T2.1
- **Estimated Duration**: 2 hours
- **Required Context**: Slack SDK async patterns
- **Implementation Details**:
  - Call `await slack_client.users_info(user=user_id)`
  - Extract name from response
  - Call `user_cache.put(user_id, user_data)`
  - Call `user_cache.save()` to persist
  - Return resolved name or None

**T2.3: Add batch prefetch on mapping build**
- **Task**: Proactively fetch all mentioned users before resolution
- **Deliverable**: New method `_prefetch_mentioned_users(messages: List[Dict]) -> None`
- **Dependencies**: T2.2
- **Estimated Duration**: 2 hours
- **Required Context**: Batch API patterns, async gathering
- **Implementation Details**:
  - Extract all mentions from message text (regex scan)
  - Filter to IDs not in mapping or cache
  - If missing IDs < 50, fetch individually
  - If >= 50, log warning and skip prefetch (rely on lazy loading)
  - Use asyncio.gather() to fetch in parallel
  - Update cache with all results

**T3.1: Add CLI command to view cache stats**
- **Task**: Create CLI command to inspect user cache
- **Deliverable**: New CLI command `slack-intel user-cache stats`
- **Dependencies**: T1.2
- **Estimated Duration**: 1 hour
- **Required Context**: Existing CLI patterns in `cli.py`
- **Implementation Details**:
  - Load UserCache
  - Print: total users, cache file size, oldest entry, newest entry
  - Format dates in human-readable form
  - Show sample entries (first 5)

**T3.2: Add CLI command to clear cache**
- **Task**: Create CLI command to delete user cache
- **Deliverable**: New CLI command `slack-intel user-cache clear`
- **Dependencies**: T1.2
- **Estimated Duration**: 1 hour
- **Required Context**: CLI confirmation patterns
- **Implementation Details**:
  - Prompt: "Delete user cache? This will require re-fetching users from Slack. [y/N]"
  - If yes: delete cache/users.json
  - Print confirmation: "User cache cleared."

**T3.3: Add CLI command to preload cache**
- **Task**: Create CLI command to populate cache from messages
- **Deliverable**: New CLI command `slack-intel user-cache preload <start-date> <end-date>`
- **Dependencies**: T2.3
- **Estimated Duration**: 2 hours
- **Required Context**: CLI argument parsing, existing cache reading
- **Implementation Details**:
  - Read all messages for date range
  - Extract all user mentions
  - Check which are not in cache
  - Print: "Found 45 new users to cache"
  - Batch fetch from API
  - Save to cache
  - Print: "Cached 45 users"

**TI.1: Add unit tests for UserCache class**
- **Task**: Test UserCache operations in isolation
- **Deliverable**: New test file `test_user_cache.py`
- **Dependencies**: T1.3
- **Estimated Duration**: 2 hours
- **Required Context**: pytest patterns, temp file handling
- **Implementation Details**:
  - Test get/put with in-memory only
  - Test load/save round-trip
  - Test TTL expiration (mock datetime)
  - Test missing file handling
  - Use tmp_path fixture for file tests

**TI.2: Add integration tests with formatter**
- **Task**: End-to-end tests of cache integration
- **Deliverable**: Extended `test_message_view_formatter.py`
- **Dependencies**: T2.3
- **Estimated Duration**: 3 hours
- **Required Context**: Existing formatter tests, mocking patterns
- **Implementation Details**:
  - Test 1: Mention resolved from cache (no API call)
  - Test 2: Mention triggers API fetch and caching
  - Test 3: Batch prefetch populates cache
  - Test 4: Expired cache entries trigger refresh
  - Mock AsyncWebClient and UserCache file operations

**TI.3: Add error handling for cache corruption**
- **Task**: Handle corrupted or invalid cache files
- **Deliverable**: Error handling in UserCache.load()
- **Dependencies**: T1.2
- **Estimated Duration**: 2 hours
- **Required Context**: Exception handling, logging
- **Implementation Details**:
  - Wrap json.load() in try/except
  - Catch JSONDecodeError
  - Log warning: "User cache corrupted, starting fresh"
  - Initialize empty cache
  - Optionally backup corrupted file before overwriting

### Integration Points
- MessageViewFormatter → initializes UserCache → loads persisted cache
- Mention resolution → checks cache → triggers API fetch if miss → saves to cache
- CLI commands → manage cache lifecycle (stats, clear, preload)
- Cache file → persists between CLI invocations → provides session continuity

---

## Tree 4: Expand User Mapping from All Messages (Quick Fix)

### Approach Summary
The simplest possible solution: when reading messages for view generation, read messages from a wider date range (e.g., ±7 days) to build the user mapping, but only display messages from the requested range. This catches users who posted recently but not on the exact requested date. No API calls, no schema changes, minimal code.

### Tree Structure
```
Root: Resolve user mentions for non-posting users
├── Branch 1: Expand user mapping date range
│   ├── Leaf 1.1: Add configurable mapping_window to MessageViewFormatter {est: 1h, deps: none}
│   │   - Add parameter: mapping_window_days (default: 7)
│   │   - Store in instance variable
│   │   - Document purpose: wider user mapping coverage
│   ├── Leaf 1.2: Modify format() to read extra messages for mapping {est: 2h, deps: 1.1}
│   │   - Calculate expanded date range: view_start - window to view_end + window
│   │   - Read messages from expanded range (don't display them)
│   │   - Build user mapping from expanded set
│   │   - Filter to requested range for display
│   └── Leaf 1.3: Update CLI to expose mapping_window parameter {est: 1h, deps: 1.2}
│       - Add --mapping-window flag to view command
│       - Default to 7 days
│       - Document in help text
├── Branch 2: Optimize memory usage
│   ├── Leaf 2.1: Add user-only read mode to ParquetMessageReader {est: 2h, deps: none}
│   │   - Add parameter: fields=["user_id", "user_name", "user_real_name"]
│   │   - PyArrow supports column projection
│   │   - Read only user columns from expanded range
│   └── Leaf 2.2: Integrate column projection in formatter {est: 1h, deps: 1.2, 2.1}
│       - For mapping-only reads, use column projection
│       - Reduces memory footprint
│       - Faster reads for large date ranges
└── Integration: Testing and documentation
    ├── Leaf I.1: Add unit test for expanded mapping window {est: 2h, deps: 1.2}
    │   - Create messages across date range
    │   - Request view for single day
    │   - Verify users from adjacent days are in mapping
    ├── Leaf I.2: Add performance test for large windows {est: 2h, deps: 2.2}
    │   - Test with 30-day mapping window
    │   - Measure memory usage with/without projection
    │   - Ensure acceptable performance
    └── Leaf I.3: Update user documentation {est: 1h, deps: 1.3}
        - Document --mapping-window flag
        - Explain trade-offs: coverage vs performance
        - Suggest values: 7 (default), 14 (better), 30 (max)
```

### Task Specifications

**T1.1: Add configurable mapping_window to MessageViewFormatter**
- **Task**: Add parameter for user mapping date expansion
- **Deliverable**: Modified `__init__` with new parameter
- **Dependencies**: None
- **Estimated Duration**: 1 hour
- **Required Context**: `message_view_formatter.py` class structure
- **Implementation Details**:
  - Add parameter: `mapping_window_days: int = 7`
  - Store as `self.mapping_window_days = mapping_window_days`
  - Update docstring to explain purpose
  - Note: 0 means no expansion (current behavior)

**T1.2: Modify format() to read extra messages for mapping**
- **Task**: Read additional messages to build comprehensive user mapping
- **Deliverable**: Modified `format()` method or new helper method
- **Dependencies**: T1.1
- **Estimated Duration**: 2 hours
- **Required Context**: How messages are currently read (ParquetMessageReader)
- **Implementation Details**:
  - Extract date range from messages or context
  - Calculate expanded range: [start - window, end + window]
  - Read messages from expanded range
  - Call `_build_user_mapping(expanded_messages)`
  - Continue with original messages for display
  - This requires passing ParquetMessageReader to formatter

**T1.3: Update CLI to expose mapping_window parameter**
- **Task**: Add CLI flag for mapping window configuration
- **Deliverable**: Modified view command in `cli.py`
- **Dependencies**: T1.2
- **Estimated Duration**: 1 hour
- **Required Context**: Existing CLI argument patterns
- **Implementation Details**:
  - Add flag: `--mapping-window <days>` (default: 7)
  - Pass to MessageViewFormatter constructor
  - Add to help text: "Expand user mapping lookup window (days before/after view range)"

**T2.1: Add user-only read mode to ParquetMessageReader**
- **Task**: Support column projection for memory efficiency
- **Deliverable**: Modified `read_channel()` and `read_channel_range()`
- **Dependencies**: None
- **Estimated Duration**: 2 hours
- **Required Context**: PyArrow column selection API
- **Implementation Details**:
  - Add parameter: `columns: Optional[List[str]] = None`
  - If columns specified: `table = pq.read_table(file, columns=columns)`
  - Document example: `reader.read_channel("eng", "2025-10-20", columns=["user_id", "user_name", "user_real_name"])`

**T2.2: Integrate column projection in formatter**
- **Task**: Use column projection for mapping-only reads
- **Deliverable**: Modified format() to use columns parameter
- **Dependencies**: T1.2, T2.1
- **Estimated Duration**: 1 hour
- **Required Context**: Integration point between formatter and reader
- **Implementation Details**:
  - For expanded range reads (mapping only), pass columns parameter
  - Only read: user_id, user_name, user_real_name
  - For display reads, read all columns
  - Reduces memory by ~70% for mapping reads

**TI.1: Add unit test for expanded mapping window**
- **Task**: Test user mapping from expanded date range
- **Deliverable**: New test in `test_message_view_formatter.py`
- **Dependencies**: T1.2
- **Estimated Duration**: 2 hours
- **Required Context**: Existing formatter test setup
- **Implementation Details**:
  - Create messages on days: 1, 3, 5 (users: Alice, Bob, Charlie)
  - Request view for day 3 only (with 2-day window)
  - Message on day 3 mentions Alice (from day 1)
  - Verify Alice's mention is resolved
  - Verify only day 3 messages are displayed

**TI.2: Add performance test for large windows**
- **Task**: Benchmark memory and time with various window sizes
- **Deliverable**: Performance test script or pytest-benchmark test
- **Dependencies**: T2.2
- **Estimated Duration**: 2 hours
- **Required Context**: Performance testing patterns
- **Implementation Details**:
  - Generate 1000 messages across 60 days
  - Test windows: 0, 7, 14, 30 days
  - Measure: memory usage, read time, format time
  - Assert: 30-day window completes in <2 seconds

**TI.3: Update user documentation**
- **Task**: Document mapping window feature
- **Deliverable**: Updated README or usage docs
- **Dependencies**: T1.3
- **Estimated Duration**: 1 hour
- **Required Context**: Project documentation location
- **Implementation Details**:
  - Add section: "User Mention Resolution"
  - Explain mapping window concept
  - Provide examples: `slack-intel view engineering 2025-10-20 --mapping-window 14`
  - Trade-offs: larger window = better coverage but slower

### Integration Points
- MessageViewFormatter → reads expanded date range → builds comprehensive mapping
- ParquetMessageReader → supports column projection → reduces memory overhead
- CLI view command → exposes mapping_window flag → user controls coverage/performance trade-off

---

## Tree Characteristics Summary

| Tree | Architecture Type | Primary Technologies | Number of Leaves | Total Estimated Hours |
|------|------------------|---------------------|------------------|----------------------|
| Tree 1 | Runtime API Fetch | Slack SDK, AsyncWebClient, Regex | 12 | 20 hours |
| Tree 2 | Comprehensive Cache | PyArrow, Parquet partitioning, CLI integration | 15 | 26 hours |
| Tree 3 | Hybrid In-Memory Cache | JSON persistence, UserCache class, CLI tools | 15 | 27 hours |
| Tree 4 | Expanded Read Window | PyArrow column projection, Date range expansion | 9 | 13 hours |

**Note:** This document contains only factual descriptions of possible solutions. Evaluation of feasibility, viability, cost-effectiveness, or other quality attributes should be performed by specialized evaluation agents.

## Additional Context for Evaluators

**Existing Capabilities:**
- Slack API client already exists in codebase (`slack_channels.py` uses `AsyncWebClient`)
- Parquet cache infrastructure in place (`parquet_cache.py`, `parquet_message_reader.py`)
- Message view formatter exists with mention resolution stub (`message_view_formatter.py`)
- CLI framework established (`cli.py` with cache and view commands)

**User Data Sources:**
1. **Message author metadata**: Already captured when caching messages (user_id, user_name, user_real_name)
2. **Slack API users.info**: Can fetch individual user by ID (rate limited: Tier 3)
3. **Slack API users.list**: Can fetch all workspace users (expensive, rarely needed)
4. **Message text mentions**: Regex extractable: `<@USER_ID>`

**Constraints Identified:**
- Slack API rate limits: ~50 calls/minute for Tier 3 endpoints
- Performance target: View generation should complete in <2 seconds for typical use
- Memory target: Should handle 1000+ messages without excessive RAM usage
- Simplicity target: Prefer solutions that don't require Parquet schema migrations if possible

**Coverage Analysis:**
- Tree 1: Covers 100% of mentioned users (runtime API), minimal code change
- Tree 2: Covers 100% of mentioned users (proactive cache), most robust but requires pipeline changes
- Tree 3: Covers 100% of mentioned users (lazy cache), balanced approach with persistence
- Tree 4: Covers ~80-95% of mentioned users (temporal proximity heuristic), simplest implementation
