# Custom Instructions Feature

## Overview

The custom instructions feature allows you to customize the analysis goals for the `process` command while preserving essential data context. This gives you flexibility to ask specific questions or focus on particular aspects of your Slack messages without losing the semantic understanding of message structure, threads, users, and timestamps.

## How It Works

### Template Architecture

Each LLM prompt is split into two parts:

1. **Foundation** (always included): Provides data context
   - System role description
   - Channel name or user timeline info
   - Date range
   - Organizational context (stakeholders, channel descriptions)
   - The actual message content

2. **Instructions** (customizable): Defines analysis goals
   - Analysis framework (default: Attention Flow)
   - Specific questions to answer
   - Output format preferences

When you provide custom instructions, they replace only the **Instructions** part while preserving the **Foundation** that helps the LLM understand your data structure.

### View Types

The foundation adapts based on the view type:

- **Single Channel**: `channel_name`, `date_range`, `message_content`
- **User Timeline**: `user_name`, `channels`, `date_range`, `message_content`
- **Multi-Channel**: `channels[]`, `date_range`, `message_content`

## Usage

### Option 1: Inline Instructions

Pass custom instructions directly via the `--instructions` parameter:

```bash
slack-intel process --channel backend-devs --days 7 \
  --instructions "Summarize the top 3 action items with owners and deadlines."
```

### Option 2: Instructions from File

Store your instructions in a file and reference it with `--instructions-file`:

```bash
slack-intel process --channel backend-devs --days 7 \
  --instructions-file custom-analysis.txt
```

**Note**: If both `--instructions` and `--instructions-file` are provided, the file takes precedence.

## Examples

### Example 1: Focus on Action Items

**File: `action-items-prompt.txt`**
```
Please analyze these messages and extract:

1. **Action Items**: List all action items with:
   - Description of the task
   - Owner (person responsible)
   - Deadline (if mentioned)
   - Status (committed, in-progress, blocked)

2. **Blockers**: Any blockers preventing progress

3. **Dependencies**: Cross-team dependencies mentioned

Keep the output concise and structured as a checklist.
```

**Command:**
```bash
slack-intel process -c backend-devs --days 14 \
  --instructions-file action-items-prompt.txt
```

### Example 2: Leadership Decision Analysis

**Inline command:**
```bash
slack-intel process --merge-channels --days 7 \
  --instructions "Focus on decisions made by leadership (CEO, VPs). For each decision:
  - What was decided
  - Who made the decision
  - When it was made
  - What channels discussed it
  - What's the next step"
```

### Example 3: Technical Debt Tracking

**File: `tech-debt-prompt.txt`**
```
Analyze these messages for technical debt discussions:

1. **Technical Debt Identified**:
   - What technical debt was mentioned?
   - Who raised it?
   - Severity (critical, high, medium, low)

2. **Proposed Solutions**:
   - What solutions were discussed?
   - Cost/effort estimates mentioned?

3. **Prioritization**:
   - Was it prioritized? If so, when will it be addressed?
   - Why was it prioritized (or not)?

Categorize by system/component (e.g., authentication, database, API).
```

**Command:**
```bash
slack-intel process -c backend-devs -c infrastructure --days 30 \
  --instructions-file tech-debt-prompt.txt \
  --model gpt-5 --reasoning-effort high
```

### Example 4: User Timeline Analysis

**Inline command for user timeline:**
```bash
slack-intel process --user john.doe --days 14 \
  --instructions "Analyze this user's contributions:
  - What projects are they working on?
  - Are they blocked on anything?
  - What questions are they asking?
  - What expertise are they demonstrating?
  Provide a 2-paragraph summary."
```

### Example 5: Incident Postmortem

**File: `incident-postmortem.txt`**
```
This is an incident postmortem analysis. Please extract:

## Timeline
- When was the incident first detected?
- Key events during the incident (with timestamps)
- When was it resolved?

## Root Cause
- What caused the incident?
- Were there any contributing factors?

## Impact
- What systems were affected?
- Were customers impacted?
- Duration of impact

## Action Items
- Preventive measures proposed
- Monitoring improvements needed
- Process changes required

## Follow-ups
- Who is responsible for each action item?
- What are the deadlines?
```

**Command:**
```bash
slack-intel process -c incidents --days 1 \
  --end-date 2024-01-15 \
  --instructions-file incident-postmortem.txt \
  --output incident-2024-01-15-postmortem.md
```

### Example 6: Sprint Retrospective

**Inline command:**
```bash
slack-intel process -c sprint-team --days 14 \
  --instructions "Generate a sprint retrospective:

  **What went well:**
  - Wins and accomplishments

  **What didn't go well:**
  - Challenges and blockers

  **Action items for next sprint:**
  - Process improvements
  - Technical improvements

  Focus on actionable insights."
```

### Example 7: Cross-functional Coordination

**File: `cross-func-analysis.txt`**
```
Analyze cross-functional coordination:

1. **Handoffs**: What work is being handed off between teams?
   - From which team to which team?
   - Is the handoff smooth or are there blockers?

2. **Dependencies**: What dependencies exist between teams?
   - Who is waiting on whom?
   - Are there SLA concerns?

3. **Communication Gaps**: Are there communication issues?
   - Missing context?
   - Duplicate discussions?

4. **Recommendations**: How can coordination improve?
```

**Command:**
```bash
slack-intel process --merge-channels --days 7 \
  --bucket-by day \
  --instructions-file cross-func-analysis.txt \
  --format json -o coordination-report.json
```

### Example 8: Quarterly Planning

**File: `quarterly-planning.txt`**
```
Extract quarterly planning insights:

## Themes & Priorities
- What are the top 3-5 strategic themes?
- Which initiatives have executive sponsorship?

## Resource Allocation
- What teams/people are mentioned for each initiative?
- Are there resource conflicts?

## Risks & Dependencies
- What risks have been identified?
- What external dependencies exist?

## Timeline & Milestones
- What are the key milestones for Q2?
- Are any deadlines aggressive or at risk?

Organize by theme, not by channel.
```

**Command:**
```bash
slack-intel process --merge-channels --days 30 \
  --instructions-file quarterly-planning.txt \
  --model gpt-5 --reasoning-effort high
```

## Tips for Writing Effective Custom Instructions

### 1. Be Specific About Output Format

❌ Bad: "Tell me what happened"
✅ Good: "List the top 3 topics in bullet points with 1-2 sentence descriptions"

### 2. Request Structured Output

Use headings, bullet points, and numbered lists to get organized responses:

```
Please structure your analysis as:

## Section 1: Topic Overview
- Bullet points

## Section 2: Action Items
1. Numbered list
2. With clear structure
```

### 3. Leverage Organizational Context

If you have a `.slack-intel.yaml` config file with stakeholders and channel descriptions, reference them:

```
Focus on decisions involving leadership (check Key Stakeholders).
Prioritize signals from critical channels (check Channel Context).
```

### 4. Use Markdown for Emphasis

```
**Bold** for important categories
*Italic* for secondary details
> Blockquotes for key insights
```

### 5. Specify Scope and Depth

```
Provide a high-level summary (3-5 bullet points)
OR
Provide a detailed analysis with examples and timestamps
```

### 6. Ask for Metadata When Needed

```
For each action item, include:
- Owner (person responsible)
- Deadline (if mentioned)
- Priority (inferred from context)
- Status (new, in-progress, blocked)
```

## Default Prompts (No Custom Instructions)

If you don't provide custom instructions, the default Attention Flow prompts are used:

### Single Channel (default)
- KEY DISCUSSIONS (tactical, strategic, reactive classification)
- IMPORTANT DECISIONS & COMMITMENTS
- ACTION ITEMS & BLOCKERS
- ENGAGEMENT SIGNALS (thread depth, participation)
- TEMPORAL CONTEXT (new, resolved, ongoing topics)

### User Timeline
- FOCAL POINTS (where user attention is concentrated)
- KEY CONTRIBUTIONS & EXPERTISE
- COLLABORATION NETWORK
- WORK CLASSIFICATION (paddling vs boat-building)
- ACTION ITEMS & OWNERSHIP
- QUESTIONS & NEEDS

### Multi-Channel
- FOCAL POINTS (organizational attention)
- TEMPORAL DIRECTION (appearing, disappearing, persisting)
- PADDLING vs BOAT-BUILDING (tactical vs strategic work)
- DECISION POINTS & BLOCKERS
- ORGANIZATIONAL DYNAMICS (gravity wells, velocity, signal strength)

## Combining with Other Options

Custom instructions work with all process command options:

```bash
# Custom instructions + GPT-5 + high reasoning
slack-intel process -c backend-devs \
  --instructions-file analysis.txt \
  --model gpt-5 --reasoning-effort high

# Custom instructions + JSON output
slack-intel process --merge-channels \
  --instructions "Focus on action items only" \
  --format json -o output.json

# Custom instructions + user timeline
slack-intel process --user jane.smith \
  --include-mentions \
  --instructions-file user-focus.txt

# Custom instructions + multi-channel + bucketing
slack-intel process -c dev -c ops -c product \
  --bucket-by day \
  --instructions "Track cross-team dependencies"
```

## Troubleshooting

### Issue: Custom instructions not being applied

**Check:**
1. Is `OPENAI_API_KEY` set correctly?
2. Are you using a supported model (gpt-4o, gpt-5)?
3. Does the instructions file exist and is readable?

**Debug:**
```bash
# Verify file exists
cat custom-prompt.txt

# Test with inline instructions first
slack-intel process -c test --days 1 \
  --instructions "Test: List the first 3 messages only"
```

### Issue: Output doesn't match expectations

**Solutions:**
1. **Be more specific**: Add structure and examples to your prompt
2. **Use GPT-5 with high reasoning**: `--model gpt-5 --reasoning-effort high`
3. **Check data availability**: Ensure messages exist in the date range
4. **Review foundation context**: The LLM sees channel names, dates, and org context

### Issue: Instructions file not found

**Error:** `Error: Input file not found: custom-prompt.txt`

**Solutions:**
1. Use absolute path: `--instructions-file /full/path/to/file.txt`
2. Use relative path from current directory
3. Check file permissions: `ls -la custom-prompt.txt`

## Advanced: Testing Different Prompts

To quickly iterate on prompts without running the full pipeline:

```bash
# Generate a view once
slack-intel view -c backend-devs --days 7 -o view.txt

# Test different prompts using the saved view
slack-intel process --input view.txt \
  --instructions-file prompt-v1.txt

slack-intel process --input view.txt \
  --instructions-file prompt-v2.txt

slack-intel process --input view.txt \
  --instructions-file prompt-v3.txt
```

This saves cache processing time and lets you experiment with different analysis approaches.

## Example Workflows

### Workflow 1: Weekly Team Sync Prep

```bash
# Generate focused summary for Monday standup
slack-intel process -c team-alpha --days 7 \
  --instructions "Summarize:
  - Completed work (what shipped)
  - In-progress work (what's being worked on)
  - Blockers (what's stuck)
  - This week's focus (what's coming)" \
  -o weekly-sync-$(date +%Y-%m-%d).md
```

### Workflow 2: Quarterly Review

```bash
# Comprehensive analysis of last 90 days
slack-intel process --merge-channels --days 90 \
  --instructions-file quarterly-themes.txt \
  --model gpt-5 --reasoning-effort high \
  --format json -o q1-review.json

# Generate executive summary
cat q1-review.json | jq '.summary'
```

### Workflow 3: On-call Handoff

```bash
# Summarize incidents and ongoing issues
slack-intel process -c incidents -c ops-alerts --days 7 \
  --instructions "On-call handoff summary:
  - Active incidents (still ongoing)
  - Resolved incidents (root cause summary)
  - Monitoring alerts (patterns observed)
  - Known issues (watch out for)
  Keep it concise for quick handoff." \
  -o oncall-handoff-$(date +%Y-%m-%d).md
```

---

## See Also

- [Configuration Guide](config-init-quickstart.md) - Set up stakeholder weights and channel descriptions
- [Attention Flow Implementation](attention-flow-implementation.md) - Understanding default prompts
- Main README - General usage and setup
