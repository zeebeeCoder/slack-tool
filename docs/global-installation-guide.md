# Global Installation Guide

## Overview

Slack-intel now supports global installation with centralized configuration and credential management. You can install it once and use it from anywhere on your system.

## Quick Start

### 1. Install Globally

Choose one of these installation methods:

```bash
# Option 1: Using uv tool (recommended if you have uv)
uv tool install .

# Option 2: Using pipx (recommended for general use)
pipx install .

# Option 3: Using pip (system or user install)
pip install .  # System-wide (may require sudo)
pip install --user .  # User install
```

### 2. Run Setup

After installation, run the interactive setup wizard:

```bash
slack-intel setup
```

This will:
- Create `~/.config/slack-intel/` directory
- Prompt for your API credentials (Slack, JIRA, OpenAI)
- Test your Slack connection
- Generate initial config file with secure permissions (600)
- Create cache directory at `~/.cache/slack-intel/`

### 3. Start Using

```bash
# Cache messages
slack-intel cache --channel backend-devs --days 7

# View messages
slack-intel view --channel backend-devs --days 7

# Process with LLM
slack-intel process --channel backend-devs --days 7
```

## Configuration

### Config File Location

Config files are searched in this order:

1. `~/.config/slack-intel/config.yaml` (XDG standard, highest priority)
2. `~/.slack-intel.yaml` (legacy support)
3. `./slack-intel.yaml` (project-specific, lowest priority)

### Config File Structure

```yaml
# ~/.config/slack-intel/config.yaml

# API Credentials (optional - can use environment variables instead)
credentials:
  slack:
    user_token: xoxp-...  # OAuth user token (preferred)
    # OR
    bot_token: xoxb-...   # Bot token

  jira:
    username: user@example.com
    api_token: your-jira-token
    server: https://your-domain.atlassian.net

  openai:
    api_key: sk-...

# Cache configuration
cache:
  path: ~/.cache/slack-intel  # Default if omitted

# Organization context (for attention flow analysis)
organization:
  name: "My Company"
  description: "Company description"
  stakeholders:
    - name: "CEO Name"
      weight: 10  # 1-10, higher = more attention
      role: "CEO"
      description: "Focus areas"

# Channel descriptions
channels:
  - name: "backend-devs"
    id: "C1234567890"
    description: "Backend development discussions"
    signal_type: "high"  # critical/high/medium/low

# ... other config sections
```

## Credential Management

### Priority Order

Credentials are loaded with this priority:

1. **Environment Variables** (highest priority, most secure)
2. **Config File** (convenience for single-user systems)

### Environment Variables

You can still use environment variables (they override config file):

```bash
# Add to ~/.zshrc or ~/.bashrc
export SLACK_API_TOKEN="xoxb-..."
export JIRA_API_TOKEN="your-token"
export JIRA_USER_NAME="user@example.com"
export OPENAI_API_KEY="sk-..."
```

### Which Method to Use?

**Use Config File** (credentials in `~/.config/slack-intel/config.yaml`):
- ✅ Single user on personal machine
- ✅ Convenience (no shell configuration needed)
- ✅ All credentials in one place
- ❌ Less secure if machine is shared

**Use Environment Variables**:
- ✅ Shared systems / production environments
- ✅ CI/CD pipelines
- ✅ More secure (not stored in file)
- ✅ Per-shell customization
- ❌ Must configure in each shell

**Use Both** (hybrid):
- Set commonly-used credentials in config
- Override with env vars when needed
- Env vars always take precedence

## Security

### File Permissions

The setup command automatically sets secure permissions:

```bash
chmod 600 ~/.config/slack-intel/config.yaml
```

Only the file owner can read/write the config.

### Security Recommendations

1. **Never commit credentials to git**:
   ```bash
   # Add to ~/.gitignore_global
   .config/slack-intel/config.yaml
   credentials.yaml
   ```

2. **Use environment variables for production**:
   - More secure than files
   - Works well with Docker, Kubernetes, CI/CD

3. **Check file permissions**:
   ```bash
   ls -la ~/.config/slack-intel/config.yaml
   # Should show: -rw------- (600)
   ```

## Cache Management

### Default Cache Location

Cache is stored at:
- macOS/Linux: `~/.cache/slack-intel/`
- Follows XDG Base Directory specification

### Custom Cache Location

**Option 1: Config file**
```yaml
cache:
  path: /mnt/data/slack-cache
```

**Option 2: Environment variable**
```bash
export SLACK_INTEL_CACHE="/mnt/data/slack-cache"
```

**Option 3: CLI flag** (overrides all)
```bash
slack-intel cache --cache-path /mnt/data/slack-cache
```

## Updating Installation

```bash
# If installed with uv tool
uv tool upgrade slack-intel

# If installed with pipx
pipx upgrade slack-intel

# If installed with pip
pip install --upgrade .
```

## Uninstalling

```bash
# If installed with uv tool
uv tool uninstall slack-intel

# If installed with pipx
pipx uninstall slack-intel

# If installed with pip
pip uninstall slack-intel

# Remove config and cache (optional)
rm -rf ~/.config/slack-intel
rm -rf ~/.cache/slack-intel
```

## Migration from Local Installation

If you were previously using `uv run slack-intel ...` from the repo:

### 1. Export your current config

```bash
# If you have .slack-intel.yaml in the repo
cp .slack-intel.yaml ~/.config/slack-intel/config.yaml
```

### 2. Add credentials to config

Edit `~/.config/slack-intel/config.yaml` and add:

```yaml
credentials:
  slack:
    bot_token: "value-of-SLACK_API_TOKEN-env-var"
  jira:
    username: "value-of-JIRA_USER_NAME-env-var"
    api_token: "value-of-JIRA_API_TOKEN-env-var"
    server: "value-of-JIRA_SERVER-env-var"
  openai:
    api_key: "value-of-OPENAI_API_KEY-env-var"
```

Or keep using environment variables (they still work!).

### 3. Install globally

```bash
uv tool install .
```

### 4. Test it works

```bash
cd ~  # Navigate away from repo
slack-intel --help
slack-intel view --channel backend-devs --days 1
```

## Troubleshooting

### "Command not found: slack-intel"

**Cause**: Installation directory not in PATH

**Fix**:
```bash
# For uv tool
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# For pipx
# Usually auto-configured, but if not:
pipx ensurepath
```

### "Slack credential validation failed"

**Cause**: No credentials found

**Solutions**:
1. Run `slack-intel setup` to configure credentials
2. Or set environment variables:
   ```bash
   export SLACK_API_TOKEN="xoxb-..."
   ```
3. Check config file exists and has correct format

### "Config file has insecure permissions"

**Cause**: Config file is readable by others

**Fix**:
```bash
chmod 600 ~/.config/slack-intel/config.yaml
```

### "OpenAI API key not found"

**Cause**: No OpenAI key configured (only needed for `process` command)

**Fix**:
```bash
# Option 1: Add to config
slack-intel setup

# Option 2: Set environment variable
export OPENAI_API_KEY="sk-..."
```

### Cache in wrong location

**Check current cache path**:
```bash
python -c "from slack_intel.credentials import get_cache_path; print(get_cache_path())"
```

**Override**:
```bash
export SLACK_INTEL_CACHE="/your/preferred/path"
```

## Advanced: Multi-Environment Setup

You can have different configs for different environments:

### Work Environment

```bash
# ~/.config/slack-intel/config.yaml (default)
credentials:
  slack:
    bot_token: "work-token"
  jira:
    server: "https://work-jira.atlassian.net"
```

### Personal Environment

```bash
# ~/.slack-intel-personal.yaml
credentials:
  slack:
    bot_token: "personal-token"
```

Use with environment variable:

```bash
export SLACK_INTEL_CONFIG=~/.slack-intel-personal.yaml
slack-intel cache ...  # Uses personal config
```

## See Also

- [Custom Instructions](custom-instructions.md) - Customize LLM analysis
- [Configuration Quickstart](config-init-quickstart.md) - Organizational context setup
- Main README - General usage
