# Caching Architecture for Cross-Channel Analysis

**Date:** 2025-10-19
**Status:** 💡 Design Ideation

---

## Problem Statement

### Current Limitations
From `SPIKE_SUMMARY.md`, the current approach:
- ✅ Fetches messages from multiple channels
- ✅ Generates LLM-optimized text per channel
- ❌ No cross-channel analysis
- ❌ No deduplication across channels
- ❌ No filtering by person/topic
- ❌ No queryable cache
- ❌ No relationship graphs

### Requirements
1. **Source data first** from multiple channels
2. **Cross-channel analysis** before LLM compression
3. **Find duplicates/related messages** across channels
4. **Filter by person, topic, time**
5. **Graph relationships** (user→message→thread→JIRA)
6. **Column-based format** for efficient queries
7. **Compress broader picture** for LLM after analysis

---

## Proposed Multi-Layer Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 4: LLM Compression                                    │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Cross-channel summaries, topic clusters, key insights  │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────────┐
│ Layer 3: Semantic Analysis                                  │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Vector embeddings, similarity search, topic clustering  │ │
│ │ Tools: sentence-transformers, FAISS, ChromaDB          │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────────┐
│ Layer 2: Relationship Graph                                 │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Cross-channel links, user activity, JIRA references     │ │
│ │ Tools: NetworkX, SQLite with graph queries              │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │
┌─────────────────────────────────────────────────────────────┐
│ Layer 1: Columnar Storage (SOURCE OF TRUTH)                 │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Parquet files: messages, users, threads, jira_tickets   │ │
│ │ Tools: Polars/DuckDB for fast queries                   │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

---

## Layer 1: Columnar Storage (Parquet)

### Why Column-Based?
- **Fast filtering**: Query by user, channel, time without loading entire dataset
- **Compression**: 10x smaller than JSON/text
- **Portable**: Works with DuckDB, Polars, Pandas, Spark
- **Schema enforcement**: Pydantic → Parquet schema
- **Partitioning**: By date/channel for incremental updates

### Schema Design

#### `messages.parquet`
```python
{
    "message_id": "1234567890.123456",           # Slack message ID
    "channel_id": "C9876543210",                 # Slack channel ID
    "channel_name": "engineering",               # Human-readable
    "user_id": "U012ABC3DEF",                    # Slack user ID
    "user_name": "john.doe",                     # Slack username
    "user_real_name": "John Doe",                # Full name
    "timestamp": "2025-10-18T13:18:00Z",         # UTC timestamp
    "text": "App is ready to be published",      # Message content
    "thread_ts": "1234567890.123456",            # Thread parent (nullable)
    "is_thread_parent": true,                    # Boolean
    "reply_count": 3,                            # Number of replies
    "reactions": [                                # Array of structs
        {"emoji": "100", "count": 1, "users": ["U012ABC3DEF"]}
    ],
    "attachments": [                              # Files, links
        {"type": "file", "url": "...", "name": "screenshot.png"}
    ],
    "jira_tickets": ["PROJ-456", "PROJ-123"],    # Extracted ticket IDs
    "mentioned_users": ["U012ABC3DEF"],          # @mentions
    "has_code_block": false,                     # Boolean flag
    "has_url": true,                             # Boolean flag
    "word_count": 24,                            # For filtering
    "fetch_time": "2025-10-19T10:00:00Z"         # When fetched
}
```

#### `threads.parquet`
```python
{
    "thread_ts": "1234567890.123456",            # Thread ID
    "channel_id": "C9876543210",
    "parent_message_id": "1234567890.123456",
    "reply_count": 3,
    "participants": ["U012ABC3DEF", "U987ZYX6WVU"],
    "first_reply_at": "2025-10-18T13:20:00Z",
    "last_reply_at": "2025-10-18T14:30:00Z",
    "duration_minutes": 70,
    "jira_tickets": ["PROJ-456"],                # All tickets in thread
}
```

#### `jira_tickets.parquet`
```python
{
    "ticket_id": "PROJ-456",
    "summary": "Fix login bug",
    "status": "In Progress",
    "assignee": "john.doe@example.com",
    "priority": "High",
    "sprint": "Sprint 42",
    "story_points": 5.0,
    "mentioned_in_channels": ["engineering", "random"],
    "mentioned_in_messages": ["1234567890.123456", ...],
    "first_mentioned": "2025-10-18T13:18:00Z",
    "mention_count": 7,
    "fetch_time": "2025-10-19T10:00:00Z"
}
```

#### `users.parquet`
```python
{
    "user_id": "U012ABC3DEF",
    "user_name": "john.doe",
    "real_name": "John Doe",
    "email": "john.doe@example.com",
    "is_bot": false,
    "channels_active": ["engineering", "random"],
    "message_count": 47,
    "thread_count": 12,
    "avg_messages_per_day": 3.2,
    "most_active_channel": "random",
    "jira_tickets_mentioned": ["PROJ-456", "PROJ-123"],
    "fetch_time": "2025-10-19T10:00:00Z"
}
```

### File Organization
```
cache/
├── raw/                           # Source of truth
│   ├── messages/
│   │   ├── dt=2025-10-18/        # Partitioned by date
│   │   │   ├── channel=engineering/
│   │   │   │   └── data.parquet
│   │   │   └── channel=random/
│   │   │       └── data.parquet
│   │   └── dt=2025-10-19/
│   ├── threads/
│   │   └── data.parquet
│   ├── jira_tickets/
│   │   └── data.parquet
│   └── users/
│       └── data.parquet
```

### Query Examples (DuckDB)

**Find all messages from a specific person across channels:**
```sql
SELECT channel_name, timestamp, text
FROM read_parquet('cache/raw/messages/**/*.parquet')
WHERE user_name = 'john.doe'
ORDER BY timestamp DESC
LIMIT 50;
```

**Cross-channel JIRA ticket analysis:**
```sql
SELECT
    jira_ticket,
    COUNT(DISTINCT channel_name) as channel_count,
    COUNT(*) as mention_count,
    LIST(DISTINCT channel_name) as channels
FROM (
    SELECT
        channel_name,
        UNNEST(jira_tickets) as jira_ticket
    FROM read_parquet('cache/raw/messages/**/*.parquet')
)
GROUP BY jira_ticket
HAVING channel_count > 1
ORDER BY mention_count DESC;
```

**Active threads across channels:**
```sql
SELECT
    t.thread_ts,
    m.channel_name,
    m.text as parent_message,
    t.reply_count,
    t.participants
FROM read_parquet('cache/raw/threads/*.parquet') t
JOIN read_parquet('cache/raw/messages/**/*.parquet') m
  ON t.parent_message_id = m.message_id
WHERE t.reply_count > 3
ORDER BY t.last_reply_at DESC;
```

---

## Layer 2: Relationship Graph

### Purpose
- Model **relationships** between entities
- Enable **graph traversal** queries
- Detect **cross-channel patterns**

### Graph Schema (NetworkX/SQLite)

**Nodes:**
- `User(id, name, real_name)`
- `Message(id, channel, timestamp, text)`
- `Thread(id, channel)`
- `JiraTicket(id, status, assignee)`
- `Channel(id, name)`

**Edges:**
- `User --POSTED--> Message`
- `Message --REPLIED_TO--> Message`
- `Message --PART_OF--> Thread`
- `Message --REFERENCES--> JiraTicket`
- `User --MENTIONED--> Message`
- `User --ACTIVE_IN--> Channel`
- `Message --SIMILAR_TO--> Message` (cross-channel)

### Example Graph Queries

**Find users who discuss same JIRA ticket across channels:**
```python
# NetworkX
import networkx as nx

def users_cross_channel_jira(G, ticket_id):
    """Find users discussing same JIRA ticket in different channels"""
    ticket_node = f"jira:{ticket_id}"

    # Get all messages referencing this ticket
    messages = [n for n in G.neighbors(ticket_node)
                if n.startswith("msg:")]

    # Get channels and users
    channel_users = {}
    for msg in messages:
        channel = G.nodes[msg]['channel']
        user = list(G.predecessors(msg))[0]  # User who posted
        channel_users.setdefault(channel, set()).add(user)

    # Find users in multiple channels
    multi_channel = [
        user for user in set().union(*channel_users.values())
        if sum(1 for users in channel_users.values() if user in users) > 1
    ]

    return multi_channel, channel_users
```

**Find message clusters (cross-channel related content):**
```python
def find_message_clusters(G, similarity_threshold=0.7):
    """Find clusters of related messages across channels"""
    # Filter to similarity edges > threshold
    similar_edges = [
        (u, v) for u, v, d in G.edges(data=True)
        if d.get('type') == 'similar_to'
        and d.get('score', 0) > similarity_threshold
    ]

    # Create subgraph and find connected components
    H = G.edge_subgraph(similar_edges)
    clusters = list(nx.connected_components(H))

    return clusters
```

### Storage: SQLite with Graph Extensions

```sql
-- Nodes table
CREATE TABLE nodes (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,  -- user, message, thread, jira, channel
    properties JSON
);

-- Edges table
CREATE TABLE edges (
    source TEXT,
    target TEXT,
    edge_type TEXT,
    properties JSON,
    FOREIGN KEY (source) REFERENCES nodes(id),
    FOREIGN KEY (target) REFERENCES nodes(id)
);

-- Indexes for fast traversal
CREATE INDEX idx_edges_source ON edges(source, edge_type);
CREATE INDEX idx_edges_target ON edges(target, edge_type);

-- Example: Find all messages by user in specific channel
SELECT n.properties->>'text' as message_text
FROM edges e
JOIN nodes n ON e.target = n.id
WHERE e.source = 'user:U012ABC3DEF'
  AND e.edge_type = 'POSTED'
  AND n.properties->>'channel' = 'engineering';
```

---

## Layer 3: Semantic Analysis

### Purpose
- Find **semantically similar** messages (not just keyword matching)
- Enable **topic clustering** across channels
- Detect **duplicate/related** discussions

### Technology Stack
- **sentence-transformers**: Generate embeddings
- **FAISS**: Fast vector similarity search
- **UMAP**: Dimensionality reduction for visualization
- **HDBSCAN**: Topic clustering

### Workflow

```python
from sentence_transformers import SentenceTransformer
import faiss
import numpy as np

# 1. Load messages from Parquet
messages_df = duckdb.query("""
    SELECT message_id, channel_name, text
    FROM read_parquet('cache/raw/messages/**/*.parquet')
""").to_df()

# 2. Generate embeddings
model = SentenceTransformer('all-MiniLM-L6-v2')
embeddings = model.encode(messages_df['text'].tolist())

# 3. Build FAISS index
dimension = embeddings.shape[1]
index = faiss.IndexFlatIP(dimension)  # Inner product (cosine sim)
index.add(embeddings.astype('float32'))

# 4. Find similar messages
query_embedding = embeddings[0:1]  # First message
k = 10  # Top 10 similar
scores, indices = index.search(query_embedding, k)

# 5. Cross-channel duplicates
for idx, score in zip(indices[0], scores[0]):
    if score > 0.85 and idx != 0:  # High similarity
        print(f"Similar: {messages_df.iloc[idx]['channel_name']}")
        print(f"  {messages_df.iloc[idx]['text'][:100]}")
```

### Topic Clustering

```python
import hdbscan
from umap import UMAP

# 1. Reduce dimensions (384 → 10)
reducer = UMAP(n_components=10, metric='cosine')
reduced = reducer.fit_transform(embeddings)

# 2. Cluster messages
clusterer = hdbscan.HDBSCAN(min_cluster_size=5)
labels = clusterer.fit_predict(reduced)

# 3. Analyze cross-channel topics
topics_df = messages_df.copy()
topics_df['topic_id'] = labels

cross_channel_topics = topics_df[topics_df['topic_id'] != -1].groupby('topic_id').agg({
    'channel_name': lambda x: list(set(x)),
    'message_id': 'count'
}).query('`message_id` > 1')  # Topics with multiple messages

print(cross_channel_topics)
```

### Output: `message_embeddings.parquet`
```python
{
    "message_id": "1234567890.123456",
    "embedding": [0.123, -0.456, ...],  # 384-dim vector
    "topic_id": 5,
    "topic_label": "login_bug_discussion",
    "similar_messages": ["9876543210.654321", ...],
    "cross_channel_duplicates": ["1111111111.111111"]
}
```

---

## Layer 4: LLM Compression

### Purpose
After analyzing Layers 1-3, compress for LLM:
- **Cross-channel summaries**
- **Deduplicated topics**
- **Key insights** (trends, blockers, decisions)

### Input Sources
1. **Messages** (Layer 1) - filtered by relevance
2. **Topics** (Layer 3) - clustered discussions
3. **Graph insights** (Layer 2) - relationships

### Compression Strategy

```python
from dataclasses import dataclass
from typing import List

@dataclass
class CrossChannelTopic:
    topic_id: int
    label: str
    channels: List[str]
    message_count: int
    key_messages: List[str]  # Most representative
    jira_tickets: List[str]
    participants: List[str]

@dataclass
class CompressedSummary:
    time_window: str
    channels_analyzed: List[str]
    total_messages: int

    # Cross-channel insights
    topics: List[CrossChannelTopic]
    cross_channel_duplicates: int

    # Key activity
    most_active_users: List[tuple]  # (user, channel, count)
    trending_jira: List[str]

    # Decisions & blockers
    decisions_made: List[str]
    blockers_identified: List[str]

    # For LLM
    llm_prompt: str

def generate_compressed_summary(days=7) -> CompressedSummary:
    """Generate cross-channel summary for LLM"""

    # 1. Get messages from Layer 1
    messages = load_messages_from_parquet(days=days)

    # 2. Get topics from Layer 3
    topics = load_topic_clusters()

    # 3. Get graph insights from Layer 2
    user_activity = get_user_activity_graph()
    jira_trends = get_jira_cross_channel()

    # 4. Build cross-channel topics
    cross_topics = []
    for topic in topics:
        if len(topic['channels']) > 1:  # Cross-channel
            # Get most representative messages
            key_msgs = get_topic_representatives(topic['topic_id'], n=3)

            cross_topics.append(CrossChannelTopic(
                topic_id=topic['topic_id'],
                label=infer_topic_label(key_msgs),
                channels=topic['channels'],
                message_count=topic['message_count'],
                key_messages=key_msgs,
                jira_tickets=extract_jira_from_topic(topic['topic_id']),
                participants=get_topic_participants(topic['topic_id'])
            ))

    # 5. Build LLM prompt
    llm_prompt = f"""
# Cross-Channel Slack Analysis ({days} days)

## Overview
- Channels analyzed: {len(set(m.channel for m in messages))}
- Total messages: {len(messages)}
- Cross-channel topics: {len(cross_topics)}

## Key Topics (Cross-Channel)

"""
    for topic in cross_topics:
        llm_prompt += f"""
### Topic: {topic.label}
- Channels: {', '.join(topic.channels)}
- Messages: {topic.message_count}
- Participants: {', '.join(topic.participants[:5])}
- JIRA: {', '.join(topic.jira_tickets)}

**Representative Messages:**
"""
        for msg in topic.key_messages:
            llm_prompt += f"- {msg}\n"

    return CompressedSummary(
        time_window=f"{days}d",
        channels_analyzed=list(set(m.channel for m in messages)),
        total_messages=len(messages),
        topics=cross_topics,
        llm_prompt=llm_prompt
    )
```

### Output Format for LLM

```
================================================================================
CROSS-CHANNEL SLACK INTELLIGENCE
Time Window: 7 days | Channels: 3 | Messages: 247 (deduplicated: 198)
================================================================================

## 🔄 CROSS-CHANNEL TOPICS

### Topic 1: Login Bug Discussion
- Channels: #engineering, #random
- Participants: John Doe, Jane Smith, Bob Johnson
- JIRA: PROJ-456, PROJ-789
- Status: 🟢 Resolved

**Timeline:**
1. Oct 18, 13:18 - Bug reported in #engineering by John
2. Oct 18, 14:30 - Root cause identified in #random by Jane
3. Oct 19, 09:00 - Fix deployed, confirmed in #engineering

**Key Messages:**
- "Users can't login after latest deploy" (#engineering)
- "Found issue in auth middleware, fixing now" (#random)
- "Fix deployed and tested, all good" (#engineering)

---

### Topic 2: Sprint Planning
- Channels: #random, #general
- Participants: 8 people
- JIRA: PROJ-123, PROJ-124, PROJ-125
- Status: 🟡 In Progress

**Key Decisions:**
- Prioritize PROJ-123 for this sprint
- Defer PROJ-125 to next sprint
- Need design review before starting PROJ-124

---

## 📊 ACTIVITY SUMMARY

**Most Active Users (Cross-Channel):**
1. John Doe: 47 messages (3 channels)
2. Jane Smith: 32 messages (2 channels)
3. Bob Johnson: 28 messages (2 channels)

**JIRA Tickets (Cross-Channel):**
1. PROJ-456: 12 mentions (2 channels) - ✅ Resolved
2. PROJ-123: 8 mentions (2 channels) - 🟡 In Progress
3. PROJ-789: 5 mentions (1 channel) - 🟠 Blocked

**Duplicate Discussions:**
- "Login bug": Discussed in #engineering (7 msgs) and #random (5 msgs)
- "Sprint planning": Discussed in #random (12 msgs) and #general (8 msgs)

## 🚨 BLOCKERS IDENTIFIED
1. PROJ-789 blocked on design approval (mentioned in 3 messages)
2. Testing environment down (mentioned in 2 messages)

================================================================================
```

---

## Implementation Roadmap

### Phase 1: Columnar Storage (Week 1)
- [ ] Define Parquet schemas (Pydantic models)
- [ ] Implement `ParquetCache` class
- [ ] Add `to_parquet()` methods to existing models
- [ ] Partition by date/channel
- [ ] DuckDB query layer

**Deliverable:** `cache/raw/messages/**/*.parquet`

### Phase 2: Graph Layer (Week 2)
- [ ] Implement `GraphBuilder` class
- [ ] Parquet → NetworkX conversion
- [ ] SQLite graph storage
- [ ] Cross-channel query functions
- [ ] Visualization (Graphviz)

**Deliverable:** `cache/graph.db` + query API

### Phase 3: Semantic Analysis (Week 3)
- [ ] Integrate sentence-transformers
- [ ] FAISS index builder
- [ ] Topic clustering (HDBSCAN)
- [ ] Similarity search API
- [ ] Deduplication logic

**Deliverable:** `cache/embeddings/` + topic labels

### Phase 4: LLM Compression (Week 4)
- [ ] Cross-channel aggregator
- [ ] Topic summarization
- [ ] Prompt builder
- [ ] Multi-provider integration (OpenAI, Claude, Gemini)
- [ ] A/B comparison

**Deliverable:** Compressed summaries for LLM

---

## Technology Stack

### Core
- **Polars** or **DuckDB**: Columnar queries
- **Parquet**: Storage format
- **NetworkX**: Graph analysis
- **SQLite**: Graph persistence

### ML/NLP
- **sentence-transformers**: Embeddings
- **FAISS**: Vector search
- **HDBSCAN**: Topic clustering
- **UMAP**: Dimensionality reduction

### Visualization
- **Graphviz**: Relationship graphs
- **Plotly**: Interactive charts
- **Rich**: Terminal output

### Existing
- **Pydantic**: Data validation
- **slack-sdk**: API client
- **jira**: API client

---

## Example End-to-End Flow

```python
from slack_intel import SlackChannelManager
from slack_intel.cache import ParquetCache
from slack_intel.graph import GraphBuilder
from slack_intel.semantic import TopicAnalyzer
from slack_intel.compress import LLMCompressor

# 1. Fetch from Slack (existing)
manager = SlackChannelManager()
channels = [
    SlackChannel(name="engineering", id="C9876543210"),
    SlackChannel(name="random", id="C1111111111"),
    SlackChannel(name="general", id="C0123456789"),
]
window = TimeWindow(days=7)

# 2. Save to Parquet (Layer 1)
cache = ParquetCache(base_path="cache/raw")
for channel in channels:
    messages = await manager.get_messages(channel, window)
    cache.save_messages(messages, channel, window)

# 3. Build graph (Layer 2)
graph_builder = GraphBuilder()
graph = graph_builder.from_parquet("cache/raw/messages/**/*.parquet")
graph.save("cache/graph.db")

# Cross-channel JIRA analysis
jira_insights = graph.analyze_jira_cross_channel()

# 4. Semantic analysis (Layer 3)
analyzer = TopicAnalyzer()
analyzer.load_from_parquet("cache/raw/messages/**/*.parquet")
topics = analyzer.cluster_topics(min_cluster_size=5)
duplicates = analyzer.find_duplicates(threshold=0.85)

# 5. Compress for LLM (Layer 4)
compressor = LLMCompressor()
summary = compressor.compress(
    messages=cache.load_all(),
    topics=topics,
    graph_insights=jira_insights,
    duplicates=duplicates
)

# 6. Send to LLM
from openai import OpenAI
client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4",
    messages=[
        {"role": "system", "content": "Analyze this Slack intelligence summary."},
        {"role": "user", "content": summary.llm_prompt}
    ]
)

print(response.choices[0].message.content)
```

---

## Benefits of This Architecture

### 1. **Separation of Concerns**
- Layer 1: Raw data (immutable)
- Layer 2: Relationships (queryable)
- Layer 3: Semantics (ML)
- Layer 4: Compression (LLM-ready)

### 2. **Incremental Updates**
- Append new data to Parquet partitions
- Rebuild only affected graph/embeddings
- Cache invalidation by date

### 3. **Flexible Querying**
- SQL (DuckDB): User/channel/time filters
- Graph (NetworkX): Relationship traversal
- Vector (FAISS): Semantic search

### 4. **Cross-Channel Analysis**
- Topic clustering across channels
- Duplicate detection
- User activity patterns
- JIRA ticket tracking

### 5. **Scalable**
- Parquet handles millions of messages
- FAISS handles millions of vectors
- Partitioning enables parallelism

### 6. **LLM-Optimized**
- Deduplicated input (lower costs)
- Topic-focused summaries
- Prioritized by relevance

---

## Open Questions

1. **Embedding model**: all-MiniLM-L6-v2 (fast) vs. larger model (accurate)?
2. **Graph DB**: NetworkX + SQLite vs. Neo4j?
3. **Incremental updates**: Rebuild all or delta-only?
4. **Topic labels**: LLM-generated vs. keyword extraction?
5. **Caching strategy**: Time-based vs. message-count-based invalidation?

---

## Next Steps

1. **Validate with current data**: Run Parquet conversion on existing Slack data
2. **Benchmark queries**: Test DuckDB performance on realistic queries
3. **Prototype topic clustering**: Run HDBSCAN on sample messages
4. **Define cache invalidation**: When to rebuild vs. append

**Ready for feedback and iteration!**
