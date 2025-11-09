"""Configuration management for Slack Intelligence

Loads and validates organizational context, channel descriptions,
and stakeholder maps from .slack-intel.yaml
"""

from typing import List, Dict, Any, Optional
from pathlib import Path
from dataclasses import dataclass, field
import yaml


@dataclass
class Stakeholder:
    """Organizational stakeholder for attention ranking (simplified)"""
    name: str
    weight: int = 5  # 1-10, higher = more attention gravity
    role: str = ""  # Optional - job title for display
    description: str = ""  # Optional - who does what, focus areas


@dataclass
class Organization:
    """Organization-wide context"""
    name: str = "Organization"
    description: str = ""
    stakeholders: List[Stakeholder] = field(default_factory=list)

    # Optional freeform context that can be used instead of structured stakeholders
    stakeholder_context: str = ""

    def get_stakeholder_by_name(self, name: str) -> Optional[Stakeholder]:
        """Find stakeholder by name (case-insensitive)"""
        name_lower = name.lower()
        for stakeholder in self.stakeholders:
            if stakeholder.name.lower() == name_lower:
                return stakeholder
        return None

    def get_stakeholder_weight(self, name: str) -> int:
        """Get attention weight for a stakeholder (0 if not found)"""
        stakeholder = self.get_stakeholder_by_name(name)
        return stakeholder.weight if stakeholder else 0


@dataclass
class ChannelConfig:
    """Enhanced channel configuration (simplified)"""
    name: str
    id: str
    description: str = ""  # Single description field (combines purpose + context)
    signal_type: str = "medium"  # critical/high/medium/low
    tags: List[str] = field(default_factory=list)  # Optional

    @property
    def signal_weight(self) -> int:
        """Convert signal_type to numeric weight"""
        weights = {
            "critical": 10,
            "high": 8,
            "medium": 5,
            "low": 2
        }
        return weights.get(self.signal_type, 5)


@dataclass
class TemporalConfig:
    """Temporal analysis configuration"""
    current_window_days: int = 7
    comparison_window_days: int = 21
    persistence_threshold_days: int = 28


@dataclass
class AnalysisThresholds:
    """Thresholds for attention signal detection"""
    high_velocity_hours: int = 4
    thread_depth_significant: int = 5
    participant_diversity: int = 3
    context_switch_rate: int = 5


@dataclass
class AnalysisConfig:
    """Analysis configuration"""
    temporal: TemporalConfig = field(default_factory=TemporalConfig)
    thresholds: AnalysisThresholds = field(default_factory=AnalysisThresholds)


@dataclass
class SlackIntelConfig:
    """Complete Slack Intelligence configuration"""
    organization: Organization = field(default_factory=Organization)
    channels: List[ChannelConfig] = field(default_factory=list)
    analysis: AnalysisConfig = field(default_factory=AnalysisConfig)
    storage: Dict[str, Any] = field(default_factory=dict)
    jira: Dict[str, Any] = field(default_factory=dict)

    def get_channel_by_name(self, name: str) -> Optional[ChannelConfig]:
        """Find channel config by name"""
        for channel in self.channels:
            if channel.name == name or channel.name == f"channel_{name}":
                return channel
        # Try without prefix
        name_stripped = name.replace("channel_", "")
        for channel in self.channels:
            if channel.name == name_stripped:
                return channel
        return None


def load_config(config_path: Optional[Path] = None) -> SlackIntelConfig:
    """Load enhanced configuration from YAML file

    Args:
        config_path: Optional path to config file. If None, searches default locations.

    Returns:
        SlackIntelConfig with organization context, channels, and analysis settings
    """
    if config_path:
        config_paths = [config_path]
    else:
        config_paths = [
            Path(".slack-intel.yaml"),
            Path.home() / ".slack-intel.yaml",
        ]

    for path in config_paths:
        if path.exists():
            try:
                with open(path) as f:
                    raw_config = yaml.safe_load(f)
                    if raw_config:
                        return _parse_config(raw_config, path)
            except Exception as e:
                print(f"Warning: Failed to load {path}: {e}")
                continue

    # Return minimal default config
    return SlackIntelConfig(
        channels=[
            ChannelConfig(name="general", id="C1234567890", description="Default channel"),
            ChannelConfig(name="engineering", id="C9876543210", description="Engineering channel"),
        ]
    )


def _parse_config(raw: Dict[str, Any], source_path: Path) -> SlackIntelConfig:
    """Parse raw YAML into structured config"""

    # Parse organization
    org_data = raw.get("organization", {})
    stakeholders = []
    for s in org_data.get("stakeholders", []):
        stakeholders.append(Stakeholder(
            name=s.get("name", ""),
            weight=s.get("weight", 5),
            role=s.get("role", ""),  # Optional
            description=s.get("description", "")  # Optional
        ))

    organization = Organization(
        name=org_data.get("name", "Organization"),
        description=org_data.get("description", ""),
        stakeholders=stakeholders,
        stakeholder_context=org_data.get("stakeholder_context", "")
    )

    # Parse channels
    channels = []
    for ch in raw.get("channels", []):
        # Support both old format (description + purpose) and new (just description)
        description = ch.get("description", "")
        purpose = ch.get("purpose", "")
        if purpose and purpose not in description:
            description = f"{description}. {purpose}".strip()

        channels.append(ChannelConfig(
            name=ch.get("name", ""),
            id=ch.get("id", ""),
            description=description,
            signal_type=ch.get("signal_type", "medium"),
            tags=ch.get("tags", [])
        ))

    # Parse analysis config
    analysis_data = raw.get("analysis", {})
    temporal_data = analysis_data.get("temporal", {})
    thresholds_data = analysis_data.get("thresholds", {})

    temporal = TemporalConfig(
        current_window_days=temporal_data.get("current_window_days", 7),
        comparison_window_days=temporal_data.get("comparison_window_days", 21),
        persistence_threshold_days=temporal_data.get("persistence_threshold_days", 28)
    )

    thresholds = AnalysisThresholds(
        high_velocity_hours=thresholds_data.get("high_velocity_hours", 4),
        thread_depth_significant=thresholds_data.get("thread_depth_significant", 5),
        participant_diversity=thresholds_data.get("participant_diversity", 3),
        context_switch_rate=thresholds_data.get("context_switch_rate", 5)
    )

    analysis = AnalysisConfig(temporal=temporal, thresholds=thresholds)

    print(f"[dim]Loaded enhanced config from {source_path}[/dim]")

    return SlackIntelConfig(
        organization=organization,
        channels=channels,
        analysis=analysis,
        storage=raw.get("storage", {}),
        jira=raw.get("jira", {})
    )


def get_channel_list_for_legacy_code(config: SlackIntelConfig) -> List[dict]:
    """Convert to legacy format for backward compatibility

    Returns list of {"name": str, "id": str} dicts
    """
    return [
        {"name": ch.name, "id": ch.id}
        for ch in config.channels
    ]


def _config_to_yaml(config: SlackIntelConfig) -> str:
    """Convert SlackIntelConfig back to YAML string

    Args:
        config: Config object to serialize

    Returns:
        YAML string
    """
    # Build dict representation
    config_dict = {}

    # Organization
    org_dict = {
        "name": config.organization.name,
        "description": config.organization.description,
        "stakeholders": []
    }

    for s in config.organization.stakeholders:
        stakeholder_dict = {
            "name": s.name,
            "weight": s.weight,
            "role": s.role,  # Always include, even if empty
            "description": s.description  # Always include, even if empty
        }
        org_dict["stakeholders"].append(stakeholder_dict)

    if config.organization.stakeholder_context:
        org_dict["stakeholder_context"] = config.organization.stakeholder_context

    config_dict["organization"] = org_dict

    # Channels
    config_dict["channels"] = []
    for ch in config.channels:
        ch_dict = {
            "name": ch.name,
            "id": ch.id,
            "description": ch.description,
            "signal_type": ch.signal_type
        }
        if ch.tags:
            ch_dict["tags"] = ch.tags
        config_dict["channels"].append(ch_dict)

    # Analysis (if not defaults)
    if config.analysis:
        analysis_dict = {}

        # Temporal
        temporal = config.analysis.temporal
        if (temporal.current_window_days != 7 or
            temporal.comparison_window_days != 21 or
            temporal.persistence_threshold_days != 28):
            analysis_dict["temporal"] = {
                "current_window_days": temporal.current_window_days,
                "comparison_window_days": temporal.comparison_window_days,
                "persistence_threshold_days": temporal.persistence_threshold_days
            }

        # Thresholds
        thresholds = config.analysis.thresholds
        if (thresholds.high_velocity_hours != 4 or
            thresholds.thread_depth_significant != 5 or
            thresholds.participant_diversity != 3 or
            thresholds.context_switch_rate != 5):
            analysis_dict["thresholds"] = {
                "high_velocity_hours": thresholds.high_velocity_hours,
                "thread_depth_significant": thresholds.thread_depth_significant,
                "participant_diversity": thresholds.participant_diversity,
                "context_switch_rate": thresholds.context_switch_rate
            }

        if analysis_dict:
            config_dict["analysis"] = analysis_dict

    # Storage/JIRA (if present)
    if config.storage:
        config_dict["storage"] = config.storage
    if config.jira:
        config_dict["jira"] = config.jira

    return yaml.dump(config_dict, default_flow_style=False, sort_keys=False, allow_unicode=True)


def sync_users_to_config(
    existing_config: SlackIntelConfig,
    cached_users: Dict[str, Dict[str, Any]],
    output_path: Optional[Path] = None
) -> tuple[SlackIntelConfig, List[str]]:
    """Merge new users from cache into existing config

    Args:
        existing_config: Current SlackIntelConfig
        cached_users: Dict of user_id -> user_data from cache
        output_path: Optional path to write updated config

    Returns:
        Tuple of (updated_config, list_of_new_user_names)
    """
    # Build set of existing stakeholder names (case-insensitive)
    existing_names = {s.name.lower() for s in existing_config.organization.stakeholders}

    # Find new users not in config
    new_stakeholders = []
    for user_id, user_data in cached_users.items():
        user_name = user_data.get("user_real_name") or user_data.get("user_name") or "Unknown"

        if user_name.lower() not in existing_names:
            new_stakeholders.append(Stakeholder(
                name=user_name,
                weight=5,  # Default weight
                role="",
                description=""  # User fills this in
            ))

    # Add new stakeholders to existing list
    updated_stakeholders = existing_config.organization.stakeholders + new_stakeholders

    # Sort alphabetically
    updated_stakeholders.sort(key=lambda s: s.name.lower())

    # Create updated config
    existing_config.organization.stakeholders = updated_stakeholders

    # Write to file if path provided
    if output_path:
        yaml_content = _config_to_yaml(existing_config)
        output_path.write_text(yaml_content)

    new_user_names = [s.name for s in new_stakeholders]
    return existing_config, new_user_names


def generate_initial_config(
    users: Dict[str, Dict[str, Any]],
    channels: List[dict],
    org_name: str = "My Organization",
    output_path: Optional[Path] = None
) -> str:
    """Generate initial config YAML from cached users and channels (first-time setup)

    Args:
        users: Dict of user_id -> user_data from cache
        channels: List of {"name": str, "id": str} channel dicts
        org_name: Organization name
        output_path: Optional path to write config file

    Returns:
        Generated YAML content as string
    """
    # Sort users by message count or alphabetically
    user_list = []
    for user_id, user_data in users.items():
        user_name = user_data.get("user_real_name") or user_data.get("user_name") or "Unknown"
        user_list.append({
            "name": user_name,
            "id": user_id,
        })

    # Sort alphabetically
    user_list.sort(key=lambda x: x["name"])

    # Build YAML content
    lines = [
        "# Slack Intelligence Configuration",
        "# Generated automatically - customize as needed",
        "",
        "# Organization Context",
        "organization:",
        f"  name: \"{org_name}\"",
        "  description: \"Add your organization description here\"",
        "",
        "  # Stakeholders - Edit weights for key people (1-10, higher = more attention)",
        "  # 10 = CEO/Founder, 8-9 = Leadership, 7 = Directors, 5 = Default",
        "  stakeholders:",
    ]

    # Add all users with default weight 5
    for user in user_list[:50]:  # Limit to 50 users
        lines.append(f"    - name: \"{user['name']}\"")
        lines.append(f"      weight: 5  # Edit: Set 7-10 for leaders, 1-4 for low attention")
        lines.append(f"      role: \"\"  # Optional: Job title")
        lines.append(f"      description: \"\"  # Optional: Who does what, focus areas")
        lines.append("")

    if len(user_list) > 50:
        lines.append(f"    # ... and {len(user_list) - 50} more users in cache")
        lines.append("    # Tip: Delete entries for people you don't need to track")
        lines.append("")

    # Optional freeform context
    lines.extend([
        "  # Optional: Freeform stakeholder context (alternative to structured list above)",
        "  # stakeholder_context: |",
        "  #   Key people to track:",
        "  #   - CEO drives strategic direction",
        "  #   - VP Product makes product decisions",
        "",
    ])

    # Channels
    lines.extend([
        "# Slack Channels",
        "channels:",
    ])

    for ch in channels:
        ch_name = ch.get("name", "unknown")
        ch_id = ch.get("id", "")
        lines.append(f"  - name: \"{ch_name}\"")
        lines.append(f"    id: \"{ch_id}\"")
        lines.append(f"    description: \"\"  # Add channel purpose/description")
        lines.append(f"    signal_type: \"medium\"  # critical/high/medium/low")
        lines.append("")

    # Analysis config
    lines.extend([
        "# Analysis Configuration (optional - these are defaults)",
        "# analysis:",
        "#   temporal:",
        "#     current_window_days: 7",
        "#     comparison_window_days: 21",
        "#     persistence_threshold_days: 28",
        "#   thresholds:",
        "#     high_velocity_hours: 4",
        "#     thread_depth_significant: 5",
        "#     participant_diversity: 3",
        "#     context_switch_rate: 5",
        "",
    ])

    yaml_content = "\n".join(lines)

    # Write to file if path provided
    if output_path:
        output_path.write_text(yaml_content)

    return yaml_content
