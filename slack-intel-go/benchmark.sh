#!/bin/bash
set -e

echo "======================================"
echo "Slack Intel: Go vs Python Benchmark"
echo "======================================"
echo ""

# Clean cache directories
echo "🧹 Cleaning cache directories..."
rm -rf cache/go cache/py
mkdir -p cache/go cache/py

# Test parameters
DAYS=2
CHANNEL="${1:-C05713KTQF9}"  # Use first arg or default channel

echo "📊 Benchmark Parameters:"
echo "  Days to cache: $DAYS"
echo "  Channel: $CHANNEL"
echo ""

# Go version
echo "======================================"
echo "🚀 Running Go version..."
echo "======================================"
time ./slack-intel cache --channel "$CHANNEL" --days "$DAYS" --cache-path cache/go
GO_EXIT=$?
echo ""

# Python version
echo "======================================"
echo "🐍 Running Python version..."
echo "======================================"
cd ..
time uv run slack-intel cache --channel "$CHANNEL" --days "$DAYS" --cache-path slack-intel-go/cache/py
PY_EXIT=$?
cd slack-intel-go
echo ""

# Compare results
echo "======================================"
echo "📈 Results Comparison"
echo "======================================"
echo ""

if [ $GO_EXIT -eq 0 ] && [ $PY_EXIT -eq 0 ]; then
    echo "✅ Both versions completed successfully"
    echo ""

    echo "📁 Cache sizes:"
    GO_SIZE=$(du -sh cache/go 2>/dev/null | cut -f1)
    PY_SIZE=$(du -sh cache/py 2>/dev/null | cut -f1)
    echo "  Go:     $GO_SIZE"
    echo "  Python: $PY_SIZE"
    echo ""

    echo "📊 File counts:"
    GO_FILES=$(find cache/go -name "*.parquet" | wc -l | tr -d ' ')
    PY_FILES=$(find cache/py -name "*.parquet" | wc -l | tr -d ' ')
    echo "  Go:     $GO_FILES Parquet files"
    echo "  Python: $PY_FILES Parquet files"
    echo ""

    echo "🔍 Binary sizes:"
    echo "  Go binary:     $(ls -lh slack-intel | awk '{print $5}')"
    echo "  Python (venv): ~50-80MB (estimated)"
else
    echo "❌ One or both versions failed"
    echo "  Go exit code:     $GO_EXIT"
    echo "  Python exit code: $PY_EXIT"
fi

echo ""
echo "======================================"
echo "💡 To test with different channel:"
echo "  ./benchmark.sh C9876543210"
echo "======================================"
