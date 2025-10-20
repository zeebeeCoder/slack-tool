# BDD Scenarios: Message View System

## Feature: Cache Slack Messages with Date-Based Partitioning

Messages should be partitioned by their actual timestamp date, enabling efficient querying by date.

### Scenario: Cache messages from last 7 days
```gherkin
Feature: Cache Slack messages with date partitioning

  Scenario: Cache messages from multiple days into separate partitions
    Given I have a Slack channel "engineering" with ID "C05713KTQF9"
    And the channel has messages from "2025-10-15" to "2025-10-20"
    When I run "slack-intel cache --channel C05713KTQF9 --days 7"
    Then messages should be partitioned by their timestamp date
    And partition "dt=2025-10-15" should contain messages from "2025-10-15"
    And partition "dt=2025-10-16" should contain messages from "2025-10-16"
    And partition "dt=2025-10-20" should contain messages from "2025-10-20"
    And the cache summary should show "X partitions: 2025-10-15 to 2025-10-20"

  Scenario: Cache with channel ID auto-prefixes channel name
    Given I cache using channel ID "C05713KTQF9"
    When messages are saved to Parquet
    Then they should be stored in "channel=channel_C05713KTQF9" directory
    And the channel name should be "channel_C05713KTQF9"

  Scenario: Cache with named channel from config
    Given I have a config file with channel "engineering" mapped to "C05713KTQF9"
    When I run "slack-intel cache --days 7"
    Then messages should be stored in "channel=engineering" directory
    And the channel name should be "engineering"
```

## Feature: View Messages by Date

### Scenario: View messages from specific date
```gherkin
Feature: Query cached messages by date

  Scenario: View messages from a single date
    Given messages are cached for dates "2025-10-15" to "2025-10-20"
    And channel "engineering" has 16 messages on "2025-10-15"
    When I run "slack-intel view --channel engineering --date 2025-10-15"
    Then I should see "Found 16 messages"
    And the view should show all 16 messages from "2025-10-15"
    And messages should be in chronological order

  Scenario: View date with no messages
    Given messages are cached for dates "2025-10-15" to "2025-10-20"
    When I run "slack-intel view --channel engineering --date 2025-10-12"
    Then I should see "No messages found in engineering for 2025-10-12"
    And I should see a hint to "check 'slack-intel stats'"

  Scenario: View date range across multiple partitions
    Given channel "engineering" has messages on multiple dates
    When I run "slack-intel view -c engineering --start-date 2025-10-15 --end-date 2025-10-17"
    Then messages from partitions "2025-10-15", "2025-10-16", "2025-10-17" should be combined
    And messages should be sorted chronologically across all dates
    And the view header should show "⏰ TIME WINDOW: 2025-10-15 to 2025-10-17"
```

## Feature: Channel Name Auto-Detection

### Scenario: View using raw channel ID
```gherkin
Feature: Auto-detect channel naming conventions

  Scenario: View with channel ID resolves to prefixed name
    Given messages were cached with channel ID "C05713KTQF9"
    And they are stored in partition "channel=channel_C05713KTQF9"
    When I run "slack-intel view --channel C05713KTQF9 --date 2025-10-20"
    Then the view command should try "C05713KTQF9" first
    And if not found, try "channel_C05713KTQF9"
    And successfully find and display messages
    And the header should show "📱 SLACK CHANNEL: channel_C05713KTQF9"

  Scenario: View with named channel works directly
    Given messages were cached for channel "engineering"
    And they are stored in partition "channel=engineering"
    When I run "slack-intel view --channel engineering --date 2025-10-20"
    Then the view should immediately find partition "channel=engineering"
    And display messages successfully
```

## Feature: Thread Reconstruction

### Scenario: Reconstruct complete thread from flat messages
```gherkin
Feature: Rebuild thread structure from flat Parquet data

  Scenario: Thread parent with all replies present
    Given flat messages:
      | id  | text                | thread_ts | is_parent | is_reply | reply_count |
      | 101 | Can someone review? | 101       | true      | false    | 2           |
      | 102 | Looking now         | 101       | false     | true     | 0           |
      | 103 | LGTM!               | 101       | false     | true     | 0           |
    When I reconstruct threads
    Then message 101 should have "replies" array with 2 items
    And "replies" should contain messages 102 and 103 in chronological order
    And the result should have 1 top-level message (not 3)

  Scenario: Orphaned replies - parent outside time window
    Given flat messages:
      | id  | text         | thread_ts | is_parent | is_reply |
      | 202 | First reply  | 201       | false     | true     |
      | 203 | Second reply | 201       | false     | true     |
    And message 201 (parent) is not in the dataset
    When I reconstruct threads
    Then messages 202 and 203 should be marked as "is_orphaned_reply: true"
    And they should be marked as "is_clipped_thread: true"
    And they should appear as separate top-level messages

  Scenario: Clipped thread - some replies missing
    Given a thread parent with "reply_count: 5"
    But only 2 replies are present in the dataset
    When I reconstruct threads
    Then the parent should be marked with "has_clipped_replies: true"
    And the view should indicate "showing 2 of 5+ replies"
```

## Feature: User Mention Resolution

### Scenario: Resolve mentions for users in conversation
```gherkin
Feature: Convert user IDs to readable names

  Scenario: Mention resolution for conversation participants
    Given these users posted messages:
      | user_id | user_real_name |
      | U001    | Alice Chen     |
      | U002    | Bob Martinez   |
      | U003    | Charlie Davis  |
    And a message contains text "Hey <@U002>, can you review? cc <@U003>"
    When I format the view
    Then the message should display "Hey @Bob Martinez, can you review? cc @Charlie Davis"
    And raw user IDs should not appear

  Scenario: Keep unknown user IDs as-is
    Given only user U001 posted messages
    And a message contains "<@U001> please review <@U999>"
    When I format the view
    Then the message should display "@Alice Chen please review <@U999>"
    And unknown user U999 should remain as "<@U999>"

  Scenario: Resolve mentions in thread replies
    Given a thread with parent from user U001
    And a reply containing "<@U001> here's the answer"
    And reply author is user U002
    When I format the view
    Then both users should be in the user mapping
    And the reply should show "@Alice Chen here's the answer"
```

## Feature: Rich Content Display

### Scenario: Display reactions, files, and JIRA tickets
```gherkin
Feature: Format rich Slack content in views

  Scenario: Message with reactions
    Given a message with reactions:
      | emoji  | count | users        |
      | rocket | 3     | U001,U002,U003 |
      | eyes   | 2     | U001,U002      |
    When I format the view
    Then I should see "😊 Reactions: rocket(3), eyes(2)"

  Scenario: Message with file attachments
    Given a message with files:
      | name           | mimetype        | size   |
      | design-v2.pdf  | application/pdf | 245000 |
      | screenshot.png | image/png       | 128000 |
    When I format the view
    Then I should see "📎 Files: design-v2.pdf (application/pdf), screenshot.png (image/png)"

  Scenario: Message with JIRA tickets
    Given a message containing text "Fixed PROJ-123 and PROJ-456"
    And JIRA tickets were extracted as ["PROJ-123", "PROJ-456"]
    When I format the view
    Then I should see "🎫 JIRA: PROJ-123, PROJ-456"

  Scenario: Message with all rich content types
    Given a message with reactions, files, and JIRA tickets
    When I format the view
    Then reactions should appear below message text
    And files should appear after reactions
    And JIRA tickets should appear after files
    And all sections should be properly indented
```

## Feature: Clipped Thread Indicators

### Scenario: Indicate when threads span beyond time window
```gherkin
Feature: Signal incomplete thread data to users

  Scenario: Parent present but some replies missing
    Given a thread parent with reply_count=5
    And only 2 replies are in the current date partition
    When I format the view
    Then the thread section should show "🧵 THREAD REPLIES (showing 2 of 5+ replies):"
    And a hint should appear: "💡 Thread may have additional replies outside this time range"

  Scenario: Orphaned reply without parent
    Given a thread reply where parent is outside the time window
    When I format the view
    Then the message header should show "💬 MESSAGE #X (🔗 Thread clipped)"
    And below the message should show "🔗 Thread clipped (parent message outside time window)"
    And a hint: "💡 Widen date range to see full thread"

  Scenario: Complete thread - no indicators
    Given a thread parent with reply_count=3
    And all 3 replies are present
    When I format the view
    Then the thread section should show "🧵 THREAD REPLIES:" (no count indicator)
    And no clipping hints should appear
```

## Feature: Save View to File

### Scenario: Export view to text file
```gherkin
Feature: Save formatted views to files

  Scenario: Save view to specified file
    Given I have cached messages for "engineering" on "2025-10-20"
    When I run "slack-intel view -c engineering --date 2025-10-20 -o report.txt"
    Then a file "report.txt" should be created
    And it should contain the full formatted view
    And I should see "✓ View saved to report.txt"
    And the view should not be printed to console

  Scenario: Default to console output when no file specified
    When I run "slack-intel view -c engineering --date 2025-10-20"
    Then the view should be printed to console
    And no file should be created
```

## Feature: Cache Statistics

### Scenario: View partition information
```gherkin
Feature: Inspect cache contents and structure

  Scenario: Show cache statistics
    Given I have cached messages across multiple dates and channels
    When I run "slack-intel stats"
    Then I should see total partition count
    And total message count across all partitions
    And total cache size in MB
    And a table listing each partition with:
      | Column   | Description                |
      | Path     | Partition path             |
      | Messages | Message count in partition |
      | Size     | Partition size in KB       |

  Scenario: Empty cache guidance
    Given I have no cached messages
    When I run "slack-intel stats"
    Then I should see "No cache found at: cache/raw"
    And a hint: "Run 'slack-intel cache' to create cache."
```

## Feature: Error Handling and User Guidance

### Scenario: No cache exists
```gherkin
Feature: Helpful error messages and guidance

  Scenario: View when cache doesn't exist
    Given no cache directory exists
    When I run "slack-intel view --channel engineering --date 2025-10-20"
    Then I should see an error about missing cache
    And a suggestion to run "slack-intel cache"

  Scenario: No messages for requested date
    Given cache exists but date 2025-10-12 has no messages
    When I run "slack-intel view --channel engineering --date 2025-10-12"
    Then I should see "No messages found in engineering for 2025-10-12"
    And a hint to "Try a different date range"
    And a suggestion to "check 'slack-intel stats' to see available data"
```

## Acceptance Criteria Summary

### Must Have ✅
- [x] Messages partitioned by timestamp date (not cache date)
- [x] View messages by specific date or date range
- [x] Thread reconstruction from flat data
- [x] User mention resolution for conversation participants
- [x] Display reactions, files, JIRA tickets
- [x] Indicate clipped/orphaned threads
- [x] Auto-detect channel naming (ID vs name)
- [x] Save view to file or print to console
- [x] Cache statistics command

### Performance ✅
- [x] Query by date only reads relevant partitions
- [x] Sub-second response for single-day views
- [x] Efficient storage with Parquet compression

### User Experience ✅
- [x] Clear visual markers (💬, 🧵, ↳, 😊, 📎, 🎫)
- [x] Helpful error messages with next steps
- [x] Chronological ordering across partitions
- [x] Thread nesting with proper indentation

### Edge Cases ✅
- [x] Orphaned replies (parent outside window)
- [x] Clipped threads (some replies outside window)
- [x] Missing optional fields (graceful defaults)
- [x] Invalid timestamps (fallback to cache date)
- [x] Empty channels (informative message)
- [x] Unknown user mentions (keep as-is)
