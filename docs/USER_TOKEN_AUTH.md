# Feature Requirement: User Token Authentication

## Overview

Add support for Slack User Token (OAuth) authentication as an alternative to Bot Token authentication, enabling automatic access to all channels and DMs visible to the authenticated user.

## Problem Statement

**Current State (Bot Token):**
- Requires bot to be manually added to each channel
- Cannot access user's DMs
- High maintenance overhead for large workspaces
- No access to private channels unless explicitly invited

**Desired State (User Token):**
- One-time OAuth authorization
- Automatic access to all channels user can see
- Access to user's DMs
- Access to private channels user is member of
- Zero maintenance for channel access

## Goals

1. Enable OAuth-based user token generation
2. Support both bot and user token authentication modes
3. Maintain backward compatibility with existing bot token workflows
4. Provide clear documentation for both authentication methods

## Non-Goals

- Removing bot token support (both should coexist)
- Implementing token refresh logic (v1 will use long-lived tokens)
- Multi-user OAuth (v1 focuses on single-user/personal use)

## User Stories

### US-1: Generate User Token via OAuth
**As a** developer
**I want to** generate a user token through OAuth flow
**So that** I can access all my Slack channels without adding a bot

**Acceptance Criteria:**
- User can initiate OAuth flow from CLI
- OAuth URL is generated with correct scopes
- User receives `xoxp-` token after authorization
- Token is saved to `.env` file or displayed for manual saving

### US-2: Use User Token for Message Fetching
**As a** user
**I want to** use my user token to cache messages
**So that** I can access all channels I'm a member of automatically

**Acceptance Criteria:**
- Existing `slack-intel cache` command works with user tokens
- No changes needed to message fetching logic
- User and bot tokens work interchangeably

### US-3: Clear Documentation on Token Types
**As a** new user
**I want to** understand the difference between bot and user tokens
**So that** I can choose the right authentication method

**Acceptance Criteria:**
- README explains both token types
- Trade-offs are clearly documented
- Step-by-step OAuth setup guide provided

## Technical Requirements

### Authentication Modes

The tool should support two modes:

```bash
# Mode 1: Bot Token (existing)
SLACK_API_TOKEN=xoxb-...

# Mode 2: User Token (new)
SLACK_API_TOKEN=xoxp-...
```

### Required Slack App Configuration

**User Token Scopes:**
- `channels:history` - Read messages from public channels
- `channels:read` - List public channels
- `groups:history` - Read messages from private channels
- `groups:read` - List private channels
- `im:history` - Read DM messages
- `im:read` - List DMs
- `mpim:history` - Read group DM messages
- `mpim:read` - List group DMs
- `users:read` - Read user information
- `users:read.email` - Read user email addresses

### Implementation Components

#### 1. OAuth Flow Handler (New)

```python
# src/slack_intel/oauth.py

class SlackOAuthHandler:
    """Handles OAuth flow for user token generation"""

    def generate_auth_url(self) -> str:
        """Generate OAuth authorization URL"""
        pass

    def exchange_code_for_token(self, code: str) -> str:
        """Exchange OAuth code for user token"""
        pass

    def save_token(self, token: str) -> None:
        """Save token to .env file"""
        pass
```

#### 2. CLI Command (New)

```bash
# Start OAuth flow
slack-intel auth --oauth

# Output:
# 1. Visit this URL: https://slack.com/oauth/v2/authorize?...
# 2. Click "Allow"
# 3. Copy the code from redirect URL
# 4. Run: slack-intel auth --code YOUR_CODE
```

#### 3. Token Detection (Enhancement)

Update `slack_channels.py` to detect token type and log it:

```python
def detect_token_type(token: str) -> str:
    """Detect if token is bot or user token"""
    if token.startswith("xoxb-"):
        return "bot"
    elif token.startswith("xoxp-"):
        return "user"
    else:
        return "unknown"
```

### Configuration

Add to `.env.example`:

```bash
# Authentication Method
# Option 1: Bot Token (requires bot added to each channel)
SLACK_API_TOKEN=xoxb-your-bot-token

# Option 2: User Token (accesses all your channels via OAuth)
# SLACK_API_TOKEN=xoxp-your-user-token

# OAuth Credentials (only needed for user token generation)
# Get from: https://api.slack.com/apps → Your App → Basic Information
# SLACK_CLIENT_ID=your-client-id
# SLACK_CLIENT_SECRET=your-client-secret
```

## Implementation Phases

### Phase 1: OAuth Flow Setup (Minimal)
- Document manual OAuth process
- Add token type detection and logging
- Update README with instructions
- **Effort:** 2-3 hours

### Phase 2: Spike Validation & Documentation (COMPLETE)
**Status:** ✅ Implemented
**Changes:**
- Added `_get_slack_token()` feature toggle method in `slack_channels.py:480`
- Added `_detect_token_type()` for token identification and logging in `slack_channels.py:507`
- Updated `.env.example` with comprehensive user token documentation
- Created spike validation template (`docs/SPIKE_USER_TOKEN.md`)
- Updated this requirements doc with implementation status
- Maintains 100% backward compatibility (bot tokens still work)

**How to Use:**
```bash
# 1. Configure Slack App with User Token Scopes (see spike doc)
# 2. Install app to workspace and copy xoxp- token
# 3. Add to .env
echo "SLACK_USER_TOKEN=xoxp-your-token" >> .env

# 4. Run any command
uv run slack-intel cache --channel C05713KTQF9 --days 3

# 5. Verify in logs: "Using USER token (xoxp-) - OAuth mode enabled"
```

**Testing:**
See `docs/SPIKE_USER_TOKEN.md` for complete test plan with 6 validation tests.

### Phase 3: CLI OAuth Helper (Future)
- Implement `slack-intel auth --oauth` command
- Auto-generate OAuth URL
- Handle code exchange
- Save token to `.env`
- **Effort:** 4-6 hours

### Phase 4: Token Refresh (Future)
- Implement refresh token logic
- Auto-refresh expired tokens
- **Effort:** 6-8 hours

## Testing Strategy

### Manual Testing
- [ ] Generate user token via OAuth
- [ ] Cache messages using user token
- [ ] Verify access to private channels
- [ ] Verify access to DMs
- [ ] Compare channel list between bot and user tokens

### Integration Tests
```python
def test_user_token_authentication():
    """Test that user tokens work for message fetching"""

def test_bot_token_backward_compatibility():
    """Ensure existing bot token workflows still work"""

def test_token_type_detection():
    """Test detection of xoxb vs xoxp tokens"""
```

## Security Considerations

1. **Token Storage:**
   - User tokens are more powerful than bot tokens
   - Must be stored securely in `.env` (gitignored)
   - Never commit tokens to version control

2. **Scope Minimization:**
   - Only request necessary OAuth scopes
   - Document why each scope is needed

3. **Token Expiration:**
   - User tokens can expire/be revoked
   - Provide clear error messages when token is invalid
   - (Future) Implement refresh token logic

## Success Metrics

- [ ] User can generate user token in < 5 minutes
- [ ] User token provides access to 100% of user's visible channels
- [ ] Zero reported issues with backward compatibility
- [ ] Documentation covers all common questions

## Open Questions

1. **Token refresh:** Should Phase 1 include refresh token logic, or defer to Phase 3?
   - **Decision:** Defer to Phase 3 (keep Phase 1 simple)

2. **Multi-workspace:** Should we support OAuth for multiple workspaces?
   - **Decision:** Not in v1 (single workspace focus)

3. **OAuth redirect:** Where should OAuth redirect after authorization?
   - **Options:**
     a. Localhost server (requires user to run local server)
     b. Copy code manually from URL
     c. Cloud redirect endpoint
   - **Decision:** Option B for Phase 1 (simplest, no server needed)

4. **Error handling:** How to handle expired user tokens?
   - **Decision:** Clear error message pointing to re-auth command

## Documentation Updates

- [ ] Update README with user token section
- [ ] Add OAUTH_SETUP.md guide
- [ ] Update .env.example
- [ ] Add troubleshooting section for token issues

## References

- [Slack OAuth Documentation](https://api.slack.com/authentication/oauth-v2)
- [User Token Scopes](https://api.slack.com/scopes)
- [slack_sdk OAuth Guide](https://slack.dev/python-slack-sdk/oauth/)

## Revision History

| Date | Version | Changes |
|------|---------|---------|
| 2025-10-27 | 1.0 | Initial draft |
