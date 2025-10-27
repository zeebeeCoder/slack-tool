# S3 Sync Documentation

## Overview

The `slack-intel sync` command provides incremental synchronization of your local Parquet cache to Amazon S3. This enables:

- **Cloud backup** of your Slack message cache
- **Data sharing** across teams and environments
- **Integration** with AWS analytics tools (Athena, Glue, Redshift Spectrum)
- **Archival** of historical Slack data

## Features

✅ **Incremental Sync**: Only uploads new or modified files
✅ **Hive Partition Preservation**: Maintains directory structure (`dt=2025-10-21/channel=xyz/`)
✅ **Efficient**: Uses s3pathlib's native sync with size/mtime comparison
✅ **AWS Native**: Uses boto3 with standard AWS credential chain
✅ **Dry Run Mode**: Preview what would be synced before uploading
✅ **Flexible**: Supports custom prefixes, regions, and AWS profiles

## Prerequisites

### 1. Install Dependencies

The S3 sync feature requires `s3pathlib`:

```bash
uv pip install slack-intel[s3]
# or if already installed:
uv pip install s3pathlib>=2.0.0
```

### 2. Configure AWS Credentials

The sync command uses the standard AWS credential chain. Configure credentials using one of:

**Option A: AWS SSO (Recommended for Organizations)**
```bash
# Configure SSO (one-time setup)
aws configure sso

# Login before using sync command
aws sso login --profile AdministratorAccess-276780518338

# Use SSO profile with sync
slack-intel sync --bucket my-bucket --profile AdministratorAccess-276780518338
```

**Option B: AWS CLI (Standard)**
```bash
aws configure
```

**Option C: Environment Variables**
```bash
export AWS_ACCESS_KEY_ID=your_key_id
export AWS_SECRET_ACCESS_KEY=your_secret_key
export AWS_DEFAULT_REGION=us-east-1
```

**Option D: Named Profiles**
```bash
# Configure a named profile
aws configure --profile production

# Use it with sync command
slack-intel sync --bucket my-bucket --profile production
```

**Option E: IAM Roles (EC2/ECS/Lambda)**

When running in AWS, use IAM roles attached to your compute resource. No explicit credentials needed.

### 3. Create S3 Bucket

```bash
# Create bucket
aws s3 mb s3://my-slack-data --region us-east-1

# Or use existing bucket
aws s3 ls s3://my-existing-bucket/
```

## Basic Usage

### Sync to S3 Bucket

```bash
# Sync entire cache to S3 bucket
slack-intel sync --bucket my-slack-data
```

This uploads:
```
cache/raw/messages/dt=2025-10-21/channel=engineering/data.parquet
  → s3://my-slack-data/messages/dt=2025-10-21/channel=engineering/data.parquet

cache/raw/jira/dt=2025-10-21/data.parquet
  → s3://my-slack-data/jira/dt=2025-10-21/data.parquet

cache/users.parquet
  → s3://my-slack-data/users.parquet
```

### Sync with Prefix

Organize data under a specific S3 prefix:

```bash
# Sync to production/ prefix
slack-intel sync --bucket my-slack-data --prefix production/

# Result: s3://my-slack-data/production/messages/dt=...
```

### Dry Run (Preview)

See what would be synced without actually uploading:

```bash
slack-intel sync --bucket my-slack-data --dry-run
```

### Delete Remote Files

Remove S3 files that no longer exist locally:

```bash
slack-intel sync --bucket my-slack-data --delete
```

**⚠️ Warning**: Use `--delete` carefully! Files deleted locally will be removed from S3.

## Advanced Usage

### Custom Cache Path

Sync from a non-default cache location:

```bash
slack-intel sync --bucket my-bucket --cache-path /path/to/custom/cache
```

### AWS Profile and Region

Use specific AWS profile and region:

```bash
slack-intel sync \
  --bucket my-slack-data \
  --profile production \
  --region us-west-2
```

### Combining Options

```bash
slack-intel sync \
  --bucket my-slack-data \
  --prefix prod/slack-cache/ \
  --region us-west-2 \
  --profile prod \
  --delete \
  --dry-run
```

## Workflow Examples

### Daily Backup Workflow

```bash
#!/bin/bash
# daily-backup.sh

# Cache latest messages
slack-intel cache --days 7

# Sync to S3 with prefix
slack-intel sync \
  --bucket company-slack-backups \
  --prefix daily/$(date +%Y-%m-%d)/

echo "Backup complete!"
```

### Multi-Environment Setup

```bash
# Development environment
slack-intel cache --days 2
slack-intel sync --bucket dev-slack-data --prefix dev/

# Production environment
slack-intel cache --days 90
slack-intel sync \
  --bucket prod-slack-data \
  --prefix prod/ \
  --profile production \
  --region us-west-2
```

### Incremental Sync

```bash
# Day 1: Full sync
slack-intel cache --days 30
slack-intel sync --bucket my-data

# Day 2: Only new/changed files uploaded
slack-intel cache --days 1
slack-intel sync --bucket my-data
# ↑ Only uploads yesterday's new partitions
```

## Integration with AWS Services

### Query with Athena

Once synced to S3, query your Slack data with Amazon Athena:

```sql
-- Create external table
CREATE EXTERNAL TABLE slack_messages (
  message_id STRING,
  user_id STRING,
  text STRING,
  timestamp STRING,
  thread_ts STRING,
  is_thread_parent BOOLEAN,
  is_thread_reply BOOLEAN,
  reply_count BIGINT,
  user_name STRING,
  user_real_name STRING,
  jira_tickets ARRAY<STRING>
)
PARTITIONED BY (
  dt STRING,
  channel STRING
)
STORED AS PARQUET
LOCATION 's3://my-slack-data/messages/';

-- Load partitions
MSCK REPAIR TABLE slack_messages;

-- Query
SELECT
  dt,
  channel,
  user_real_name,
  COUNT(*) as message_count
FROM slack_messages
WHERE dt >= '2025-10-01'
GROUP BY dt, channel, user_real_name
ORDER BY message_count DESC;
```

### AWS Glue Crawler

Automatically discover schema and partitions:

```bash
# Create Glue database
aws glue create-database --database-input '{"Name": "slack_data"}'

# Create crawler
aws glue create-crawler \
  --name slack-messages-crawler \
  --role AWSGlueServiceRole \
  --database-name slack_data \
  --targets '{"S3Targets": [{"Path": "s3://my-slack-data/messages/"}]}'

# Run crawler
aws glue start-crawler --name slack-messages-crawler
```

### Redshift Spectrum

Query S3 data directly from Redshift:

```sql
CREATE EXTERNAL SCHEMA slack_spectrum
FROM DATA CATALOG
DATABASE 'slack_data'
IAM_ROLE 'arn:aws:iam::123456789012:role/RedshiftSpectrumRole';

SELECT * FROM slack_spectrum.slack_messages
WHERE dt = '2025-10-21';
```

## Performance Tips

### 1. Use Appropriate Regions

Sync from EC2/ECS in the same region as your S3 bucket to avoid data transfer charges:

```bash
# If bucket is in us-west-2, run sync from us-west-2 EC2
slack-intel sync --bucket my-bucket --region us-west-2
```

### 2. Incremental Caching

Cache only recent data, sync frequently:

```bash
# Better: cache 1 day, sync daily
slack-intel cache --days 1
slack-intel sync --bucket my-bucket

# vs. cache 90 days, sync weekly (slower)
```

### 3. Monitor Costs

- **Storage**: Use S3 Intelligent-Tiering or Glacier for infrequent access
- **Requests**: Minimize PUT operations (use incremental sync)
- **Data Transfer**: Sync from same region as bucket

## Troubleshooting

### "Cannot access S3 bucket"

**Problem**: No AWS credentials configured or insufficient permissions

**Solutions**:
```bash
# For AWS SSO users - login first
aws sso login --profile AdministratorAccess-276780518338

# Check credentials
aws sts get-caller-identity --profile YOUR_PROFILE

# Verify bucket access
aws --profile YOUR_PROFILE s3 ls s3://my-bucket/

# Test the exact command that works
aws --profile AdministratorAccess-276780518338 s3 ls
# Then use same profile with slack-intel:
slack-intel sync --bucket my-bucket --profile AdministratorAccess-276780518338

# Check IAM permissions (need s3:PutObject, s3:GetObject, s3:ListBucket)
```

### "AWS credentials expired"

**Problem**: SSO session expired

**Solutions**:
```bash
# Re-authenticate with SSO
aws sso login --profile AdministratorAccess-276780518338

# Verify it works
aws --profile AdministratorAccess-276780518338 sts get-caller-identity

# Then retry sync
slack-intel sync --bucket my-bucket --profile AdministratorAccess-276780518338
```

### "Local path does not exist"

**Problem**: Cache directory not found

**Solutions**:
```bash
# Create cache first
slack-intel cache --days 7

# Or specify correct path
slack-intel sync --bucket my-bucket --cache-path /path/to/cache
```

### Slow Sync Performance

**Problem**: Many small files or network latency

**Solutions**:
- Run from EC2/ECS in same region as bucket
- Use larger cache windows (fewer, larger files)
- Consider S3 Transfer Acceleration for cross-region

### S3PathLib Import Error

**Problem**: `s3pathlib` not installed

**Solutions**:
```bash
# Install dependency
uv pip install s3pathlib>=2.0.0

# Or reinstall slack-intel
uv pip install --upgrade slack-intel
```

## Security Best Practices

### 1. Use IAM Roles (Recommended)

When running on AWS, use IAM roles instead of access keys:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::my-slack-data",
        "arn:aws:s3:::my-slack-data/*"
      ]
    }
  ]
}
```

### 2. Enable S3 Encryption

```bash
# Enable default encryption on bucket
aws s3api put-bucket-encryption \
  --bucket my-slack-data \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "AES256"
      }
    }]
  }'
```

### 3. Enable S3 Versioning

Protect against accidental deletions:

```bash
aws s3api put-bucket-versioning \
  --bucket my-slack-data \
  --versioning-configuration Status=Enabled
```

### 4. Restrict Bucket Access

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Deny",
      "Principal": "*",
      "Action": "s3:*",
      "Resource": "arn:aws:s3:::my-slack-data/*",
      "Condition": {
        "Bool": {
          "aws:SecureTransport": "false"
        }
      }
    }
  ]
}
```

## Architecture Notes

The S3 sync implementation uses:

- **s3pathlib**: High-level Python library for S3 operations
- **boto3**: AWS SDK for Python (under the hood)
- **Incremental sync**: Compares file size and modification time
- **Concurrent uploads**: Uses boto3's TransferConfig for parallelism

### Why s3pathlib?

Compared to alternatives:
- ✅ Built-in `sync_to()` method (like `aws s3 sync`)
- ✅ Pathlib-like interface (intuitive)
- ✅ Lightweight (focused dependencies)
- ✅ Hive partition aware
- ❌ No AWS CLI coupling (pure Python)

## Roadmap

Future enhancements:

- [ ] **Auto-sync**: Automatic sync after `cache` command
- [ ] **Config file**: Store S3 settings in `.slack-intel.yaml`
- [ ] **Progress bars**: Detailed upload progress for large files
- [ ] **GCS/Azure support**: Multi-cloud storage backends
- [ ] **Compression**: Optional gzip compression before upload
- [ ] **Lifecycle policies**: Automatic tier transitions

## See Also

- [Caching Architecture](CACHING_ARCHITECTURE.md)
- [Parquet Schema](PARQUET_SCHEMA.md)
- [Parquet Cache Usage](PARQUET_CACHE_USAGE.md)
- [s3pathlib Documentation](https://s3pathlib.readthedocs.io/)
