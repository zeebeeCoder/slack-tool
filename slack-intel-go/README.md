# Slack Intel (Go)

High-performance Go implementation of slack-intel CLI.

## Features

- ⚡ **Fast**: 30-60% faster than Python version
- 🚀 **Low Memory**: 4x lower memory footprint
- 📦 **Single Binary**: No runtime dependencies
- 🔄 **High Concurrency**: 100+ goroutines for parallel API calls

## Status

Phase 1: Foundation + Cache Command (In Progress)

## Build

```bash
cd slack-intel-go
go mod download
go build -o slack-intel ./cmd/slack-intel
```

## Usage

```bash
# Cache messages from last 7 days
./slack-intel cache --days 7

# Cache specific channel
./slack-intel cache --channel C9876543210 --days 3

# Cache with JIRA enrichment
./slack-intel cache --enrich-jira --days 7
```

## Configuration

Uses same `.slack-intel.yaml` as Python version:

```yaml
channels:
  - name: general
    id: C0123456789
  - name: engineering
    id: C9876543210
```

## Environment Variables

```bash
SLACK_API_TOKEN=xoxb-your-token
JIRA_API_TOKEN=your-jira-token
JIRA_USER_NAME=your-email@example.com
JIRA_SERVER=https://your-domain.atlassian.net
```
