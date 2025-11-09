# Attention Flow Analysis - Implementation Guide

## Overview

We've enhanced Slack Intelligence with **Organizational Attention Flow** analysis capabilities. This adds temporal awareness, stakeholder-based attention ranking, and strategic vs tactical work classification to LLM processing.

## What's New

### 1. Enhanced Configuration (`.slack-intel.yaml`)

**Location**: `.slack-intel.yaml` in project root or home directory
**Example**: `.slack-intel.yaml.example`

#### New Config Sections:

**Organization Context**:
```yaml
organization:
  name: "Your Company Name"
  description: "Brief description"

  stakeholders:
    - name: "Sarah Chen"
      role: "CEO"
      focus_areas: ["Company strategy", "Product vision"]
      weight: 10  # Highest attention weight (1-10)
```

**Enhanced Channel Descriptions**:
```yaml
channels:
  - name: "engineering"
    id: "C9876543210"
    description: "Engineering team coordination"
    purpose: "Core product development and technical decisions"
    signal_type: "high"  # critical/high/medium/low
    tags: ["technical", "execution"]
```

**Analysis Configuration**:
```yaml
analysis:
  temporal:
    current_window_days: 7
    comparison_window_days: 21
    persistence_threshold_days: 28

  thresholds:
    high_velocity_hours: 4
    thread_depth_significant: 5
    participant_diversity: 3
    context_switch_rate: 5
```

### 2. Metadata Header in Views

Views now include computed metadata showing "conversation hotness":

```
================================================================================
🏢 ORGANIZATION: Your Company
📱 SLACK CHANNELS: #engineering, #product
   • engineering: Engineering team coordination
   • product: Product strategy and roadmap

⏰ TIME WINDOW: 2025-10-28 to 2025-11-03 (7 days)

📊 CONVERSATION METRICS:
   • Total Messages: 450
   • Active Threads: 45 (180 replies)
   • Avg Thread Depth: 4.2 replies
   • Unique Participants: 23
   • High Engagement Threads: 12 (5+ replies)
   • Leadership Involvement: 8 messages from key stakeholders

👥 KEY STAKEHOLDERS:
   🔴 Sarah Chen - CEO
   🟠 Ankita Sharma - VP Product
   🟠 Dev Bharat - Engineering Lead
================================================================================
```

### 3. Attention Flow Prompts

#### Single Channel Analysis:
- **Key Discussions** with tactical/strategic classification
- **Decisions & Commitments** with velocity tracking
- **Action Items & Blockers**
- **Engagement Signals** (thread depth, leadership involvement)
- **Temporal Context** (new/resolved/ongoing topics)

#### User Timeline Analysis:
- **Focal Points** (where user's attention is concentrated)
- **Work Classification** (% tactical vs strategic vs reactive)
- **Collaboration Network** (who they work with)
- **Expertise & Contributions**
- **Ownership & Commitments**

#### Multi-Channel Analysis (Full Attention Flow):
- **Focal Points** (org-wide attention concentration)
- **Temporal Direction** (appearing/disappearing/persisting topics)
- **Paddling vs Boat-Building** (tactical vs strategic effort %)
- **Decision Points & Blockers**
- **Organizational Dynamics** (gravity wells, cross-functional coordination)

## Usage

### Step 1: Create Config File

Copy `.slack-intel.yaml.example` to `.slack-intel.yaml` and customize:

```bash
cp .slack-intel.yaml.example .slack-intel.yaml
```

Edit the file with your:
- Organization name
- Key stakeholders (CEO, VPs, leads) with attention weights
- Channel descriptions and purposes
- Signal types (critical/high/medium/low)

### Step 2: Run Analysis with Enhanced Context

The config is automatically loaded when you run commands:

```bash
# Single channel analysis
slack-intel process --channel engineering --days 7

# Multi-channel with full attention flow
slack-intel process --merge-channels --days 14

# User timeline with work classification
slack-intel process --user zeebee --days 30
```

### Step 3: Interpret Results

**Attention Ranking**:
- Leadership involvement = Higher priority
- High engagement threads (5+ replies) = Strong signal
- Cross-functional discussions = Organization-wide importance

**Work Classification**:
- 🚣 **Paddling**: Tactical execution (features, bugs, support)
- 🛠️ **Boat-Building**: Strategic systems (process, infrastructure)
- ⚠️ **Drift**: Reactive overload (incidents, firefighting)

**Temporal Signals**:
- 📈 **APPEARING**: New topics or escalating attention
- 📉 **DISAPPEARING**: Resolved or fading topics
- 🔄 **PERSISTING**: Strategic continuity (4+ weeks)

## Implementation Details

### Files Modified:

1. **`src/slack_intel/config.py`** (NEW)
   - Enhanced config loader with organization context
   - Stakeholder and channel configuration management

2. **`src/slack_intel/message_view_formatter.py`**
   - Added `ViewMetadata` dataclass for computed statistics
   - Enhanced `ViewContext` with org_context
   - Added `compute_metadata()` static method
   - Enhanced `_format_header()` with metadata and stakeholder display

3. **`src/slack_intel/pipeline/processors.py`**
   - Updated all three prompt templates with Attention Flow framework
   - Added `org_context` parameter to `generate_summary()`
   - Added `_format_org_context()` helper method

4. **`.slack-intel.yaml.example`** (NEW)
   - Complete example configuration with all sections documented

### Integration Points:

To use in CLI (needs wiring):
1. Load config: `from .config import load_config`
2. Get org context: `config = load_config()`
3. Compute metadata: `ViewMetadata = MessageViewFormatter.compute_metadata(messages, org_context)`
4. Pass to processor: `processor.generate_summary(..., org_context=org_dict)`

## Edge Cases Handled

### 1. Resolved vs Abandoned Topics
- JIRA status enrichment shows resolution
- Thread closure pattern analysis
- Decision velocity tracking

### 2. Leadership Amplification
- CEO/VP messages get attention weight (7-10)
- Tracked separately in metadata
- Flagged in analysis as "gravity wells"

### 3. High-Value Low-Volume Work
- Strategic work (boat-building) gets separate classification
- Not penalized for low message count
- Emphasis on decision points and long-term impact

### 4. Channel Baseline Normalization
- Each channel has signal_type (critical/high/medium/low)
- Critical channels (e.g., incidents) always get attention
- Low-signal channels (e.g., random) deprioritized

## Next Steps (Optional Future Enhancements)

1. **CLI Integration** - Wire config loader into CLI commands
2. **Historical Comparison** - Compare current window to prior periods
3. **Topic Clustering** - Semantic analysis to detect recurring themes
4. **Velocity Metrics** - Time-to-decision tracking
5. **Cross-Window Analysis** - Detect appearing/disappearing with actual history
6. **JIRA Status Integration** - Use ticket status for resolution detection

## Testing

Create test config:
```bash
# Use example config
cp .slack-intel.yaml.example .slack-intel.yaml

# Test view with metadata
slack-intel view --merge-channels --days 7

# Look for:
# - 📊 CONVERSATION METRICS section
# - 👥 KEY STAKEHOLDERS section
# - Channel descriptions in header
```

Test processing (requires OpenAI API key):
```bash
export OPENAI_API_KEY='your-key'

# Single channel
slack-intel process --channel engineering --days 7

# Look for:
# - Tactical/Strategic/Reactive classification
# - Leadership involvement mentions
# - Engagement signal analysis
```

## Configuration Tips

### Stakeholder Weights:
- **10**: CEO, Founder
- **8-9**: C-suite, VPs
- **7**: Directors, Senior Leads
- **5-6**: Leads, Managers
- **<5**: Individual contributors (optional to include)

### Signal Types:
- **critical**: Incidents, production, security
- **high**: Core product, engineering, key business
- **medium**: Support functions, planning
- **low**: Social, water cooler, non-work

### Focus Areas:
- Be specific: "Payment infrastructure" not "Engineering"
- Helps LLM identify expertise and ownership
- Max 3-5 focus areas per stakeholder

## Questions?

See:
- `.slack-intel.yaml.example` for full configuration reference
- `src/slack_intel/config.py` for config schema
- `src/slack_intel/pipeline/processors.py` for prompt templates
