# Config Management - Quick Start Guide

## Overview

Slack Intelligence has two config commands:
- **`config init`** - First-time setup (generates `.slack-intel.yaml` from cache)
- **`config sync-users`** - Add new team members to existing config (preserves your edits)

No more manual YAML writing!

## First-Time Setup

### 1. Cache Slack Data First

```bash
# Cache messages from your channels
slack-intel cache --days 30
```

This populates the user and channel cache.

### 2. Generate Config

```bash
# Generate .slack-intel.yaml with all users and channels
slack-intel config init
```

**Output**: `.slack-intel.yaml` with:
- ✅ All users from cache (default weight: 5)
- ✅ All channels from manifest
- ✅ Ready-to-edit format

### 3. Edit Config (5 minutes)

Open `.slack-intel.yaml` and:

#### A. Set Stakeholder Weights

Find key people and adjust their weights:

```yaml
stakeholders:
  - name: "Sarah Chen"
    weight: 10  # CEO - Change from 5 to 10
    role: "CEO"
    description: "Company strategy, product vision, key partnerships"

  - name: "Ankita Sharma"
    weight: 8   # VP - Change from 5 to 8
    role: "VP Product"
    description: "Product roadmap, feature prioritization, customer insights"

  - name: "Dev Bharat"
    weight: 7   # Lead - Change from 5 to 7
    role: "Engineering Lead"
    description: "Technical architecture, infrastructure decisions"
```

**Weight Guide:**
- **10** = CEO, Founder (highest attention)
- **8-9** = C-suite, VPs
- **7** = Directors, Senior Leads
- **5** = Everyone else (default)
- **1-4** = Low priority (or delete entry)

#### B. Delete Unnecessary Users

Remove users you don't need to track:

```yaml
# BEFORE (100 users)
stakeholders:
  - name: "Random User 1"
    weight: 5
  - name: "Random User 2"
    weight: 5
  # ... 98 more ...

# AFTER (Keep only key people - 10-20 users)
stakeholders:
  - name: "CEO Name"
    weight: 10
  - name: "VP Product"
    weight: 8
  # ... only leadership ...
```

#### C. Add Channel Descriptions

Describe what each channel is for:

```yaml
channels:
  - name: "engineering"
    id: "C9876543210"
    description: "Engineering coordination and technical decisions"
    signal_type: "high"

  - name: "incidents"
    id: "C5678901234"
    description: "Production incidents and emergency response"
    signal_type: "critical"

  - name: "random"
    id: "C1111111111"
    description: "Water cooler chat"
    signal_type: "low"
```

**Signal Types:**
- **critical** = Always important (incidents, security)
- **high** = Core work (engineering, product)
- **medium** = Support functions
- **low** = Social/non-work

### 4. Run Analysis

```bash
# Analyze with new attention-aware prompts
slack-intel process --merge-channels --days 7
```

The LLM now knows:
- Who the CEO/leadership are → **attention gravity**
- Which channels are critical → **signal ranking**
- Engagement metrics → **conversation hotness**

---

## Adding New Team Members (Later)

When new people join your team:

### 1. Cache Recent Messages

```bash
# Cache messages that include new team members
slack-intel cache --days 7
```

### 2. Sync New Users to Config

```bash
# Add new users from cache (keeps your edits)
slack-intel config sync-users
```

**What happens:**
- ✅ Reads your existing config (preserves all weights and descriptions)
- ✅ Finds users in cache that aren't in config
- ✅ Adds them with default weight 5
- ✅ Keeps everything else intact

**Example output:**
```
✓ Added 3 new users to .slack-intel.yaml

New users added:
  • Alice Johnson (weight: 5)
  • Bob Smith (weight: 5)
  • Carol Lee (weight: 5)

Next steps:
  1. Edit .slack-intel.yaml:
     - Adjust weights for new leaders (7-10)
     - Delete unneeded entries
```

### 3. Edit New Users

Open `.slack-intel.yaml` and adjust weights for the new users:

```yaml
stakeholders:
  # Existing users (unchanged)
  - name: "Sarah Chen"
    weight: 10  # Your edit preserved!
    role: "CEO"
    description: "Company strategy and direction"  # Preserved!

  # New users (added by sync-users)
  - name: "Alice Johnson"
    weight: 8   # Edit: New VP, bump to 8
    role: "VP Engineering"
    description: "Engineering org, technical hiring, platform architecture"

  - name: "Bob Smith"
    weight: 5   # Keep default
    role: ""
    description: ""  # Fill in if needed
```

---

## Example Output

With config enabled, you get enhanced analysis:

```
================================================================================
🏢 ORGANIZATION: Acme Corp
📱 SLACK CHANNELS: #engineering, #product, #incidents

📊 CONVERSATION METRICS:
   • Total Messages: 450
   • Leadership Involvement: 12 messages from key stakeholders 🔴
   • High Engagement Threads: 8 (5+ replies)

👥 KEY STAKEHOLDERS:
   🔴 Sarah Chen - CEO
   🟠 Ankita Sharma - VP Product
   🟠 Dev Bharat - Engineering Lead
================================================================================
```

Then the LLM analysis includes:

```markdown
## 1. FOCAL POINTS

🎯 **UPI Autopay Implementation**
   - Drivers: Sarah Chen (CEO), Ankita Sharma (VP Product) ← Leadership involvement
   - Intensity: HIGH (15 threads, 45 messages)
   - Work Type: 🚣 Tactical (execution)
   - State: Executing

🎯 **Data Lake Infrastructure**
   - Drivers: Dev Bharat (Engineering Lead)
   - Intensity: MEDIUM (3 threads, steady)
   - Work Type: 🛠️ Strategic (boat-building)
   - State: Ongoing
```

## Command Options

### `config init` (First-time setup)

```bash
# Basic usage (first time)
slack-intel config init

# Custom organization name
slack-intel config init --org-name "Acme Corp"

# Custom output path
slack-intel config init --output my-config.yaml

# Overwrite existing config (start over)
slack-intel config init --force

# Use different cache location
slack-intel config init --cache-path cache/backup
```

### `config sync-users` (Add new team members)

```bash
# Basic usage (add new users to existing config)
slack-intel config sync-users

# Use custom config path
slack-intel config sync-users --config-path my-config.yaml

# Use different cache location
slack-intel config sync-users --cache-path cache/backup
```

## Tips

### Tip 1: Keep It Small
Don't track all 100 users. Just 10-20 key stakeholders:
- CEO, Founders
- C-suite, VPs
- Directors, Leads
- Delete the rest

### Tip 2: Use Signal Types
Mark channels by importance:
- `critical` = Incidents, security alerts
- `high` = Core work channels
- `low` = Social, water cooler

### Tip 3: Alternative - Freeform Context
If structured data is still too much, use freeform text:

```yaml
organization:
  stakeholder_context: |
    Key people:
    - Sarah Chen (CEO) drives strategy
    - Ankita (Product) makes product calls
    - Dev (Eng) owns technical decisions
```

The LLM will parse natural language context.

### Tip 4: Sync Instead of Regenerate
When new team members join, DON'T regenerate - use sync:

```bash
# Cache new messages
slack-intel cache --days 7

# Sync new users (keeps your edits!)
slack-intel config sync-users

# Edit new users' weights
vim .slack-intel.yaml
```

**Why sync instead of init --force?**
- ✅ Preserves your existing weights and descriptions
- ✅ Only adds new users (doesn't touch anything else)
- ❌ `init --force` would reset all your edits!

## Troubleshooting

### No users in cache?

```bash
# Error: "No users found in cache"
# Solution: Cache messages first
slack-intel cache --days 30
```

### Too many users?

Generated config has 100+ users. **Delete most of them!** Keep only:
- Leadership (weight 7-10)
- People you actively track
- Delete the rest

### Config not loading?

```bash
# Check YAML syntax
cat .slack-intel.yaml

# Validate with Python
python -c "import yaml; print(yaml.safe_load(open('.slack-intel.yaml')))"
```

### Want to start over?

```bash
# Delete and regenerate from scratch
rm .slack-intel.yaml
slack-intel config init

# OR: Overwrite existing config
slack-intel config init --force
```

### Config not updating?

If `sync-users` doesn't add new people:
- They might already be in the config (check names, case-insensitive)
- They might not be in cache yet (run `slack-intel cache --days 7`)
- Check cache has user data: `ls cache/users/`

## What Gets Injected Into Prompts

The config enables:

1. **Stakeholder Context** (in prompts):
   ```
   Key Stakeholders:
   • Sarah Chen (CEO) - Executive level
   • Ankita Sharma (VP Product) - Leadership level
   ```

2. **Channel Context** (in prompts):
   ```
   Channel Context:
   • #incidents (🔴 CRITICAL): Production incidents
   • #engineering (🟠 HIGH): Core development
   ```

3. **Metadata Header** (in views):
   ```
   📊 CONVERSATION METRICS:
   • Leadership Involvement: 8 messages
   • High Engagement Threads: 12
   ```

4. **Attention Ranking** (in analysis):
   - CEO messages = Highest priority
   - Critical channels = Always important
   - Cross-functional threads = Organizational importance

## Next Steps

After setup:
- Run daily/weekly analysis: `slack-intel process --merge-channels`
- Adjust weights based on results
- Add/remove stakeholders as team changes
- Fine-tune channel signal types
