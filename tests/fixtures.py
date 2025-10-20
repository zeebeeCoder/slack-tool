"""Test fixtures for Parquet conversion tests"""

from datetime import datetime
from slack_intel import (
    SlackMessage,
    SlackUser,
    SlackReaction,
    SlackFile,
    SlackThread,
    JiraTicket,
    JiraSprint,
    JiraProgress,
    SlackChannel,
)


def sample_user() -> SlackUser:
    """Create a sample SlackUser with all fields populated"""
    return SlackUser(
        id="U012ABC3DEF",
        name="john.doe",
        real_name="John Doe",
        display_name="Johnny",
        email="john.doe@example.com",
        is_bot=False
    )


def sample_user_bot() -> SlackUser:
    """Create a sample bot user"""
    return SlackUser(
        id="B987ZYX6WVU",
        name="deploybot",
        real_name="Deploy Bot",
        display_name="DeployBot",
        email=None,
        is_bot=True
    )


def sample_reaction() -> SlackReaction:
    """Create a sample reaction"""
    return SlackReaction(
        name="100",
        count=3,
        users=["U012ABC3DEF", "U987ZYX6WVU"],
        user_names=["John Doe", "Jane Smith"]
    )


def sample_file() -> SlackFile:
    """Create a sample file attachment"""
    return SlackFile(
        id="F1234567890",
        name="screenshot.png",
        url_private="https://files.slack.com/files-pri/T123/F1234/screenshot.png",
        mimetype="image/png",
        size=245678
    )


def sample_message_basic() -> SlackMessage:
    """Create a basic message with minimal fields"""
    return SlackMessage(
        ts="1697654321.123456",  # 2023-10-18 ~17:38 UTC
        user="U012ABC3DEF",
        text="This is a simple test message"
    )


def sample_message_with_user_info() -> SlackMessage:
    """Create a message with full user info"""
    return SlackMessage(
        ts="1697654321.123456",
        user="U012ABC3DEF",
        text="Message with user details",
        user_info=sample_user()
    )


def sample_message_with_reactions() -> SlackMessage:
    """Create a message with reactions"""
    return SlackMessage(
        ts="1697654321.123456",
        user="U012ABC3DEF",
        text="Great job team!",
        user_info=sample_user(),
        reactions=[
            SlackReaction(name="100", count=2, users=["U012ABC3DEF", "U987ZYX6WVU"], user_names=["John", "Jane"]),
            SlackReaction(name="fire", count=1, users=["U111AAA1BBB"], user_names=["Bob"])
        ]
    )


def sample_message_with_files() -> SlackMessage:
    """Create a message with file attachments"""
    return SlackMessage(
        ts="1697654321.123456",
        user="U012ABC3DEF",
        text="Check out this screenshot",
        user_info=sample_user(),
        files=[sample_file()]
    )


def sample_message_with_jira() -> SlackMessage:
    """Create a message with JIRA ticket references in text"""
    return SlackMessage(
        ts="1697654321.123456",
        user="U012ABC3DEF",
        text="Working on PROJ-123 and PROJ-456 today. Need to finish PROJ-789.",
        user_info=sample_user()
    )


def sample_message_thread_parent() -> SlackMessage:
    """Create a message that's a thread parent"""
    parent = SlackMessage(
        ts="1697654321.123456",
        user="U012ABC3DEF",
        text="Thread parent message",
        user_info=sample_user(),
        thread_ts="1697654321.123456",  # Thread parent has thread_ts = ts
        replies_count=2
    )

    # Add thread with replies
    replies = [
        SlackMessage(
            ts="1697654400.123457",
            user="U987ZYX6WVU",
            text="First reply",
            thread_ts="1697654321.123456",
            user_info=SlackUser(id="U987ZYX6WVU", name="jane", real_name="Jane Smith")
        ),
        SlackMessage(
            ts="1697654500.123458",
            user="U012ABC3DEF",
            text="Second reply",
            thread_ts="1697654321.123456",
            user_info=sample_user()
        )
    ]

    parent.thread = SlackThread(
        parent_message=parent,
        replies=replies,
        total_participants=2,
        jira_tickets_mentioned=["PROJ-123"]
    )

    return parent


def sample_message_thread_reply() -> SlackMessage:
    """Create a message that's a thread reply (not parent)"""
    return SlackMessage(
        ts="1697654400.123457",
        user="U987ZYX6WVU",
        text="This is a reply in a thread",
        thread_ts="1697654321.123456",  # Different from ts - indicates it's a reply
        user_info=SlackUser(id="U987ZYX6WVU", name="jane", real_name="Jane Smith")
    )


def sample_jira_sprint() -> JiraSprint:
    """Create a sample JIRA sprint"""
    return JiraSprint(
        name="Sprint 42",
        state="active"
    )


def sample_jira_progress() -> JiraProgress:
    """Create sample JIRA progress"""
    return JiraProgress(
        total=100,
        progress=65
    )


def sample_jira_ticket_basic() -> JiraTicket:
    """Create a basic JIRA ticket"""
    return JiraTicket(
        ticket="PROJ-123",
        summary="Fix login bug",
        priority="High",
        issue_type="Bug",
        status="In Progress",
        assignee="john.doe@example.com",
        created="2023-10-15T10:00:00Z",
        updated="2023-10-18T15:30:00Z",
        project="COTO"
    )


def sample_jira_ticket_full() -> JiraTicket:
    """Create a JIRA ticket with all fields populated"""
    return JiraTicket(
        ticket="PROJ-456",
        summary="Implement user authentication",
        priority="High",
        issue_type="Story",
        status="In Progress",
        assignee="john.doe@example.com",
        due_date="2023-10-25",
        story_points=8,
        created="2023-10-10T09:00:00Z",
        updated="2023-10-18T16:00:00Z",
        blocks=["PROJ-789"],
        blocked_by=["PROJ-100"],
        depends_on=["PROJ-200", "PROJ-300"],
        related=["PROJ-400"],
        components=["Backend", "Auth"],
        labels=["security", "authentication"],
        fix_versions=["v2.0.0"],
        resolution="Done",
        progress=sample_jira_progress(),
        project="COTO",
        team="Backend Team",
        epic_link="PROJ-1000",
        comments={"john.doe": 3, "jane.smith": 2},
        sprints=[sample_jira_sprint()]
    )


def sample_channel() -> SlackChannel:
    """Create a sample Slack channel"""
    return SlackChannel(
        name="engineering",
        id="C9876543210"
    )


def sample_message_complex() -> SlackMessage:
    """Create a complex message with multiple features"""
    return SlackMessage(
        ts="1697654321.123456",
        user="U012ABC3DEF",
        text="PROJ-123: Deployed fix! 🚀 Check the logs in attached file.",
        user_info=sample_user(),
        reactions=[sample_reaction()],
        files=[sample_file()],
        replies_count=0
    )
