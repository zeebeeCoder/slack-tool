---
name: slack-intel
description: Slack Intelligence - Cache, query, and analyze Slack workspace messages using Parquet storage and SQL analytics. Use this when users need to analyze team communications, track engagement, reconstruct conversation threads, query historical messages, or extract insights from Slack data. Supports JIRA enrichment, DuckDB queries, and LLM-optimized message formatting.
license: See LICENSE file
---

# Slack Intelligence Tool

A comprehensive Slack data analytics platform that caches workspace messages in columnar Parquet format, enabling powerful SQL-based analysis, thread reconstruction, and intelligence extraction from team communications.

## Core Capabilities

### 1. Message Caching & Storage
- **Parquet-based caching**: Convert Slack messages to efficient columnar format
- **Partitioned by date and channel**: Optimized for time-based and channel-specific queries
- **Thread-aware storage**: Preserves parent-reply relationships for conversation reconstruction
- **JIRA enrichment**: Automatically extract and enrich JIRA ticket references
- **Incremental updates**: Cache new messages without reprocessing entire history

### 2. SQL Analytics with DuckDB
- **Direct SQL queries**: Query messages using standard SQL syntax
- **Cross-channel analysis**: Aggregate data across multiple channels and date ranges
- **User engagement metrics**: Track message counts, thread participation, reaction patterns
- **Interactive REPL**: Real-time SQL exploration with result formatting
- **Multiple export formats**: Output as tables, JSON, or CSV

### 3. Thread Reconstruction & Formatting
- **Intelligent thread grouping**: Reconstruct conversation threads from flat message data
- **Parent-reply linking**: Maintain conversation hierarchy and context
- **LLM-optimized output**: Format messages for optimal AI consumption
- **Rich metadata**: Include user names, timestamps, reactions, and attachments
- **Custom view contexts**: Generate focused views for specific analysis tasks

### 4. Team Intelligence Extraction
- **User activity analysis**: Track who's most active, when, and in which channels
- **Engagement patterns**: Identify response times, thread depth, and collaboration dynamics
- **JIRA integration**: Link Slack discussions to project tracking tickets
- **Temporal analysis**: Understand communication patterns over time
- **Channel dynamics**: Compare activity across different team channels

## When to Use This Skill

Use `slack-intel` when users request:

- **Data Analysis Tasks**:
  - "Analyze our team's Slack activity"
  - "Show me the most active users this week"
  - "Which channels have the most engagement?"
  - "Find all messages mentioning [topic]"

- **Thread & Conversation Analysis**:
  - "Reconstruct this conversation thread"
  - "Show me all discussions about [project]"
  - "What were the main topics in #engineering?"
  - "Extract decisions from channel discussions"

- **Historical Queries**:
  - "What did we discuss last month?"
  - "Find messages from [user] in [timeframe]"
  - "Show conversation history for this topic"
  - "Export channel messages to analyze"

- **Integration Tasks**:
  - "Link Slack discussions to JIRA tickets"
  - "Show all messages referencing ticket ABC-123"
  - "Enrich our cache with JIRA metadata"

- **Reporting & Insights**:
  - "Generate a summary of team activity"
  - "Track user engagement over time"
  - "Identify key contributors in discussions"
  - "Export data for further analysis"

## Command Reference

### Cache Command: Fetch and Store Messages

```bash
# Basic usage - cache last 2 days from configured channels
slack-intel cache

# Specific timeframe
slack-intel cache --days 7

# Specific channel by ID
slack-intel cache --channel C1234567890 --days 3

# Multiple channels
slack-intel cache -c C1234567890 -c C0987654321 --days 5

# With JIRA enrichment
slack-intel cache --days 7 --enrich-jira

# Custom cache location
slack-intel cache --cache-path /path/to/cache --days 2
```

**Key Features**:
- Partitions messages by actual message timestamp (not cache time)
- Creates date-partitioned directory structure: `dt=YYYY-MM-DD/channel=name/`
- Displays progress bars and summary statistics
- Handles rate limiting and async API calls
- Extracts JIRA ticket IDs and optionally fetches metadata

**Output**: Parquet files organized by date and channel with summary table showing message counts and sizes.

### Query Command: SQL Analytics

```bash
# Run SQL query
slack-intel query -q "SELECT user_real_name, COUNT(*) as messages
                      FROM 'cache/raw/messages/**/*.parquet'
                      GROUP BY user_real_name
                      ORDER BY messages DESC"

# Interactive SQL REPL
slack-intel query --interactive

# Date-filtered query using partition columns
slack-intel query -q "SELECT * FROM 'cache/raw/messages/**/*.parquet'
                      WHERE dt >= '2025-10-15' AND dt <= '2025-10-20'"

# Channel-specific analysis
slack-intel query -q "SELECT text, user_real_name, timestamp
                      FROM 'cache/raw/messages/**/*.parquet'
                      WHERE channel = 'channel_C1234567890'
                      LIMIT 100"

# Thread analysis
slack-intel query -q "SELECT thread_ts, COUNT(*) as replies
                      FROM 'cache/raw/messages/**/*.parquet'
                      WHERE is_thread_reply = true
                      GROUP BY thread_ts
                      ORDER BY replies DESC"

# Export as JSON
slack-intel query -q "SELECT * FROM 'cache/raw/messages/**/*.parquet'
                      WHERE dt='2025-10-20'" --format json

# Export as CSV
slack-intel query -q "SELECT user_real_name, text
                      FROM 'cache/raw/messages/**/*.parquet'" --format csv
```

**Key SQL Patterns**:

1. **User Activity Ranking**:
```sql
SELECT user_real_name, COUNT(*) as msg_count,
       COUNT(DISTINCT dt) as active_days
FROM 'cache/raw/messages/**/*.parquet'
GROUP BY user_real_name
ORDER BY msg_count DESC
```

2. **Thread Engagement Analysis**:
```sql
SELECT thread_ts, user_real_name as thread_starter,
       COUNT(*) as total_replies
FROM 'cache/raw/messages/**/*.parquet'
WHERE is_thread_reply = true
GROUP BY thread_ts, user_real_name
HAVING COUNT(*) > 5
```

3. **Daily Activity Patterns**:
```sql
SELECT dt as date, channel, COUNT(*) as message_count
FROM 'cache/raw/messages/**/*.parquet'
GROUP BY dt, channel
ORDER BY dt DESC, message_count DESC
```

4. **JIRA Ticket References**:
```sql
SELECT text, user_real_name, timestamp,
       UNNEST(jira_tickets) as ticket_id
FROM 'cache/raw/messages/**/*.parquet'
WHERE len(jira_tickets) > 0
```

5. **Reaction Analysis**:
```sql
SELECT UNNEST(reactions).name as emoji,
       COUNT(*) as usage_count
FROM 'cache/raw/messages/**/*.parquet'
WHERE len(reactions) > 0
GROUP BY emoji
ORDER BY usage_count DESC
```

**Interactive Mode**:
- Type SQL queries directly at `sql>` prompt
- Results displayed as formatted tables
- Use `exit`, `quit`, or `\q` to leave
- Includes sample queries for quick start

### Stats Command: Cache Overview

```bash
# View cache statistics
slack-intel stats

# Export stats as JSON
slack-intel stats --format json

# Check specific cache location
slack-intel stats --cache-path /custom/cache/path
```

**Output**:
- Total partitions (date/channel combinations)
- Total message count across all cached data
- Total storage size in MB
- Per-partition breakdown with paths, message counts, and sizes

### View Command: Formatted Message Display

```bash
# View specific date
slack-intel view --channel backend-devs --date 2025-10-20

# View date range
slack-intel view -c engineering --start-date 2025-10-18 --end-date 2025-10-20

# Save to file
slack-intel view -c general --date 2025-10-20 -o conversation.txt

# Use today's date (default)
slack-intel view --channel random

# Works with both channel names and IDs
slack-intel view -c C1234567890 --date 2025-10-20
```

**Features**:
- Reconstructs threaded conversations with proper nesting
- Groups parent messages with their replies
- Formats timestamps in human-readable format
- Includes user names, reactions, and metadata
- Optimized for LLM consumption (clear structure, rich context)

**Output Format**:
```
SLACK CONVERSATION VIEW
Channel: #backend-devs | Date: 2025-10-20

[2025-10-20 09:15:23] John Doe:
Hey team, thoughts on the new API design?

  [2025-10-20 09:18:45] Jane Smith (reply):
  I like the RESTful approach, but should we consider GraphQL?

  [2025-10-20 09:22:10] John Doe (reply):
  Good point. Let's discuss in tomorrow's sync.

[2025-10-20 10:30:00] Alice Johnson:
Deployed v2.1.0 to staging 🚀
[Reactions: ✅ (3), 🎉 (5)]
```

## Configuration

### Environment Variables

Required in `.env` file:
```bash
SLACK_API_TOKEN=xoxb-your-slack-bot-token
JIRA_USER_NAME=your-email@company.com  # Optional, for JIRA enrichment
JIRA_API_TOKEN=your-jira-api-token     # Optional, for JIRA enrichment
```

### Channel Configuration

Create `.slack-intel.yaml` in project root or home directory:
```yaml
channels:
  - name: general
    id: C0123456789
  - name: engineering
    id: C1234567890
  - name: random
    id: C0987654321
```

**Benefits**:
- Default channels for cache command
- Named references in queries and views
- Easier team onboarding
- Version-controllable configuration

## Data Schema

### Parquet Message Structure

Messages are stored with the following schema:

```
timestamp: datetime              # Message timestamp
text: string                     # Message content
user: string                     # User ID
user_real_name: string          # Display name
channel: string                  # Channel identifier
thread_ts: string (optional)     # Thread timestamp (parent message ID)
is_thread_reply: boolean        # Whether this is a reply in a thread
reactions: list<struct>         # Emoji reactions
  - name: string                # Emoji name
  - count: int                  # Number of reactions
  - users: list<string>         # Users who reacted
files: list<struct>             # Attached files
  - name: string
  - url: string
  - mimetype: string
jira_tickets: list<string>      # Extracted JIRA ticket IDs (e.g., ["PROJ-123"])
dt: string                      # Partition: date (YYYY-MM-DD)
```

### JIRA Enrichment Schema

When `--enrich-jira` is used, a separate Parquet file stores ticket metadata:

```
ticket_key: string              # e.g., "PROJ-123"
summary: string                 # Ticket title
status: string                  # Current status
assignee: string                # Assigned person
created: datetime               # Creation timestamp
updated: datetime               # Last update timestamp
priority: string                # Priority level
dt: string                      # Partition: cache date
```

## Advanced Usage Patterns

### Pattern 1: User Engagement Analysis

**Goal**: Identify top contributors and their activity patterns

```bash
# Step 1: Cache recent data
slack-intel cache --days 30

# Step 2: Query top users
slack-intel query -q "
  SELECT
    user_real_name,
    COUNT(*) as total_messages,
    COUNT(CASE WHEN is_thread_reply THEN 1 END) as thread_replies,
    COUNT(DISTINCT channel) as channels_active,
    COUNT(DISTINCT dt) as active_days,
    MIN(dt) as first_message,
    MAX(dt) as last_message
  FROM 'cache/raw/messages/**/*.parquet'
  GROUP BY user_real_name
  ORDER BY total_messages DESC
  LIMIT 20
" --format json > user_engagement.json
```

### Pattern 2: Thread Conversation Extraction

**Goal**: Extract and format complete conversation threads

```bash
# Step 1: Find active threads
slack-intel query -q "
  SELECT thread_ts, MIN(timestamp) as thread_start, COUNT(*) as replies
  FROM 'cache/raw/messages/**/*.parquet'
  WHERE channel = 'channel_C1234567890'
  GROUP BY thread_ts
  HAVING COUNT(*) > 3
  ORDER BY replies DESC
"

# Step 2: View specific thread (use thread_ts from query)
slack-intel query -q "
  SELECT timestamp, user_real_name, text, is_thread_reply
  FROM 'cache/raw/messages/**/*.parquet'
  WHERE thread_ts = '1697654321.123456' OR timestamp = '1697654321.123456'
  ORDER BY timestamp ASC
" --format table
```

### Pattern 3: JIRA Integration Analysis

**Goal**: Link Slack discussions to project tickets

```bash
# Step 1: Cache with JIRA enrichment
slack-intel cache --days 14 --enrich-jira

# Step 2: Query messages with JIRA references
slack-intel query -q "
  SELECT
    m.text,
    m.user_real_name,
    m.timestamp,
    UNNEST(m.jira_tickets) as ticket_id,
    j.summary as ticket_title,
    j.status as ticket_status
  FROM 'cache/raw/messages/**/*.parquet' as m
  LEFT JOIN 'cache/raw/jira/**/*.parquet' as j
    ON UNNEST(m.jira_tickets) = j.ticket_key
  WHERE len(m.jira_tickets) > 0
  ORDER BY m.timestamp DESC
"
```

### Pattern 4: Temporal Activity Heatmap

**Goal**: Understand when team is most active

```bash
slack-intel query -q "
  SELECT
    dt as date,
    HOUR(timestamp) as hour,
    COUNT(*) as message_count
  FROM 'cache/raw/messages/**/*.parquet'
  WHERE dt >= '2025-10-01'
  GROUP BY dt, HOUR(timestamp)
  ORDER BY dt, hour
" --format csv > activity_heatmap.csv
```

### Pattern 5: Channel Comparison

**Goal**: Compare activity across different team channels

```bash
slack-intel query -q "
  SELECT
    channel,
    COUNT(*) as total_messages,
    COUNT(DISTINCT user) as unique_users,
    COUNT(CASE WHEN is_thread_reply THEN 1 END) as thread_replies,
    AVG(len(text)) as avg_message_length
  FROM 'cache/raw/messages/**/*.parquet'
  WHERE dt >= '2025-10-01'
  GROUP BY channel
  ORDER BY total_messages DESC
"
```

## Python API Usage

For programmatic access, use the Python API:

```python
from slack_intel import ParquetCache, SlackChannelManager, TimeWindow, SlackChannel
from slack_intel.parquet_message_reader import ParquetMessageReader
from slack_intel.thread_reconstructor import ThreadReconstructor
from slack_intel.message_view_formatter import MessageViewFormatter, ViewContext
import asyncio

# Caching messages
async def cache_messages():
    manager = SlackChannelManager()
    cache = ParquetCache(base_path="cache/raw")

    channel = SlackChannel(name="engineering", id="C1234567890")
    time_window = TimeWindow(days=7)

    messages = await manager.get_messages(
        channel.id,
        time_window.start_time,
        time_window.end_time
    )

    # Save with automatic date partitioning
    for msg in messages:
        msg_date = msg.timestamp.strftime('%Y-%m-%d')
        cache.save_messages([msg], channel, msg_date)

# Reading and analyzing
def analyze_cached_data():
    reader = ParquetMessageReader(base_path="cache/raw")

    # Read specific date
    messages = reader.read_channel("engineering", "2025-10-20")

    # Read date range
    messages_range = reader.read_channel_range(
        "engineering",
        "2025-10-15",
        "2025-10-20"
    )

    # Reconstruct threads
    reconstructor = ThreadReconstructor()
    structured = reconstructor.reconstruct(messages_range)

    # Format for display
    context = ViewContext(
        channel_name="engineering",
        date_range="2025-10-15 to 2025-10-20"
    )
    formatter = MessageViewFormatter()
    view = formatter.format(structured, context)

    return view

# SQL queries with DuckDB
import duckdb

def query_with_duckdb():
    conn = duckdb.connect()
    result = conn.execute("""
        SELECT user_real_name, COUNT(*) as msg_count
        FROM 'cache/raw/messages/**/*.parquet'
        WHERE dt >= '2025-10-01'
        GROUP BY user_real_name
        ORDER BY msg_count DESC
    """).df()

    return result
```

## Best Practices

### 1. Caching Strategy
- **Incremental caching**: Run daily caches to keep data fresh without reprocessing
- **Partition optimization**: Use date partitions for efficient time-based queries
- **Channel selection**: Cache only relevant channels to minimize storage
- **JIRA enrichment**: Enable when ticket context is needed, disable for faster caching

### 2. Query Optimization
- **Use partition filters**: Filter by `dt` (date) and `channel` early in queries
- **Limit results**: Add `LIMIT` clauses to large result sets
- **Aggregate first**: Use GROUP BY and aggregations before detailed filtering
- **Index on common patterns**: DuckDB automatically optimizes Parquet column access

### 3. Thread Reconstruction
- **Date range considerations**: Thread replies may span multiple dates
- **Parent message inclusion**: Always include parent messages for context
- **Nested depth**: Slack supports one level of nesting (parent + replies)

### 4. LLM Integration
- **Use view command**: Formatted output is optimized for LLM consumption
- **Include context**: Add channel names, date ranges, and user info
- **Thread awareness**: Preserve conversation structure for better understanding
- **Selective extraction**: Query specific topics before formatting for focused analysis

### 5. JIRA Enrichment
- **Batch processing**: Enrichment fetches all unique tickets in one operation
- **Rate limiting**: Respects JIRA API rate limits with async batching
- **Selective enrichment**: Only enable when analyzing project-related discussions
- **Separate storage**: JIRA data stored independently for flexible joins

## Troubleshooting

### No messages cached
```bash
# Check if cache directory exists
slack-intel stats

# Verify Slack token and channel IDs
# Check .env file and .slack-intel.yaml

# Test with explicit channel ID
slack-intel cache --channel C1234567890 --days 1
```

### Query errors
```bash
# Verify cache path matches
slack-intel query -q "SELECT * FROM 'cache/raw/messages/**/*.parquet' LIMIT 1"

# Check partition structure
ls -la cache/raw/messages/

# Use interactive mode for query debugging
slack-intel query --interactive
```

### View command returns no results
```bash
# Check available dates
slack-intel stats

# Try with explicit date that exists in cache
slack-intel view --channel engineering --date 2025-10-20

# Handle channel naming: try both name and "channel_" prefix
slack-intel view -c general --date 2025-10-20
slack-intel view -c channel_C1234567890 --date 2025-10-20
```

### JIRA enrichment fails
```bash
# Verify JIRA credentials in .env
# Check JIRA_USER_NAME and JIRA_API_TOKEN

# Try caching without enrichment first
slack-intel cache --days 1

# Enable enrichment separately if needed
slack-intel cache --days 1 --enrich-jira
```

## Project Architecture

```
slack-intel/
├── src/slack_intel/
│   ├── cli.py                      # CLI interface (cache/query/stats/view)
│   ├── slack_channels.py           # Slack API integration
│   ├── parquet_cache.py            # Parquet storage engine
│   ├── parquet_message_reader.py   # Read from Parquet cache
│   ├── thread_reconstructor.py     # Thread structure rebuilding
│   ├── message_view_formatter.py   # LLM-optimized formatting
│   └── parquet_utils.py            # Partition utilities
├── tests/
│   ├── test_parquet_cache.py       # Cache unit tests
│   ├── test_parquet_message_reader.py
│   ├── test_thread_reconstructor.py
│   ├── test_message_view_formatter.py
│   └── test_integration.py         # End-to-end tests
├── cache/
│   └── raw/
│       ├── messages/
│       │   ├── dt=2025-10-20/
│       │   │   ├── channel=engineering/
│       │   │   └── channel=general/
│       │   └── dt=2025-10-21/
│       └── jira/                   # JIRA enrichment data
├── .slack-intel.yaml               # Channel configuration
├── .env                            # API credentials
└── README.md                       # Project documentation
```

## Dependencies

- **slack-sdk**: Official Slack API client
- **pyarrow**: Parquet file format support
- **duckdb**: In-process SQL analytics engine
- **pydantic**: Data validation and schema enforcement
- **rich**: Terminal formatting and progress bars
- **click**: CLI framework
- **aiohttp**: Async HTTP for Slack API
- **jira**: JIRA API integration (optional)

## Testing

Run comprehensive test suite:
```bash
# All tests
uv run pytest

# Specific test categories
uv run pytest tests/test_parquet_cache.py -v
uv run pytest tests/test_thread_reconstructor.py -v
uv run pytest tests/test_message_view_formatter.py -v

# Skip integration tests (require API access)
uv run pytest -v -m "not integration"
```

## Future Capabilities

Planned enhancements:
- **Incremental updates**: Smart delta caching to avoid reprocessing
- **Real-time streaming**: Live message ingestion from Slack events
- **Sentiment analysis**: Automated mood and tone detection
- **Topic modeling**: Automatic conversation categorization
- **User network graphs**: Visualization of collaboration patterns
- **Slack app integration**: Direct workspace installation
- **Multi-workspace support**: Aggregate across multiple Slack teams
- **Advanced JIRA workflows**: Bi-directional sync and status updates

---

## Summary

**Slack Intelligence** transforms Slack workspace data into a queryable analytics platform. By caching messages in Parquet format and providing SQL-based analysis, it enables:

- **Deep team insights**: Understand communication patterns and engagement
- **Thread reconstruction**: Rebuild conversations with full context
- **Project tracking**: Link discussions to JIRA tickets
- **Historical analysis**: Query months of conversation data efficiently
- **LLM integration**: Format data for AI-powered analysis

Use this skill when users need to extract intelligence from team communications, analyze collaboration patterns, or transform unstructured Slack data into actionable insights.
