package main

import (
	"context"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/charmbracelet/lipgloss"
	"github.com/spf13/cobra"
	"github.com/zbigniewsiwiec/slack-intel-go/internal/cache"
	"github.com/zbigniewsiwiec/slack-intel-go/internal/models"
	"github.com/zbigniewsiwiec/slack-intel-go/internal/slack"
	"github.com/zbigniewsiwiec/slack-intel-go/pkg/config"
)

var (
	// Styles
	titleStyle = lipgloss.NewStyle().
			Bold(true).
			Foreground(lipgloss.Color("39")).
			PaddingTop(1).
			PaddingBottom(1)

	successStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("10"))

	errorStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("9"))

	dimStyle = lipgloss.NewStyle().
			Foreground(lipgloss.Color("240"))
)

func main() {
	rootCmd := &cobra.Command{
		Use:   "slack-intel",
		Short: "Slack Intelligence - High-performance Slack message caching and analysis",
		Long:  `Cache and query Slack messages in Parquet format with blazing speed.`,
	}

	rootCmd.AddCommand(cacheCmd())

	if err := rootCmd.Execute(); err != nil {
		fmt.Fprintf(os.Stderr, "%s\n", errorStyle.Render(fmt.Sprintf("Error: %v", err)))
		os.Exit(1)
	}
}

func cacheCmd() *cobra.Command {
	var (
		channels  []string
		days      int
		hours     int
		cachePath string
		date      string
	)

	cmd := &cobra.Command{
		Use:   "cache",
		Short: "Fetch messages from Slack and save to Parquet cache",
		Long: `Fetch messages from Slack channels and cache them in Parquet format.

Examples:
  # Cache last 7 days from configured channels
  slack-intel cache --days 7

  # Cache specific channel
  slack-intel cache --channel C9876543210 --days 3

  # Cache multiple channels
  slack-intel cache -c C9876543210 -c C1111111111 --days 1`,
		RunE: func(cmd *cobra.Command, args []string) error {
			return runCache(channels, days, hours, cachePath, date)
		},
	}

	cmd.Flags().StringSliceVarP(&channels, "channel", "c", []string{}, "Channel ID(s) to cache (overrides config)")
	cmd.Flags().IntVarP(&days, "days", "d", 2, "Days to look back")
	cmd.Flags().IntVar(&hours, "hours", 0, "Hours to look back")
	cmd.Flags().StringVar(&cachePath, "cache-path", "cache/raw", "Cache directory")
	cmd.Flags().StringVar(&date, "date", "", "Partition date YYYY-MM-DD (default: today)")

	return cmd
}

func runCache(channelIDs []string, days, hours int, cachePath, partitionDate string) error {
	startTime := time.Now()

	// Load config
	cfg, err := config.Load()
	if err != nil {
		return fmt.Errorf("failed to load config: %w", err)
	}

	// Determine channels to process
	var channelsToProcess []models.SlackChannel
	if len(channelIDs) > 0 {
		// Use CLI-provided channels
		for _, id := range channelIDs {
			channelsToProcess = append(channelsToProcess, models.SlackChannel{
				Name: fmt.Sprintf("channel_%s", id),
				ID:   id,
			})
		}
		fmt.Println(dimStyle.Render(fmt.Sprintf("Using %d channel(s) from CLI arguments", len(channelsToProcess))))
	} else {
		// Use config channels
		for _, ch := range cfg.Channels {
			channelsToProcess = append(channelsToProcess, models.SlackChannel{
				Name: ch.Name,
				ID:   ch.ID,
			})
		}
		fmt.Println(dimStyle.Render(fmt.Sprintf("Using %d channel(s) from config", len(channelsToProcess))))
	}

	// Get Slack token
	token, err := config.GetEnv("SLACK_API_TOKEN")
	if err != nil {
		return fmt.Errorf("SLACK_API_TOKEN not set: %w", err)
	}

	// Initialize clients
	slackClient := slack.NewClient(token)
	parquetCache := cache.NewParquetCache(cachePath)

	// Calculate time window
	endTime := time.Now()
	startTimeWindow := endTime.Add(-time.Duration(days)*24*time.Hour - time.Duration(hours)*time.Hour)

	// Use provided date or current date
	dateStr := partitionDate
	if dateStr == "" {
		dateStr = time.Now().Format("2006-01-02")
	}

	// Print header
	fmt.Println(titleStyle.Render("📦 Slack to Parquet Cache (Go)"))
	fmt.Println(dimStyle.Render(fmt.Sprintf("Processing %d channels", len(channelsToProcess))))
	fmt.Println(dimStyle.Render(fmt.Sprintf("Time window: %d days, %d hours", days, hours)))
	fmt.Println(dimStyle.Render(fmt.Sprintf("Cache path: %s", cachePath)))
	fmt.Println()

	ctx := context.Background()
	totalMessages := 0
	totalSize := int64(0)

	// Process each channel
	for _, channel := range channelsToProcess {
		fmt.Printf("📡 Fetching %s...\n", channel.Name)

		messages, err := slackClient.GetMessages(ctx, channel.ID, startTimeWindow, endTime)
		if err != nil {
			fmt.Printf("%s\n", errorStyle.Render(fmt.Sprintf("  ✗ Error: %v", err)))
			continue
		}

		if len(messages) == 0 {
			fmt.Printf("%s\n", dimStyle.Render("  ⚠ No messages found"))
			continue
		}

		// Group messages by date
		messagesByDate := make(map[string][]*models.SlackMessage)
		for _, msg := range messages {
			msgDate := msg.Timestamp.Format("2006-01-02")
			messagesByDate[msgDate] = append(messagesByDate[msgDate], msg)
		}

		// Save messages partitioned by date
		for msgDate, dateMsgs := range messagesByDate {
			filePath, err := parquetCache.SaveMessages(dateMsgs, &channel, msgDate)
			if err != nil {
				fmt.Printf("%s\n", errorStyle.Render(fmt.Sprintf("  ✗ Error saving: %v", err)))
				continue
			}

			// Get file size
			info, _ := os.Stat(filePath)
			totalSize += info.Size()
		}

		totalMessages += len(messages)
		sizeMB := float64(totalSize) / (1024 * 1024)
		fmt.Printf("%s (%d messages, %.2f MB)\n",
			successStyle.Render(fmt.Sprintf("  ✓ Cached %s", channel.Name)),
			len(messages),
			sizeMB)
	}

	// Save user cache
	userCache := slackClient.GetUserCache()
	if len(userCache) > 0 {
		fmt.Printf("\n👥 Caching %d users...\n", len(userCache))
		usersPath, err := parquetCache.SaveUsers(userCache)
		if err != nil {
			fmt.Printf("%s\n", errorStyle.Render(fmt.Sprintf("  ✗ Error saving users: %v", err)))
		} else {
			info, _ := os.Stat(usersPath)
			sizeMB := float64(info.Size()) / (1024 * 1024)
			fmt.Printf("%s (%.2f MB)\n",
				successStyle.Render(fmt.Sprintf("  ✓ Cached users to %s", filepath.Base(usersPath))),
				sizeMB)
		}
	}

	// Summary
	elapsed := time.Since(startTime)
	fmt.Println()
	fmt.Println(titleStyle.Render("✅ Cache Complete"))
	fmt.Printf("Total messages: %d\n", totalMessages)
	fmt.Printf("Total size: %.2f MB\n", float64(totalSize)/(1024*1024))
	fmt.Printf("Time elapsed: %v\n", elapsed.Round(time.Millisecond))
	fmt.Printf("Speed: %.0f messages/sec\n", float64(totalMessages)/elapsed.Seconds())

	return nil
}
