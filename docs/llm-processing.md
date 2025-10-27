# LLM Processing Pipeline

The slack-intel tool includes an LLM processing pipeline that can analyze Slack conversations and generate actionable insights using OpenAI's GPT models.

## Architecture

The pipeline is based on a chain-of-thought processing approach, similar to the YouTube analyzer reference implementation. It consists of:

1. **ChainProcessor** - Main orchestrator that manages the processing flow
2. **OpenAIProcessor** - Handles communication with OpenAI API
3. **Processing Context** - Data flow object that carries state through the pipeline
4. **Analysis Result** - Final output with summary and metrics

## Setup

### 1. Install Dependencies

```bash
# Using uv (recommended)
uv pip install -e .

# Or using pip
pip install -e .
```

### 2. Configure OpenAI API Key

Set your OpenAI API key as an environment variable:

```bash
export OPENAI_API_KEY='sk-...'
```

Or add it to your `.env` file:

```bash
echo "OPENAI_API_KEY=sk-..." >> .env
```

## Usage

### Process a Channel

Generate a view and process it with LLM in one command:

```bash
# Process single channel
slack-intel process --channel backend-devs --date 2025-10-20

# Process last 7 days (default)
slack-intel process --channel backend-devs
```

### Process Multiple Channels

```bash
# Process specific channels
slack-intel process -c backend-devs -c user-engagement

# Process all channels from config
slack-intel process --merge-channels
```

### Process User Timeline

Analyze a specific user's activity across all channels:

```bash
# Process user timeline (last 7 days)
slack-intel process --user shef

# Include threads where user was mentioned
slack-intel process --user shef --include-mentions

# Process user timeline for specific date range
slack-intel process --user shef --start-date 2025-10-20 --end-date 2025-10-27
```

**User timeline prompts focus on**:
- Key contributions and areas of activity
- Expertise and focus areas
- Communication patterns (questions, answers, decisions)
- Action items owned
- Collaboration network
- Questions and blockers

### Process Existing View File

If you already have a view saved, you can process it directly:

```bash
# First, generate a view
slack-intel view --channel backend-devs -o view.txt

# Then process it
slack-intel process --input view.txt --output summary.txt
```

### Model Configuration

#### Default Model (gpt-5)

```bash
# Uses gpt-5 by default
slack-intel process --channel backend-devs
```

#### Custom Parameters

```bash
slack-intel process \
  --channel backend-devs \
  --temperature 0.5 \
  --max-tokens 2000
```

#### Use GPT-5 (Responses API)

GPT-5 uses a different API (Responses API) with reasoning capabilities:

```bash
# Use GPT-5 with medium reasoning effort (default)
slack-intel process --channel backend-devs --model gpt-5

# Use GPT-5 with high reasoning effort for complex analysis
slack-intel process --channel backend-devs --model gpt-5 --reasoning-effort high

# Use GPT-5 with low reasoning effort for faster processing
slack-intel process --channel backend-devs --model gpt-5 --reasoning-effort low
```

**Note:** GPT-5 does not support:
- `--temperature` parameter (reasoning is controlled by `--reasoning-effort`)
- `--max-tokens` parameter (output length is automatically determined)
- Streaming (responses are returned all at once)

### Output Formats

#### Text Output (Default)

```bash
slack-intel process --channel backend-devs
```

Produces markdown-formatted output with:
- Channel metadata
- Date range
- Model used
- Processing time
- Summary with key insights

#### JSON Output

```bash
slack-intel process --channel backend-devs --format json -o insights.json
```

Produces structured JSON with all metadata and processing steps.

## Examples

### Daily Standup Summary

```bash
slack-intel process \
  --channel standup \
  --date 2025-10-27 \
  --temperature 0.3 \
  --output daily-standup-summary.txt
```

### Weekly Team Insights

```bash
slack-intel process \
  --merge-channels \
  --start-date 2025-10-20 \
  --end-date 2025-10-27 \
  --temperature 0.7 \
  --output weekly-insights.txt
```

### User Performance Review

Analyze a team member's contributions across all channels:

```bash
slack-intel process \
  --user shef \
  --start-date 2025-10-01 \
  --end-date 2025-10-27 \
  --reasoning-effort high \
  --output shef-october-review.txt
```

### Cross-Team Coordination Analysis

Analyze coordination across multiple specific teams:

```bash
slack-intel process \
  -c backend-devs \
  -c frontend-team \
  -c product-design \
  --start-date 2025-10-20 \
  --end-date 2025-10-27 \
  --output cross-team-coordination.txt
```

### Quick Analysis from Saved View

```bash
# Save view first
slack-intel view --channel backend-devs -o view.txt

# Process multiple times with different parameters
slack-intel process -i view.txt --temperature 0.3 -o conservative-summary.txt
slack-intel process -i view.txt --temperature 0.9 -o creative-summary.txt
```

## Pipeline Steps

The current implementation includes a single processing step:

1. **Process Messages** - Generates AI summary using OpenAI

Future steps could include:
- Sentiment analysis
- Entity extraction (people, projects, decisions)
- Action item detection
- Topic clustering
- Trend analysis

## Prompt Templates

The tool uses context-aware prompts that adapt to the type of view being processed:

### Single Channel Prompt

Used when processing a single channel with `--channel`. Focuses on:

1. Key topics and discussions
2. Important decisions made
3. Action items or follow-ups mentioned
4. Notable patterns or trends
5. Critical issues or concerns raised

### Multi-Channel Prompt

Used when processing multiple channels with `--merge-channels` or `-c channel1 -c channel2`. Focuses on:

1. **Common Themes**: Topics appearing across multiple channels
2. **Cross-Functional Coordination**: How different teams interact
3. **Channel-Specific Highlights**: Key developments unique to each channel
4. **Organization-Wide Trends**: Patterns affecting multiple teams
5. **Critical Dependencies**: Blockers or decisions impacting multiple channels
6. **Emerging Issues**: New concerns or opportunities

### User Timeline Prompt

Used when processing a user's timeline with `--user`. Focuses on:

1. **Key Contributions**: Main topics and areas where the user is active
2. **Expertise & Focus Areas**: Technical domains or business areas they engage with
3. **Communication Patterns**: How they interact (questions, answers, decisions, collaboration)
4. **Action Items Owned**: Tasks and responsibilities they've taken on
5. **Collaboration Network**: Who they work with most frequently
6. **Questions & Blockers**: Areas where they need input or are blocked

You can customize these prompts by modifying `src/slack_intel/pipeline/processors.py`.

## Cost Considerations

- **Token Estimation**: The tool estimates input tokens (1 token ≈ 4 characters)
- **Default Limits**: Max 4000 tokens output (configurable with `--max-tokens`)
- **Streaming**: Not supported by GPT-5 (returns full response at once)
- **Model Selection**:
  - Default model (gpt-5): Advanced reasoning capabilities
  - Use reasoning effort (low/medium/high) to control analysis depth

## Error Handling

The pipeline includes comprehensive error handling:

- API key validation
- Rate limiting (built into OpenAI SDK)
- Token limit warnings
- Step-by-step metrics
- Detailed error messages

## Extending the Pipeline

To add new processing steps, modify `src/slack_intel/pipeline/chain.py`:

```python
def _step_2_extract_entities(self, context: ProcessingContext) -> None:
    """Extract entities from the summary"""
    # Add your custom processing logic here
    pass
```

## Integration with View Command

The process command reuses the view command logic:

1. Reads messages from cache
2. Reconstructs thread structure
3. Formats with JIRA enrichment
4. Passes formatted output to LLM

This ensures consistent formatting between `view` and `process` commands.
