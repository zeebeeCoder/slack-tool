#!/bin/bash
# Install git hooks for slack-intel project

echo "📦 Installing git hooks..."

# Copy pre-commit hook
cp hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit

echo "✅ Git hooks installed successfully!"
echo ""
echo "The pre-commit hook will now run unit tests before each commit."
echo "To skip the hook for a specific commit, use: git commit --no-verify"
