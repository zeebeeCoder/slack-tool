# Git Hooks

This directory contains git hooks for the slack-intel project.

## Installation

To install the hooks, run:

```bash
./hooks/install.sh
```

Or manually:

```bash
cp hooks/pre-commit .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

## Available Hooks

### pre-commit

Runs unit tests before each commit to ensure code quality.

- Executes: `uv run pytest tests/ -v -m "not integration"`
- Skips: Integration tests (which require API access)
- Duration: ~10 seconds

**To bypass the hook (not recommended):**
```bash
git commit --no-verify
```

## Why Git Hooks?

Git hooks ensure:
- ✅ All unit tests pass before committing
- ✅ Code quality is maintained
- ✅ Bugs are caught early
- ✅ CI/CD pipelines don't fail

## Troubleshooting

**Hook not running?**
- Ensure it's executable: `chmod +x .git/hooks/pre-commit`
- Verify it exists: `ls -la .git/hooks/pre-commit`

**Tests taking too long?**
- The hook only runs unit tests (not integration tests)
- If still slow, consider optimizing test fixtures
