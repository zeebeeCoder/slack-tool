.PHONY: build run test clean benchmark

# Build the binary
build:
	cd cmd/slack-intel && go build -o ../../slack-intel

# Run with default args
run: build
	./slack-intel cache --days 2

# Build with optimizations for benchmarking
build-release:
	cd cmd/slack-intel && go build -ldflags="-s -w" -o ../../slack-intel

# Run tests
test:
	go test ./...

# Clean build artifacts
clean:
	rm -f slack-intel
	rm -rf cache/

# Download dependencies
deps:
	go mod download
	go mod tidy

# Format code
fmt:
	go fmt ./...

# Benchmark against Python version
benchmark: build-release
	@echo "Running Go version..."
	@time ./slack-intel cache --days 2 --cache-path cache/go
	@echo "\nRunning Python version..."
	@cd .. && time uv run slack-intel cache --days 2 --cache-path cache/raw
	@echo "\nComparing sizes..."
	@du -sh cache/go cache/raw

# Install locally
install: build-release
	cp slack-intel ~/bin/slack-intel-go
