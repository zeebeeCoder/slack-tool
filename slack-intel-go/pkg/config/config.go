package config

import (
	"fmt"
	"os"
	"path/filepath"

	"gopkg.in/yaml.v3"
)

// Config represents the .slack-intel.yaml configuration
type Config struct {
	Channels []ChannelConfig `yaml:"channels"`
	Storage  StorageConfig   `yaml:"storage,omitempty"`
	Jira     JiraConfig      `yaml:"jira,omitempty"`
}

// ChannelConfig represents a channel configuration
type ChannelConfig struct {
	Name string `yaml:"name"`
	ID   string `yaml:"id"`
}

// StorageConfig represents S3 storage configuration
type StorageConfig struct {
	Bucket  string `yaml:"bucket,omitempty"`
	Prefix  string `yaml:"prefix,omitempty"`
	Region  string `yaml:"region,omitempty"`
	Profile string `yaml:"profile,omitempty"`
}

// JiraConfig represents JIRA configuration
type JiraConfig struct {
	Server string `yaml:"server,omitempty"`
}

// Load reads configuration from .slack-intel.yaml
// Looks in current directory first, then home directory
func Load() (*Config, error) {
	configPaths := []string{
		".slack-intel.yaml",
		filepath.Join(os.Getenv("HOME"), ".slack-intel.yaml"),
	}

	for _, path := range configPaths {
		if _, err := os.Stat(path); err == nil {
			data, err := os.ReadFile(path)
			if err != nil {
				continue
			}

			var cfg Config
			if err := yaml.Unmarshal(data, &cfg); err != nil {
				return nil, fmt.Errorf("failed to parse %s: %w", path, err)
			}

			return &cfg, nil
		}
	}

	// Return default config if no file found
	return &Config{
		Channels: []ChannelConfig{
			{Name: "general", ID: "C0123456789"},
		},
	}, nil
}

// GetEnv reads required environment variables
func GetEnv(key string) (string, error) {
	value := os.Getenv(key)
	if value == "" {
		return "", fmt.Errorf("%s not set in environment", key)
	}
	return value, nil
}
