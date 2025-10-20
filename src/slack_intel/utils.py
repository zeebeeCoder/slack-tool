"""Utility functions for Slack Intel"""

from typing import List, Dict, Any
from .slack_channels import SlackMessage


def convert_slack_dicts_to_messages(raw_messages: List[Dict[str, Any]]) -> List[SlackMessage]:
    """Convert raw Slack API dicts to SlackMessage objects

    The SlackChannelManager.get_messages() method returns raw dicts from Slack API.
    We need to convert these to SlackMessage objects for ParquetCache.

    Args:
        raw_messages: List of raw message dictionaries from Slack API

    Returns:
        List of SlackMessage objects

    Example:
        >>> manager = SlackChannelManager()
        >>> raw_messages = await manager.get_messages(channel_id, start, end)
        >>> messages = convert_slack_dicts_to_messages(raw_messages)
        >>> cache.save_messages(messages, channel, date)
    """
    slack_messages = []
    for msg_dict in raw_messages:
        # Create SlackMessage from dict - Pydantic will handle validation
        try:
            # Map Slack API field names to SlackMessage field names
            # reply_count (API) → replies_count (model)
            converted_dict = msg_dict.copy()
            if "reply_count" in converted_dict:
                converted_dict["replies_count"] = converted_dict.pop("reply_count")

            slack_msg = SlackMessage(**converted_dict)
            slack_messages.append(slack_msg)
        except Exception as e:
            # Log error but continue processing other messages
            print(f"Warning: Failed to convert message {msg_dict.get('ts', 'unknown')}: {e}")
            continue

    return slack_messages
