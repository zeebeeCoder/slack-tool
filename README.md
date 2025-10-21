# Slack Intelligence Tool

LLM-optimized Slack message processing and intelligence extraction.

## Quick Start

1. **Install dependencies with uv:**
   ```bash
   uv sync
   ```

2. **Configure environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials
   ```

3. **Run the tool:**
   ```bash
   uv run python src/slack_intel/slack_channels.py
   ```

## Features

- **LLM-Optimized Text Generation**: Formats Slack conversations for optimal LLM consumption
- **Thread Clustering**: Groups messages with their replies spatially
- **SQL-Based JIRA Enrichment**: DuckDB-powered JOIN operations for displaying ticket metadata (summary, status, priority, assignee)
- **Rich Terminal Output**: Beautiful console display using Rich library
- **Async Processing**: Concurrent message fetching and processing
- **Parquet Caching**: Column-based storage for efficient cross-channel analysis

## Configuration

Required environment variables:
- `SLACK_API_TOKEN`: Your Slack bot token
- `JIRA_USER_NAME`: Your JIRA email
- `JIRA_API_TOKEN`: Your JIRA API token

Optional configuration via `.slack-intel.yaml`:
```yaml
# JIRA Configuration
jira:
  server: https://your-domain.atlassian.net

# Default channels
default_channels:
  - channel_C1234567890
  - backend-devs
```

## Output

The tool generates:
- Terminal preview with Rich formatting
- Text files: `llm_output_<channel>_<days>d.txt` for each channel
- Optimized format for direct LLM consumption

## Parquet Caching (Phase 2a)

Cache Slack messages in columnar Parquet format for efficient cross-channel analysis and querying.

### CLI Usage (Recommended)

**Cache messages from Slack:**
```bash
# Cache last 10 days from specific channel
slack-intel cache --days 10 --channel C1234567890

# Cache with JIRA enrichment (fetches ticket metadata)
slack-intel cache --days 10 --channel C1234567890 --enrich-jira

# Cache multiple channels
slack-intel cache --days 7 -c C9876543210 -c C1111111111

# Use default channels from config
slack-intel cache --days 5
```

**Query cached data:**
```bash
# Run SQL query
slack-intel query -q "SELECT user_real_name, COUNT(*) FROM 'cache/raw/messages/**/*.parquet' GROUP BY user_real_name"

# Interactive SQL mode
slack-intel query --interactive

# Export as JSON
slack-intel query -q "SELECT * FROM 'cache/raw/messages/**/*.parquet' LIMIT 10" --format json
```

**View formatted messages:**
```bash
# View messages from a specific date
slack-intel view --channel C1234567890 --date 2025-10-20

# View date range with JIRA enrichment
slack-intel view -c C1234567890 --start-date 2025-10-18 --end-date 2025-10-20

# Use channel name from config
slack-intel view -c backend-devs --date 2025-10-20
```

**View cache statistics:**
```bash
slack-intel stats
```

### Python API

**Quick Example:**
```python
from slack_intel import ParquetCache, SlackChannel

cache = ParquetCache(base_path="cache/raw")
cache.save_messages(messages, channel, "2023-10-18")

# Query with DuckDB
import duckdb
conn = duckdb.connect()
result = conn.execute("""
    SELECT user_real_name, COUNT(*) as msg_count
    FROM 'cache/raw/messages/**/*.parquet'
    WHERE dt = '2023-10-18'
    GROUP BY user_real_name
""").df()
```

**Features:**
- Partitioned by date and channel (`dt=YYYY-MM-DD/channel=name`)
- PyArrow schema with nested structures (reactions, files, JIRA tickets)
- Thread conversation support (parent/reply tracking)
- Automatic JIRA ticket extraction from message text
- DuckDB-compatible for SQL queries
- Rich CLI with progress bars and formatted output

See [PARQUET_CACHE_USAGE.md](docs/PARQUET_CACHE_USAGE.md) for detailed documentation.

## Project Structure

```
slack-tool/
   src/
      slack_intel/
          __init__.py
          slack_channels.py        # Main processing logic
          parquet_cache.py         # Parquet caching (Phase 2a)
          parquet_utils.py         # Partition utilities (Phase 1)
          cli.py                   # CLI interface (cache/query/stats)
          utils.py                 # Helper functions
   tests/
      fixtures.py                  # Test data generators
      test_integration.py          # Integration tests (Slack API)
      test_models.py               # Model validation tests
      test_parquet_models.py       # Schema conversion tests
      test_parquet_cache.py        # ParquetCache unit tests
      test_parquet_validation.py   # DuckDB integration tests
      test_cache_threads_jira.py   # Thread & JIRA caching tests
   docs/
      PARQUET_SCHEMA.md            # Parquet schema documentation
      PARQUET_CACHE_USAGE.md       # Caching usage guide
   .slack-intel.example.yaml       # Example config file
   pyproject.toml                  # uv project config
   .env.example                    # Environment template
   README.md                       # This file
```

## Development

Install with dev dependencies:
```bash
uv sync --all-extras
```

Install git hooks (recommended):
```bash
./hooks/install.sh
```

Run tests:
```bash
uv run pytest
```

Format code:
```bash
uv run ruff check --fix
```

### Git Hooks

The project includes a pre-commit hook that runs unit tests before each commit. This ensures code quality and catches issues early. See [hooks/README.md](hooks/README.md) for details.

## Testing

**Current test status: 72/72 passing**

Test categories:
- Integration tests: 16 tests (Slack API + ParquetCache integration)
- Model validation: 8 tests (Pydantic models)
- Parquet model conversion: 27 tests (Phase 1)
- ParquetCache unit tests: 14 tests (Phase 2a)
- DuckDB validation: 7 tests (Phase 2a)
- Thread & JIRA caching: 6 tests (Thread tracking + JIRA extraction)

Run specific test suites:
```bash
uv run pytest tests/test_parquet_models.py -v
uv run pytest tests/test_parquet_cache.py -v
uv run pytest tests/test_parquet_validation.py -v
```
