---
name: slack-intel-workflow
description: Orchestrate Slack intelligence extraction — cache messages, generate views, and process with LLM in a streamlined pipeline. Use when the user wants to pull Slack data, preview channel activity, generate summaries, or extract actionable insights from team communications.
---

# Slack Intel Workflow

Three-step pipeline: **cache** → **view** → **process**. Each step can run independently but they chain naturally: cache pulls raw data, view formats it for reading, process runs it through an LLM for insights.

## Prerequisites

The CLI `slack-intel` is installed globally via `uv tool install`. It reads configuration from:
- `.slack-intel.yaml` in the current directory (or `~/.config/slack-intel/config.yaml`)
- `.env` for API credentials (SLACK_API_TOKEN, JIRA_API_TOKEN, OPENAI_API_KEY)

The config YAML defines channels (with IDs, names, descriptions, signal types) and organizational stakeholders (with roles and weights). Check available channels:

```bash
cat .slack-intel.yaml   # or grep "name:" .slack-intel.yaml
```

The `cache/` directory in the working directory stores Parquet files. If you're working from a resource folder outside the repo, the `--cache-path` flag points to the cache location.

## Step 1: Cache

Pull messages from Slack API into local Parquet files partitioned by date and channel.

```bash
# Cache last 7 days from all configured channels
slack-intel cache --days 7

# Cache specific channel(s)
slack-intel cache -c backend-devs --days 14
slack-intel cache -c backend-devs -c design-product --days 7

# With JIRA ticket enrichment (fetches ticket metadata)
slack-intel cache --days 7 --enrich-jira
```

**Typical usage:** Run cache first to refresh data, especially if it's been more than a day since the last pull. The cache is idempotent — re-running merges new messages without losing existing data.

## Step 2: View

Generate a formatted, human/LLM-readable view from cached Parquet data.

```bash
# Single channel, last 7 days (default)
slack-intel view -c backend-devs

# Multiple days with auto-save to timestamped file
slack-intel view -c backend-devs --days 14 --auto-save
# → saves to: backend-devs_2025-10-20_143022.txt

# Merge all channels from config into one view
slack-intel view --merge-channels --days 7 --auto-save

# User timeline — one person across all channels
slack-intel view --user zeebee --days 30 --auto-save

# User timeline in specific channels, including threads where mentioned
slack-intel view --user zeebee -c backend-devs -c design-product --include-mentions --auto-save

# Explicit output file name
slack-intel view -c backend-devs --days 7 -o my-report.txt

# Control time bucketing for multi-channel/user views
slack-intel view --merge-channels --days 14 --bucket-by day --auto-save
```

**Key flags:**
| Flag | Purpose |
|------|---------|
| `-c`, `--channel` | Channel name(s) — repeatable |
| `--merge-channels` | All channels from config merged together |
| `-u`, `--user` | User timeline mode |
| `--include-mentions` | Include threads where user was mentioned (with `--user`) |
| `--days`, `-d` | Lookback window (default: 7) |
| `--end-date` | End date YYYY-MM-DD (default: today) |
| `--bucket-by` | Time grouping: `hour`, `day`, `none` (default: hour) |
| `-o`, `--output` | Explicit output filename |
| `--auto-save` | Auto-generate timestamped filename |

**Auto-save naming convention:**
- Single channel: `backend-devs_2025-10-20_143022.txt`
- Merged: `merged_2025-10-20_143022.txt`
- User timeline: `user-zeebee_2025-10-20_143022.txt`

## Step 3: Process

Run the view through an LLM (OpenAI) to extract structured insights.

```bash
# Process directly from cache (generates view internally)
slack-intel process -c backend-devs --days 7

# Process from a saved view file
slack-intel process --input backend-devs_2025-10-20_143022.txt -o summary.txt

# Merge all channels and process
slack-intel process --merge-channels --days 14 -o insights.txt

# Control LLM parameters
slack-intel process -c backend-devs --model gpt-5 --reasoning-effort high

# Custom analysis instructions (override default prompt)
slack-intel process -c backend-devs --instructions "Focus only on blockers and decisions"

# Load instructions from file
slack-intel process -c backend-devs --instructions-file my-prompt.txt

# JSON output format
slack-intel process --merge-channels --days 7 --format json -o insights.json
```

**Process flags:**
| Flag | Purpose |
|------|---------|
| `--input`, `-i` | Skip view generation, use existing file |
| `--model` | OpenAI model (default: gpt-5) |
| `--reasoning-effort` | `low`, `medium`, `high` (default: medium) |
| `--instructions` | Inline custom analysis prompt |
| `--instructions-file` | Load custom prompt from file |
| `--format` | `text` or `json` (default: text) |

## Common Workflows

### Daily standup prep
```bash
slack-intel cache --days 1
slack-intel view --merge-channels --days 1 --auto-save
slack-intel process --merge-channels --days 1 -o daily-summary.txt
```

### Weekly channel digest
```bash
slack-intel cache --days 7
slack-intel view -c backend-devs --days 7 --auto-save
slack-intel process -c backend-devs --days 7 --reasoning-effort high -o weekly-backend.txt
```

### Deep-dive on a person's activity
```bash
slack-intel cache --days 30
slack-intel view --user zeebee --days 30 --include-mentions --auto-save
slack-intel process --user zeebee --days 30 --include-mentions -o zeebee-30d.txt
```

### Custom analysis question
```bash
slack-intel view --merge-channels --days 14 --auto-save
slack-intel process --input merged_2025-10-20_143022.txt \
  --instructions "Identify the top 3 blockers and who owns them" \
  -o blockers.txt
```

## SQL Queries (Advanced)

Query the Parquet cache directly with DuckDB SQL:

```bash
# Who's most active?
slack-intel query -q "SELECT user_real_name, COUNT(*) as msgs FROM 'cache/raw/messages/**/*.parquet' GROUP BY 1 ORDER BY 2 DESC LIMIT 10"

# Activity per channel per day
slack-intel query -q "SELECT dt, channel, COUNT(*) FROM 'cache/raw/messages/**/*.parquet' GROUP BY 1,2 ORDER BY 1 DESC"

# Interactive SQL REPL
slack-intel query --interactive
```

## Cache Statistics

```bash
slack-intel stats          # Overview of cached data
slack-intel stats --format json
```

## Troubleshooting

- **No data after cache:** Verify `.slack-intel.yaml` has correct channel IDs, and `.env` has a valid SLACK_API_TOKEN
- **Channel not found in view:** Try both the channel name and `channel_CXXXXX` prefix format
- **Old data:** Re-run `slack-intel cache --days N` to refresh
- **Process fails:** Check OPENAI_API_KEY is set in `.env` or environment
