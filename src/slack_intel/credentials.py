"""Centralized credential management for slack-intel

This module provides a hybrid approach to credential loading:
1. Environment variables (highest priority, most secure)
2. Config file credentials (convenience for single-user systems)

Environment variables always take precedence over config file values.
"""

import os
from pathlib import Path
from typing import Optional, Tuple
import yaml


class CredentialError(Exception):
    """Raised when required credentials are missing or invalid"""
    pass


def _load_config_file() -> dict:
    """Load config file from standard locations

    Search order:
    1. ~/.config/slack-intel/config.yaml (XDG standard)
    2. ~/.slack-intel.yaml (legacy support)
    3. ./slack-intel.yaml (project-specific, lowest priority)

    Returns:
        Config dict, or empty dict if no config found
    """
    search_paths = [
        Path.home() / ".config" / "slack-intel" / "config.yaml",
        Path.home() / ".slack-intel.yaml",
        Path.cwd() / "slack-intel.yaml",
    ]

    for config_path in search_paths:
        if config_path.exists():
            try:
                with open(config_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                # If config file is malformed, continue to next location
                print(f"Warning: Could not load config from {config_path}: {e}")
                continue

    return {}


def _get_from_config(key_path: str) -> Optional[str]:
    """Get value from config file using dot-notation path

    Args:
        key_path: Dot-separated path like "credentials.slack.bot_token"

    Returns:
        Value if found, None otherwise
    """
    config = _load_config_file()

    # Navigate nested dict using key_path
    keys = key_path.split('.')
    value = config

    for key in keys:
        if isinstance(value, dict) and key in value:
            value = value[key]
        else:
            return None

    return value if isinstance(value, (str, int, float, bool)) else None


def get_credential(
    env_var: str,
    config_path: str,
    required: bool = False,
    description: str = None
) -> Optional[str]:
    """Generic credential getter with env var + config file support

    Args:
        env_var: Environment variable name (e.g., "SLACK_API_TOKEN")
        config_path: Dot-notation path in config (e.g., "credentials.slack.bot_token")
        required: If True, raise error if credential not found
        description: Human-readable description for error messages

    Returns:
        Credential value if found

    Raises:
        CredentialError: If required=True and credential not found
    """
    # 1. Check environment variable first (highest priority)
    value = os.getenv(env_var)
    if value:
        return value

    # 2. Check config file
    value = _get_from_config(config_path)
    if value:
        return str(value)

    # 3. Not found - raise error if required
    if required:
        desc = description or env_var
        raise CredentialError(
            f"Missing required credential: {desc}\n"
            f"Set environment variable: export {env_var}='your-value'\n"
            f"Or add to config file: ~/.config/slack-intel/config.yaml at '{config_path}'\n"
            f"Run 'slack-intel setup' to configure interactively."
        )

    return None


def get_slack_token() -> str:
    """Get Slack API token (user or bot token)

    Priority order:
    1. SLACK_USER_TOKEN env var (xoxp- OAuth user token)
    2. credentials.slack.user_token in config
    3. SLACK_API_TOKEN env var (xoxb- bot token)
    4. credentials.slack.bot_token in config

    Returns:
        Slack token

    Raises:
        CredentialError: If no Slack token found
    """
    # Try user token first (preferred)
    user_token = get_credential(
        env_var="SLACK_USER_TOKEN",
        config_path="credentials.slack.user_token",
        required=False
    )
    if user_token:
        return user_token

    # Fall back to bot token
    bot_token = get_credential(
        env_var="SLACK_API_TOKEN",
        config_path="credentials.slack.bot_token",
        required=False
    )
    if bot_token:
        return bot_token

    # Neither found - raise error with helpful message
    raise CredentialError(
        "Missing Slack API token\n"
        "Set one of:\n"
        "  - SLACK_USER_TOKEN (xoxp-... OAuth user token, preferred)\n"
        "  - SLACK_API_TOKEN (xoxb-... bot token)\n"
        "Or add to config file ~/.config/slack-intel/config.yaml:\n"
        "  credentials:\n"
        "    slack:\n"
        "      user_token: xoxp-...  # or\n"
        "      bot_token: xoxb-...\n"
        "Run 'slack-intel setup' to configure interactively."
    )


def get_openai_key() -> str:
    """Get OpenAI API key

    Returns:
        OpenAI API key

    Raises:
        CredentialError: If no OpenAI key found
    """
    return get_credential(
        env_var="OPENAI_API_KEY",
        config_path="credentials.openai.api_key",
        required=True,
        description="OpenAI API key"
    )


def get_jira_credentials() -> Tuple[str, str, str]:
    """Get JIRA credentials (username, token, server)

    Returns:
        Tuple of (username, api_token, server_url)

    Raises:
        CredentialError: If any required JIRA credential is missing
    """
    username = get_credential(
        env_var="JIRA_USER_NAME",
        config_path="credentials.jira.username",
        required=True,
        description="JIRA username"
    )

    api_token = get_credential(
        env_var="JIRA_API_TOKEN",
        config_path="credentials.jira.api_token",
        required=True,
        description="JIRA API token"
    )

    # Server can also come from jira.server in config (existing field)
    server = get_credential(
        env_var="JIRA_SERVER",
        config_path="credentials.jira.server",
        required=False
    )

    # Fall back to legacy config location
    if not server:
        server = _get_from_config("jira.server")

    if not server:
        raise CredentialError(
            "Missing JIRA server URL\n"
            "Set environment variable: export JIRA_SERVER='https://your-domain.atlassian.net'\n"
            "Or add to config file at 'credentials.jira.server' or 'jira.server'"
        )

    return username, api_token, server


def get_cache_path() -> Path:
    """Get cache directory path

    Priority order:
    1. SLACK_INTEL_CACHE env var (highest priority)
    2. cache.path in config file
    3. ~/.cache/slack-intel (XDG default)

    Returns:
        Path to cache directory (expanded, absolute)
    """
    # 1. Check environment variable
    env_cache = os.getenv("SLACK_INTEL_CACHE")
    if env_cache:
        return Path(env_cache).expanduser().absolute()

    # 2. Check config file
    config_cache = _get_from_config("cache.path")
    if config_cache:
        return Path(config_cache).expanduser().absolute()

    # 3. XDG default
    xdg_cache = os.getenv("XDG_CACHE_HOME")
    if xdg_cache:
        return Path(xdg_cache).expanduser().absolute() / "slack-intel"

    # Fall back to ~/.cache/slack-intel
    return Path.home() / ".cache" / "slack-intel"


def validate_all_credentials(require_openai: bool = False) -> dict:
    """Validate that all required credentials are available

    Args:
        require_openai: If True, require OpenAI key (for process command)

    Returns:
        Dict of credential names to their sources (env/config/missing)

    Raises:
        CredentialError: If any required credential is missing
    """
    results = {}
    errors = []

    # Check Slack token
    try:
        get_slack_token()
        results['slack'] = 'available'
    except CredentialError as e:
        results['slack'] = 'missing'
        errors.append(str(e))

    # Check JIRA credentials
    try:
        get_jira_credentials()
        results['jira'] = 'available'
    except CredentialError as e:
        results['jira'] = 'missing'
        errors.append(str(e))

    # Check OpenAI (optional unless required)
    if require_openai:
        try:
            get_openai_key()
            results['openai'] = 'available'
        except CredentialError as e:
            results['openai'] = 'missing'
            errors.append(str(e))

    if errors:
        raise CredentialError("\n\n".join(errors))

    return results


def check_config_file_security() -> Optional[str]:
    """Check if config file has secure permissions

    Returns:
        Warning message if insecure, None if secure or no file
    """
    config_path = Path.home() / ".config" / "slack-intel" / "config.yaml"

    if not config_path.exists():
        return None

    # Check file permissions (should be 600 - owner read/write only)
    stat_info = config_path.stat()
    mode = stat_info.st_mode

    # Check if readable by group or others (insecure)
    if mode & 0o077:  # Check group/other permissions
        return (
            f"WARNING: Config file has insecure permissions\n"
            f"File: {config_path}\n"
            f"Current: {oct(mode)[-3:]}\n"
            f"Fix with: chmod 600 {config_path}"
        )

    return None
