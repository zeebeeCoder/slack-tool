package slack

import (
	"context"
	"fmt"
	"log"
	"regexp"
	"sync"
	"time"

	"github.com/slack-go/slack"
	"github.com/zbigniewsiwiec/slack-intel-go/internal/models"
	"golang.org/x/time/rate"
)

// Client wraps Slack API with rate limiting and caching
type Client struct {
	api        *slack.Client
	rateLimiter *rate.Limiter
	userCache  map[string]*models.SlackUser
	userMu     sync.RWMutex
}

// NewClient creates a new Slack client with rate limiting
func NewClient(token string) *Client {
	// Slack API rate limit: ~1 request per second per method
	// Set to 20 requests/second with burst of 50 for safety
	limiter := rate.NewLimiter(20, 50)

	return &Client{
		api:         slack.New(token),
		rateLimiter: limiter,
		userCache:   make(map[string]*models.SlackUser),
	}
}

// GetMessages fetches messages from a channel within a time window
func (c *Client) GetMessages(ctx context.Context, channelID string, startTime, endTime time.Time) ([]*models.SlackMessage, error) {
	// Wait for rate limiter
	if err := c.rateLimiter.Wait(ctx); err != nil {
		return nil, fmt.Errorf("rate limiter: %w", err)
	}

	log.Printf("Fetching messages for channel %s from %s to %s", channelID, startTime.Format(time.RFC3339), endTime.Format(time.RFC3339))

	params := slack.GetConversationHistoryParameters{
		ChannelID: channelID,
		Oldest:    fmt.Sprintf("%d.%06d", startTime.Unix(), startTime.Nanosecond()/1000),
		Latest:    fmt.Sprintf("%d.%06d", endTime.Unix(), endTime.Nanosecond()/1000),
		Limit:     1000,
	}

	history, err := c.api.GetConversationHistoryContext(ctx, &params)
	if err != nil {
		return nil, fmt.Errorf("failed to get conversation history: %w", err)
	}

	messages := make([]*models.SlackMessage, 0, len(history.Messages))
	userIDs := make(map[string]bool)

	// First pass: collect user IDs
	for _, msg := range history.Messages {
		if msg.User != "" {
			userIDs[msg.User] = true
		}
	}

	// Fetch user info in parallel (with concurrency limit)
	if err := c.fetchUsersParallel(ctx, userIDs); err != nil {
		log.Printf("Warning: failed to fetch some users: %v", err)
	}

	// Second pass: convert messages and enrich with user info
	for _, msg := range history.Messages {
		message := c.convertMessage(&msg)
		messages = append(messages, message)
	}

	// Fetch thread replies for thread parents
	threadMessages, err := c.fetchThreadReplies(ctx, channelID, messages)
	if err != nil {
		log.Printf("Warning: failed to fetch some thread replies: %v", err)
	}

	// Merge thread replies with main messages
	allMessages := append(messages, threadMessages...)

	log.Printf("Fetched %d total messages (%d timeline, %d thread replies)",
		len(allMessages), len(messages), len(threadMessages))

	return allMessages, nil
}

// fetchThreadReplies fetches all replies for thread parent messages
func (c *Client) fetchThreadReplies(ctx context.Context, channelID string, messages []*models.SlackMessage) ([]*models.SlackMessage, error) {
	var threadReplies []*models.SlackMessage
	var mu sync.Mutex
	var wg sync.WaitGroup

	// Limit concurrent thread fetches
	sem := make(chan struct{}, 10)

	for _, msg := range messages {
		if msg.IsThreadParent() {
			wg.Add(1)
			go func(threadTS string) {
				defer wg.Done()
				sem <- struct{}{}        // Acquire
				defer func() { <-sem }() // Release

				replies, err := c.getThreadReplies(ctx, channelID, threadTS)
				if err != nil {
					log.Printf("Warning: failed to fetch thread %s: %v", threadTS, err)
					return
				}

				mu.Lock()
				threadReplies = append(threadReplies, replies...)
				mu.Unlock()
			}(msg.ThreadTS)
		}
	}

	wg.Wait()
	return threadReplies, nil
}

// getThreadReplies fetches replies for a single thread
func (c *Client) getThreadReplies(ctx context.Context, channelID, threadTS string) ([]*models.SlackMessage, error) {
	if err := c.rateLimiter.Wait(ctx); err != nil {
		return nil, err
	}

	params := slack.GetConversationRepliesParameters{
		ChannelID: channelID,
		Timestamp: threadTS,
		Limit:     1000,
	}

	msgs, _, _, err := c.api.GetConversationRepliesContext(ctx, &params)
	if err != nil {
		return nil, err
	}

	// Skip first message (parent) and convert replies
	replies := make([]*models.SlackMessage, 0, len(msgs)-1)
	for i, msg := range msgs {
		if i == 0 {
			continue // Skip parent
		}
		replies = append(replies, c.convertMessage(&msg))
	}

	return replies, nil
}

// fetchUsersParallel fetches multiple users in parallel with rate limiting
func (c *Client) fetchUsersParallel(ctx context.Context, userIDs map[string]bool) error {
	var wg sync.WaitGroup
	sem := make(chan struct{}, 10) // Limit to 10 concurrent requests

	for userID := range userIDs {
		// Skip if already cached
		c.userMu.RLock()
		_, exists := c.userCache[userID]
		c.userMu.RUnlock()
		if exists {
			continue
		}

		wg.Add(1)
		go func(uid string) {
			defer wg.Done()
			sem <- struct{}{}        // Acquire
			defer func() { <-sem }() // Release

			if err := c.fetchUserInfo(ctx, uid); err != nil {
				log.Printf("Warning: failed to fetch user %s: %v", uid, err)
			}
		}(userID)
	}

	wg.Wait()
	return nil
}

// fetchUserInfo fetches and caches a single user's info
func (c *Client) fetchUserInfo(ctx context.Context, userID string) error {
	if err := c.rateLimiter.Wait(ctx); err != nil {
		return err
	}

	user, err := c.api.GetUserInfoContext(ctx, userID)
	if err != nil {
		return err
	}

	slackUser := &models.SlackUser{
		ID:          user.ID,
		Name:        user.Name,
		RealName:    user.RealName,
		DisplayName: user.Profile.DisplayName,
		Email:       user.Profile.Email,
		IsBot:       user.IsBot,
	}

	c.userMu.Lock()
	c.userCache[userID] = slackUser
	c.userMu.Unlock()

	return nil
}

// GetUserInfo retrieves cached user info
func (c *Client) GetUserInfo(userID string) *models.SlackUser {
	c.userMu.RLock()
	defer c.userMu.RUnlock()
	return c.userCache[userID]
}

// GetUserCache returns all cached users
func (c *Client) GetUserCache() map[string]*models.SlackUser {
	c.userMu.RLock()
	defer c.userMu.RUnlock()

	// Return a copy to avoid concurrent map access
	cache := make(map[string]*models.SlackUser, len(c.userCache))
	for k, v := range c.userCache {
		cache[k] = v
	}
	return cache
}

// convertMessage converts slack.Message to models.SlackMessage
func (c *Client) convertMessage(msg *slack.Message) *models.SlackMessage {
	ts, _ := parseSlackTimestamp(msg.Timestamp)

	message := &models.SlackMessage{
		MessageID:  msg.Timestamp,
		UserID:     msg.User,
		Text:       msg.Text,
		Timestamp:  ts,
		ThreadTS:   msg.ThreadTimestamp,
		ReplyCount: msg.ReplyCount,
	}

	// Attach cached user info
	if msg.User != "" {
		message.UserInfo = c.GetUserInfo(msg.User)
	}

	// Convert reactions
	for _, r := range msg.Reactions {
		message.Reactions = append(message.Reactions, models.SlackReaction{
			Emoji: r.Name,
			Count: r.Count,
			Users: r.Users,
		})
	}

	// Convert files
	for _, f := range msg.Files {
		message.Files = append(message.Files, models.SlackFile{
			ID:       f.ID,
			Name:     f.Name,
			URL:      f.URLPrivate,
			Mimetype: f.Mimetype,
			Size:     int64(f.Size),
		})
	}

	// Extract JIRA tickets
	message.JiraTickets = extractJiraTickets(msg.Text)

	return message
}

// parseSlackTimestamp converts Slack timestamp string to time.Time
func parseSlackTimestamp(ts string) (time.Time, error) {
	var sec, nsec int64
	_, err := fmt.Sscanf(ts, "%d.%d", &sec, &nsec)
	if err != nil {
		return time.Time{}, err
	}
	return time.Unix(sec, nsec), nil
}

// extractJiraTickets extracts JIRA ticket IDs from text
func extractJiraTickets(text string) []string {
	re := regexp.MustCompile(`\b[A-Z]+-\d+\b`)
	matches := re.FindAllString(text, -1)

	// Deduplicate
	seen := make(map[string]bool)
	var tickets []string
	for _, match := range matches {
		if !seen[match] {
			tickets = append(tickets, match)
			seen[match] = true
		}
	}

	return tickets
}
