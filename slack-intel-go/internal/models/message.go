package models

import "time"

// SlackUser represents a Slack user
type SlackUser struct {
	ID          string `json:"id"`
	Name        string `json:"name,omitempty"`
	RealName    string `json:"real_name,omitempty"`
	DisplayName string `json:"display_name,omitempty"`
	Email       string `json:"email,omitempty"`
	IsBot       bool   `json:"is_bot"`
}

// SlackReaction represents a reaction on a message
type SlackReaction struct {
	Emoji string   `json:"emoji"`
	Count int      `json:"count"`
	Users []string `json:"users"`
}

// SlackFile represents a file attachment
type SlackFile struct {
	ID       string `json:"id"`
	Name     string `json:"name,omitempty"`
	URL      string `json:"url,omitempty"`
	Mimetype string `json:"mimetype,omitempty"`
	Size     int64  `json:"size,omitempty"`
}

// SlackMessage represents a complete Slack message
type SlackMessage struct {
	MessageID   string          `json:"message_id"`
	UserID      string          `json:"user_id,omitempty"`
	Text        string          `json:"text"`
	Timestamp   time.Time       `json:"timestamp"`
	ThreadTS    string          `json:"thread_ts,omitempty"`
	ReplyCount  int             `json:"reply_count"`
	UserInfo    *SlackUser      `json:"user_info,omitempty"`
	Reactions   []SlackReaction `json:"reactions,omitempty"`
	Files       []SlackFile     `json:"files,omitempty"`
	JiraTickets []string        `json:"jira_tickets,omitempty"`
}

// IsThreadParent checks if message is a thread parent
func (m *SlackMessage) IsThreadParent() bool {
	return m.ThreadTS == m.MessageID && m.ReplyCount > 0
}

// IsThreadReply checks if message is a thread reply
func (m *SlackMessage) IsThreadReply() bool {
	return m.ThreadTS != "" && m.ThreadTS != m.MessageID
}

// SlackChannel represents a Slack channel configuration
type SlackChannel struct {
	Name string `json:"name"`
	ID   string `json:"id"`
}

// JiraTicket represents JIRA ticket metadata
type JiraTicket struct {
	TicketID    string            `json:"ticket_id"`
	Summary     string            `json:"summary"`
	Priority    string            `json:"priority"`
	IssueType   string            `json:"issue_type"`
	Status      string            `json:"status"`
	Assignee    string            `json:"assignee"`
	DueDate     string            `json:"due_date,omitempty"`
	StoryPoints int               `json:"story_points,omitempty"`
	Created     string            `json:"created"`
	Updated     string            `json:"updated"`
	Blocks      []string          `json:"blocks,omitempty"`
	BlockedBy   []string          `json:"blocked_by,omitempty"`
	DependsOn   []string          `json:"depends_on,omitempty"`
	Related     []string          `json:"related,omitempty"`
	Components  []string          `json:"components,omitempty"`
	Labels      []string          `json:"labels,omitempty"`
	FixVersions []string          `json:"fix_versions,omitempty"`
	Resolution  string            `json:"resolution,omitempty"`
	Project     string            `json:"project"`
	Team        string            `json:"team,omitempty"`
	EpicLink    string            `json:"epic_link,omitempty"`
	Comments    map[string]int    `json:"comments,omitempty"`
	Sprints     []JiraSprint      `json:"sprints,omitempty"`
	CachedAt    time.Time         `json:"cached_at"`
}

// JiraSprint represents a JIRA sprint
type JiraSprint struct {
	Name  string `json:"name"`
	State string `json:"state"`
}
