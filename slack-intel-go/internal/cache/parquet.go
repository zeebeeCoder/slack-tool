package cache

import (
	"fmt"
	"os"
	"path/filepath"
	"time"

	"github.com/apache/arrow/go/v14/arrow"
	"github.com/apache/arrow/go/v14/arrow/array"
	"github.com/apache/arrow/go/v14/arrow/memory"
	"github.com/apache/arrow/go/v14/parquet"
	"github.com/apache/arrow/go/v14/parquet/compress"
	"github.com/apache/arrow/go/v14/parquet/pqarrow"
	"github.com/zbigniewsiwiec/slack-intel-go/internal/models"
)

// ParquetCache handles writing messages to Parquet files
type ParquetCache struct {
	basePath string
	schema   *arrow.Schema
}

// NewParquetCache creates a new Parquet cache
func NewParquetCache(basePath string) *ParquetCache {
	return &ParquetCache{
		basePath: basePath,
		schema:   createMessageSchema(),
	}
}

// createMessageSchema creates Arrow schema for Slack messages
func createMessageSchema() *arrow.Schema {
	return arrow.NewSchema([]arrow.Field{
		{Name: "message_id", Type: arrow.BinaryTypes.String},
		{Name: "user_id", Type: arrow.BinaryTypes.String, Nullable: true},
		{Name: "text", Type: arrow.BinaryTypes.String},
		{Name: "timestamp", Type: arrow.BinaryTypes.String},
		{Name: "thread_ts", Type: arrow.BinaryTypes.String, Nullable: true},
		{Name: "is_thread_parent", Type: arrow.FixedWidthTypes.Boolean},
		{Name: "is_thread_reply", Type: arrow.FixedWidthTypes.Boolean},
		{Name: "reply_count", Type: arrow.PrimitiveTypes.Int64},
		{Name: "user_name", Type: arrow.BinaryTypes.String, Nullable: true},
		{Name: "user_real_name", Type: arrow.BinaryTypes.String, Nullable: true},
		{Name: "user_email", Type: arrow.BinaryTypes.String, Nullable: true},
		{Name: "user_is_bot", Type: arrow.FixedWidthTypes.Boolean, Nullable: true},
		{Name: "jira_tickets", Type: arrow.ListOf(arrow.BinaryTypes.String)},
		{Name: "has_reactions", Type: arrow.FixedWidthTypes.Boolean},
		{Name: "has_files", Type: arrow.FixedWidthTypes.Boolean},
		{Name: "has_thread", Type: arrow.FixedWidthTypes.Boolean},
	}, nil)
}

// SaveMessages writes messages to a partitioned Parquet file
func (pc *ParquetCache) SaveMessages(messages []*models.SlackMessage, channel *models.SlackChannel, date string) (string, error) {
	if len(messages) == 0 {
		return "", fmt.Errorf("no messages to save")
	}

	// Create partition directory
	partitionDir := filepath.Join(pc.basePath, "messages", fmt.Sprintf("dt=%s", date), fmt.Sprintf("channel=%s", channel.Name))
	if err := os.MkdirAll(partitionDir, 0755); err != nil {
		return "", fmt.Errorf("failed to create partition directory: %w", err)
	}

	filePath := filepath.Join(partitionDir, "data.parquet")

	// Build Arrow record
	mem := memory.NewGoAllocator()
	builder := array.NewRecordBuilder(mem, pc.schema)
	defer builder.Release()

	// Populate columns
	for _, msg := range messages {
		builder.Field(0).(*array.StringBuilder).Append(msg.MessageID)
		if msg.UserID != "" {
			builder.Field(1).(*array.StringBuilder).Append(msg.UserID)
		} else {
			builder.Field(1).(*array.StringBuilder).AppendNull()
		}
		builder.Field(2).(*array.StringBuilder).Append(msg.Text)
		builder.Field(3).(*array.StringBuilder).Append(msg.Timestamp.Format(time.RFC3339))

		if msg.ThreadTS != "" {
			builder.Field(4).(*array.StringBuilder).Append(msg.ThreadTS)
		} else {
			builder.Field(4).(*array.StringBuilder).AppendNull()
		}

		builder.Field(5).(*array.BooleanBuilder).Append(msg.IsThreadParent())
		builder.Field(6).(*array.BooleanBuilder).Append(msg.IsThreadReply())
		builder.Field(7).(*array.Int64Builder).Append(int64(msg.ReplyCount))

		// User fields
		if msg.UserInfo != nil {
			builder.Field(8).(*array.StringBuilder).Append(msg.UserInfo.Name)
			builder.Field(9).(*array.StringBuilder).Append(msg.UserInfo.RealName)
			if msg.UserInfo.Email != "" {
				builder.Field(10).(*array.StringBuilder).Append(msg.UserInfo.Email)
			} else {
				builder.Field(10).(*array.StringBuilder).AppendNull()
			}
			builder.Field(11).(*array.BooleanBuilder).Append(msg.UserInfo.IsBot)
		} else {
			builder.Field(8).(*array.StringBuilder).AppendNull()
			builder.Field(9).(*array.StringBuilder).AppendNull()
			builder.Field(10).(*array.StringBuilder).AppendNull()
			builder.Field(11).(*array.BooleanBuilder).AppendNull()
		}

		// JIRA tickets (list)
		listBuilder := builder.Field(12).(*array.ListBuilder)
		listBuilder.Append(true)
		strBuilder := listBuilder.ValueBuilder().(*array.StringBuilder)
		for _, ticket := range msg.JiraTickets {
			strBuilder.Append(ticket)
		}

		// Boolean flags
		builder.Field(13).(*array.BooleanBuilder).Append(len(msg.Reactions) > 0)
		builder.Field(14).(*array.BooleanBuilder).Append(len(msg.Files) > 0)
		builder.Field(15).(*array.BooleanBuilder).Append(false) // has_thread (for future)
	}

	record := builder.NewRecord()
	defer record.Release()

	// Write to Parquet with Snappy compression
	file, err := os.Create(filePath)
	if err != nil {
		return "", fmt.Errorf("failed to create file: %w", err)
	}
	defer file.Close()

	props := parquet.NewWriterProperties(
		parquet.WithCompression(compress.Codecs.Snappy),
	)

	writer, err := pqarrow.NewFileWriter(pc.schema, file, props, pqarrow.DefaultWriterProps())
	if err != nil {
		return "", fmt.Errorf("failed to create parquet writer: %w", err)
	}
	defer writer.Close()

	if err := writer.Write(record); err != nil {
		return "", fmt.Errorf("failed to write record: %w", err)
	}

	return filePath, nil
}

// SaveUsers writes user cache to a global Parquet file
func (pc *ParquetCache) SaveUsers(users map[string]*models.SlackUser) (string, error) {
	if len(users) == 0 {
		return "", nil
	}

	// Users file at cache/users.parquet
	usersDir := filepath.Dir(pc.basePath)
	usersPath := filepath.Join(usersDir, "users.parquet")

	// Ensure directory exists
	if err := os.MkdirAll(usersDir, 0755); err != nil {
		return "", fmt.Errorf("failed to create users directory: %w", err)
	}

	// Create schema for users
	schema := arrow.NewSchema([]arrow.Field{
		{Name: "user_id", Type: arrow.BinaryTypes.String},
		{Name: "user_name", Type: arrow.BinaryTypes.String, Nullable: true},
		{Name: "user_real_name", Type: arrow.BinaryTypes.String, Nullable: true},
		{Name: "user_email", Type: arrow.BinaryTypes.String, Nullable: true},
		{Name: "is_bot", Type: arrow.FixedWidthTypes.Boolean},
		{Name: "cached_at", Type: arrow.BinaryTypes.String},
	}, nil)

	mem := memory.NewGoAllocator()
	builder := array.NewRecordBuilder(mem, schema)
	defer builder.Release()

	cachedAt := time.Now().Format(time.RFC3339)

	for _, user := range users {
		builder.Field(0).(*array.StringBuilder).Append(user.ID)
		if user.Name != "" {
			builder.Field(1).(*array.StringBuilder).Append(user.Name)
		} else {
			builder.Field(1).(*array.StringBuilder).AppendNull()
		}
		if user.RealName != "" {
			builder.Field(2).(*array.StringBuilder).Append(user.RealName)
		} else {
			builder.Field(2).(*array.StringBuilder).AppendNull()
		}
		if user.Email != "" {
			builder.Field(3).(*array.StringBuilder).Append(user.Email)
		} else {
			builder.Field(3).(*array.StringBuilder).AppendNull()
		}
		builder.Field(4).(*array.BooleanBuilder).Append(user.IsBot)
		builder.Field(5).(*array.StringBuilder).Append(cachedAt)
	}

	record := builder.NewRecord()
	defer record.Release()

	// Write to file
	file, err := os.Create(usersPath)
	if err != nil {
		return "", fmt.Errorf("failed to create users file: %w", err)
	}
	defer file.Close()

	props := parquet.NewWriterProperties(
		parquet.WithCompression(compress.Codecs.Snappy),
	)

	writer, err := pqarrow.NewFileWriter(schema, file, props, pqarrow.DefaultWriterProps())
	if err != nil {
		return "", fmt.Errorf("failed to create parquet writer: %w", err)
	}
	defer writer.Close()

	if err := writer.Write(record); err != nil {
		return "", fmt.Errorf("failed to write record: %w", err)
	}

	return usersPath, nil
}
