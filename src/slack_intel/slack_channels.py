# flake8: noqa: E501

import asyncio
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Set

from dotenv import load_dotenv
from jira import JIRA, JIRAError
from pydantic import BaseModel, Field, field_validator
from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient

# Add logging configuration at the top after imports
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)

# Load environment variables
load_dotenv()

# Constants
JIRA_LINK_PATTERN = r"((?<!([A-Z]{1,10})-?)[A-Z]+-\d+)"


# Pydantic Models for Data Structure
class SlackUser(BaseModel):
    """Represents a Slack user with essential information"""

    id: str
    name: Optional[str] = None
    real_name: Optional[str] = None
    display_name: Optional[str] = None
    email: Optional[str] = None
    is_bot: bool = False

    def to_parquet_dict(self) -> Dict[str, Any]:
        """Convert user to Parquet-friendly dictionary"""
        return {
            "user_id": self.id,
            "user_name": self.name,
            "real_name": self.real_name,
            "display_name": self.display_name,
            "email": self.email,
            "is_bot": self.is_bot,
        }

    class Config:
        extra = "allow"  # Allow additional fields from Slack API


class SlackFile(BaseModel):
    """Represents a file attachment in Slack"""

    id: str
    name: Optional[str] = None
    url_private: Optional[str] = None
    mimetype: Optional[str] = None
    size: Optional[int] = None

    class Config:
        extra = "allow"


class SlackReaction(BaseModel):
    """Represents a reaction on a Slack message"""

    name: str
    count: int
    users: List[str] = Field(default_factory=list)
    user_names: List[str] = Field(default_factory=list)


class SlackThread(BaseModel):
    """Represents a Slack thread with all replies"""

    parent_message: "SlackMessage"
    replies: List["SlackMessage"] = Field(default_factory=list)
    total_participants: int = 0
    jira_tickets_mentioned: List[str] = Field(default_factory=list)

    @property
    def reply_count(self) -> int:
        """Number of replies in the thread"""
        return len(self.replies)

    @property
    def participants(self) -> List[str]:
        """List of unique participants in the thread"""
        participants = set()
        if self.parent_message.user_info:
            participants.add(
                self.parent_message.user_info.real_name or "Unknown"
            )

        for reply in self.replies:
            if reply.user_info:
                participants.add(reply.user_info.real_name or "Unknown")

        return list(participants)

    @property
    def duration_minutes(self) -> float:
        """Duration of thread conversation in minutes"""
        if not self.replies:
            return 0.0

        start_time = self.parent_message.timestamp
        end_time = self.replies[-1].timestamp
        return (end_time - start_time).total_seconds() / 60

    def to_parquet_dict(self) -> Dict[str, Any]:
        """Convert thread to Parquet-friendly dictionary"""
        return {
            "thread_id": self.parent_message.ts,
            "reply_count": self.reply_count,
            "participant_count": len(self.participants),
            "participants": self.participants,
            "jira_tickets": self.jira_tickets_mentioned,
            "duration_minutes": self.duration_minutes,
        }

    def generate_summary(self) -> str:
        """Generate a textual summary of the thread"""
        summary_parts = []

        # Thread header
        starter = (
            self.parent_message.user_info.real_name
            if self.parent_message.user_info
            else "Unknown"
        )
        summary_parts.append(f"Thread started by {starter}")

        # Basic stats
        summary_parts.append(
            f"{self.reply_count} replies from {len(self.participants)} participants"
        )

        if self.duration_minutes > 0:
            if self.duration_minutes < 60:
                summary_parts.append(
                    f"Duration: {self.duration_minutes:.1f} minutes"
                )
            else:
                hours = self.duration_minutes / 60
                summary_parts.append(f"Duration: {hours:.1f} hours")

        # JIRA tickets if any
        if self.jira_tickets_mentioned:
            summary_parts.append(
                f"JIRA tickets discussed: {', '.join(self.jira_tickets_mentioned)}"
            )

        return " | ".join(summary_parts)


class SlackMessage(BaseModel):
    """Represents a Slack message with all metadata"""

    ts: str  # Timestamp
    user: Optional[str] = None
    text: str = ""
    thread_ts: Optional[str] = None
    user_info: Optional[SlackUser] = None
    reactions: List[SlackReaction] = Field(default_factory=list)
    files: List[SlackFile] = Field(default_factory=list)
    replies_count: int = 0
    formatted_text: Optional[str] = None
    relative_time: Optional[str] = None
    thread: Optional[
        SlackThread
    ] = None  # Full thread data if this is a parent message

    @property
    def timestamp(self) -> datetime:
        """Convert Slack timestamp to datetime"""
        return datetime.fromtimestamp(float(self.ts))

    @property
    def is_thread_parent(self) -> bool:
        """Check if this message is the start of a thread"""
        # Check if thread object is attached (when thread is fully built)
        if self.thread is not None:
            return True
        # Otherwise compute from fields (when caching from API)
        return (
            self.thread_ts == self.ts and
            self.replies_count > 0
        )

    @property
    def is_thread_reply(self) -> bool:
        """Check if this message is a reply in a thread"""
        return self.thread_ts is not None and self.thread_ts != self.ts

    def to_parquet_dict(self) -> Dict[str, Any]:
        """Convert message to Parquet-friendly flat dictionary

        Flattens nested structures and converts to Parquet-compatible types.
        """
        # Extract JIRA tickets from text
        jira_pattern = r"(?<=\b)[A-Z]+-\d+(?=\b)"
        jira_matches = re.findall(jira_pattern, self.text)
        jira_tickets = list(set(jira_matches)) if jira_matches else []

        # Flatten user_info to user_* fields
        user_data = {}
        if self.user_info:
            user_data = {
                "user_name": self.user_info.name,
                "user_real_name": self.user_info.real_name,
                "user_email": self.user_info.email,
                "user_is_bot": self.user_info.is_bot,
            }
        else:
            user_data = {
                "user_name": None,
                "user_real_name": None,
                "user_email": None,
                "user_is_bot": None,
            }

        # Convert reactions to list of dicts
        reactions_list = []
        for reaction in self.reactions:
            reactions_list.append({
                "emoji": reaction.name,
                "count": reaction.count,
                "users": reaction.users,
            })

        # Convert files to list of dicts
        files_list = []
        for file in self.files:
            files_list.append({
                "id": file.id,
                "name": file.name,
                "mimetype": file.mimetype,
                "url": file.url_private,
                "size": file.size,
            })

        # Build the Parquet dict
        return {
            # Core message fields
            "message_id": self.ts,
            "user_id": self.user,
            "text": self.text,
            "timestamp": self.timestamp.isoformat() + "Z",  # ISO 8601 format

            # Thread fields
            "thread_ts": self.thread_ts,
            "is_thread_parent": self.is_thread_parent,
            "is_thread_reply": self.is_thread_reply,
            "reply_count": self.replies_count,

            # Flattened user fields
            **user_data,

            # Array fields
            "reactions": reactions_list if reactions_list else [],
            "files": files_list if files_list else [],
            "jira_tickets": jira_tickets,

            # Boolean flags for filtering
            "has_reactions": len(self.reactions) > 0,
            "has_files": len(self.files) > 0,
            "has_thread": self.thread is not None,
        }

    class Config:
        extra = "allow"


class JiraSprint(BaseModel):
    """Represents a JIRA sprint"""

    name: str
    state: str


class JiraProgress(BaseModel):
    """Represents JIRA progress information"""

    total: int = 0
    progress: int = 0

    @property
    def percentage(self) -> float:
        """Calculate progress percentage"""
        return (self.progress / self.total * 100) if self.total > 0 else 0.0


class JiraTicket(BaseModel):
    """Comprehensive JIRA ticket information"""

    ticket: str
    summary: str
    priority: str
    issue_type: str
    status: str
    assignee: str

    # Delivery & Timeline
    due_date: Optional[str] = None
    story_points: Optional[int] = None
    created: str
    updated: str

    # Dependencies & Links
    blocks: List[str] = Field(default_factory=list)
    blocked_by: List[str] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)
    related: List[str] = Field(default_factory=list)

    # Progress & Components
    components: List[str] = Field(default_factory=list)
    labels: List[str] = Field(default_factory=list)
    fix_versions: List[str] = Field(default_factory=list)
    resolution: Optional[str] = None
    progress: JiraProgress = Field(default_factory=JiraProgress)

    # Team & Project
    project: str
    team: Optional[str] = None
    epic_link: Optional[str] = None

    # Activity
    comments: Dict[str, int] = Field(default_factory=dict)
    sprints: List[JiraSprint] = Field(default_factory=list)

    @property
    def total_comments(self) -> int:
        """Total number of comments across all users"""
        return sum(self.comments.values())

    @property
    def url(self) -> str:
        """Generate JIRA ticket URL"""
        return f"https://your-domain.atlassian.net/browse/{self.ticket}"

    def to_parquet_dict(self) -> Dict[str, Any]:
        """Convert JIRA ticket to Parquet-friendly flat dictionary

        Flattens nested progress and converts sprints to list of dicts.
        """
        # Flatten progress
        progress_data = {
            "progress_total": self.progress.total,
            "progress_done": self.progress.progress,
            "progress_percentage": self.progress.percentage,
        }

        # Convert sprints to list of dicts
        sprints_list = []
        for sprint in self.sprints:
            sprints_list.append({
                "name": sprint.name,
                "state": sprint.state,
            })

        return {
            # Core fields
            "ticket_id": self.ticket,
            "summary": self.summary,
            "priority": self.priority,
            "issue_type": self.issue_type,
            "status": self.status,
            "assignee": self.assignee,

            # Timeline
            "due_date": self.due_date,
            "story_points": self.story_points,
            "created": self.created,
            "updated": self.updated,

            # Dependencies (arrays)
            "blocks": self.blocks,
            "blocked_by": self.blocked_by,
            "depends_on": self.depends_on,
            "related": self.related,

            # Components (arrays)
            "components": self.components,
            "labels": self.labels,
            "fix_versions": self.fix_versions,
            "resolution": self.resolution,

            # Flattened progress
            **progress_data,

            # Team & Project
            "project": self.project,
            "team": self.team,
            "epic_link": self.epic_link,

            # Activity
            "comments": self.comments,
            "total_comments": self.total_comments,
            "sprints": sprints_list,
        }


class SlackChannel(BaseModel):
    """Represents a Slack channel configuration"""

    name: str
    id: str

    @field_validator("id")
    @classmethod
    def validate_channel_id(cls, v: str) -> str:
        if not v.startswith("C"):
            raise ValueError("Channel ID must start with C")
        return v


class TimeWindow(BaseModel):
    """Represents a time window for message retrieval"""

    days: int = 0
    hours: int = 4

    @property
    def start_time(self) -> float:
        """Calculate start timestamp"""
        current_time = datetime.now()
        time_delta = timedelta(days=self.days, hours=self.hours)
        return (current_time - time_delta).timestamp()

    @property
    def end_time(self) -> float:
        """Calculate end timestamp"""
        return datetime.now().timestamp()


class ChannelAnalytics(BaseModel):
    """Represents processed analytics for a channel"""

    channel_name: str
    messages: List[str] = Field(
        default_factory=list
    )  # Formatted message strings
    users: List[str] = Field(default_factory=list)  # User names
    jira_items: List[str] = Field(default_factory=list)  # JIRA ticket IDs

    @property
    def active_users_count(self) -> int:
        """Number of active users in the channel"""
        return len(self.users)

    @property
    def messages_count(self) -> int:
        """Number of messages processed"""
        return len(self.messages)

    @property
    def jira_tickets_count(self) -> int:
        """Number of unique JIRA tickets mentioned"""
        return len(self.jira_items)


class SlackChannelManager:
    def __init__(self) -> None:
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Initializing SlackChannelManager")
        self._validate_env()
        self.client: AsyncWebClient = AsyncWebClient(
            token=os.environ["SLACK_API_TOKEN"]
        )
        self.user_cache: Dict[str, Any] = {}
        self.ticket_cache: Dict[str, Dict[str, Any]] = {}
        self.jira_client: JIRA = self._init_jira()

    def _validate_env(self) -> None:
        """Validate required environment variables exist"""
        self.logger.debug("Validating environment variables")
        required_vars = ["SLACK_API_TOKEN", "JIRA_API_TOKEN", "JIRA_USER_NAME"]
        for var in required_vars:
            assert (
                var in os.environ
            ), f"{var} not found in environment variables"

    def _init_jira(self) -> JIRA:
        """Initialize JIRA client"""
        return JIRA(
            basic_auth=(
                os.environ["JIRA_USER_NAME"],
                os.environ["JIRA_API_TOKEN"],
            ),
            server="https://your-domain.atlassian.net",
        )

    async def get_messages(
        self, channel_id: str, start_time: float, end_time: float
    ) -> List[Dict[str, Any]]:
        self.logger.debug(
            f"Fetching messages for channel {channel_id} from {start_time} to {end_time}"
        )
        try:
            result = await self.client.conversations_history(
                channel=channel_id,
                oldest=str(start_time),
                latest=str(end_time),
            )
            messages: List[Dict[str, Any]] = (
                result.data.get("messages", [])
                if hasattr(result, "data") and isinstance(result.data, dict)
                else []
            )

            # Add semaphore for concurrency control
            semaphore = asyncio.Semaphore(
                10
            )  # Limit to 10 concurrent requests

            async def fetch_user_info(user_id: str) -> Any:
                async with semaphore:
                    return await self.client.users_info(user=user_id)

            # Fetch user info in parallel with rate limiting
            user_tasks = []
            for message in messages:
                user_id = message.get("user")
                if user_id and user_id not in self.user_cache:
                    user_tasks.append(fetch_user_info(user_id))

            if user_tasks:
                user_responses = await asyncio.gather(
                    *user_tasks, return_exceptions=True
                )
                for response in user_responses:
                    if isinstance(response, SlackApiError):
                        self.logger.error(
                            f"Error fetching user info: {response}"
                        )
                        continue
                    if (
                        not isinstance(response, Exception)
                        and hasattr(response, "data")
                        and isinstance(response.data, dict)
                    ):
                        user = response.data.get("user")
                        if user:
                            self.user_cache[user.get("id")] = user

            # Add user info to messages
            for message in messages:
                user_id = message.get("user")
                if user_id:
                    message["user_info"] = self.user_cache.get(user_id)

            # Fetch thread replies for thread parents
            # Thread parent detection: thread_ts == ts AND reply_count > 0
            thread_parents = [
                msg for msg in messages
                if msg.get("thread_ts") == msg.get("ts") and msg.get("reply_count", 0) > 0
            ]
            thread_replies = []  # Initialize for logging

            if thread_parents:
                self.logger.info(
                    f"Found {len(thread_parents)} thread parents, fetching replies..."
                )

                async def fetch_thread_replies(thread_ts: str) -> List[Dict[str, Any]]:
                    """Fetch all replies for a thread"""
                    async with semaphore:
                        try:
                            replies_result = await self.client.conversations_replies(
                                channel=channel_id, ts=thread_ts
                            )
                            thread_messages = (
                                replies_result.data.get("messages", [])
                                if hasattr(replies_result, "data")
                                and isinstance(replies_result.data, dict)
                                else []
                            )
                            # Skip first message (parent) and return only replies
                            return thread_messages[1:] if len(thread_messages) > 1 else []
                        except SlackApiError as e:
                            self.logger.warning(
                                f"Error fetching thread replies for {thread_ts}: {e}"
                            )
                            return []

                # Fetch all thread replies in parallel
                thread_tasks = [
                    fetch_thread_replies(parent["ts"]) for parent in thread_parents
                ]
                all_thread_replies_lists = await asyncio.gather(
                    *thread_tasks, return_exceptions=True
                )

                # Flatten and collect all thread replies
                for replies_list in all_thread_replies_lists:
                    if isinstance(replies_list, list):
                        thread_replies.extend(replies_list)

                if thread_replies:
                    # Fetch user info for reply authors not yet in cache
                    reply_user_tasks = []
                    for reply in thread_replies:
                        user_id = reply.get("user")
                        if user_id and user_id not in self.user_cache:
                            reply_user_tasks.append(fetch_user_info(user_id))

                    if reply_user_tasks:
                        reply_user_responses = await asyncio.gather(
                            *reply_user_tasks, return_exceptions=True
                        )
                        for response in reply_user_responses:
                            if isinstance(response, SlackApiError):
                                self.logger.error(
                                    f"Error fetching reply user info: {response}"
                                )
                                continue
                            if (
                                not isinstance(response, Exception)
                                and hasattr(response, "data")
                                and isinstance(response.data, dict)
                            ):
                                user = response.data.get("user")
                                if user:
                                    self.user_cache[user.get("id")] = user

                    # Add user info to thread replies
                    for reply in thread_replies:
                        user_id = reply.get("user")
                        if user_id:
                            reply["user_info"] = self.user_cache.get(user_id)

                    # Add thread replies to messages list
                    messages.extend(thread_replies)

            self.logger.debug(
                f"Retrieved {len(messages)} total messages "
                f"({len(messages) - len(thread_replies) if thread_parents else len(messages)} timeline, "
                f"{len(thread_replies) if thread_parents else 0} thread replies)"
            )
            return messages

        except SlackApiError as e:
            self.logger.error(
                f"Error fetching messages: {e.response['error']}"
            )
            return []

    async def get_user_info(self, user_id: str) -> Any:
        """Get user info from cache or API"""
        if user_id not in self.user_cache:
            try:
                user_info = await self.client.users_info(user=user_id)
                self.user_cache[user_id] = (
                    user_info.data.get("user", "Unknown")
                    if hasattr(user_info, "data")
                    and isinstance(user_info.data, dict)
                    else "Unknown"
                )
            except SlackApiError:
                return "Unknown"
        return self.user_cache.get(user_id, "Unknown")

    async def format_user_mentions(self, text: str) -> str:
        """Replace user IDs with real names in text"""
        user_mentions = re.findall("<@(U[A-Z0-9]+)>", text)
        for user_id in user_mentions:
            user_info = await self.get_user_info(user_id)
            real_name = user_info.get("real_name", "")
            text = text.replace(f"<@{user_id}>", real_name)
        return text

    async def format_reactions(self, reactions: List[Dict[str, Any]]) -> str:
        """Format reaction data into readable string"""
        reactions_list = []
        for reaction in reactions:
            reaction_name = reaction.get("name")
            reaction_count = reaction.get("count")
            users = reaction.get("users", [])
            users_names = []
            for user_id in users:
                user_info = await self.get_user_info(user_id)
                name = user_info.get("real_name", "Unknown User")
                if name:
                    users_names.append(name)
            users_names_str = ", ".join(users_names)
            reactions_list.append(
                f"{reaction_name} ({reaction_count}) by {users_names_str}"
            )
        return "\n".join(reactions_list)

    async def format_replies(
        self, thread_ts: Optional[str], channel_id: str
    ) -> str:
        """Format thread replies into readable string"""
        replies_text = ""
        if thread_ts:
            try:
                replies_result = await self.client.conversations_replies(
                    channel=channel_id, ts=thread_ts
                )
                thread_messages = (
                    replies_result.data.get("messages", [])
                    if hasattr(replies_result, "data")
                    and isinstance(replies_result.data, dict)
                    else []
                )
                if thread_messages:
                    replies_text = " >> REPLIES_START : "
                    for reply in thread_messages:
                        reply_text = await self.format_user_mentions(
                            reply.get("text", "")
                        )
                        reply_user_id = reply.get("user")
                        reply_user = await self.get_user_info(reply_user_id)
                        reply_real_name = reply_user.get(
                            "real_name", "Unknown User"
                        )
                        reply_timestamp = datetime.fromtimestamp(
                            float(reply.get("ts", ""))
                        ).strftime("%Y-%m-%d %H:%M:%S")
                        reactions = reply.get("reactions", [])
                        reactions_str = await self.format_reactions(reactions)
                        reply_text += (
                            f"\nReactions: {reactions_str}"
                            if reactions_str
                            else ""
                        )
                        replies_text += f"\n{reply_timestamp} - {reply_real_name}: {reply_text}"
                    replies_text += " << REPLIES_END"
            except SlackApiError:
                pass
        return replies_text

    @staticmethod
    def format_relative_time(message_time: datetime) -> str:
        """Convert timestamp to relative time string"""
        now = datetime.now().replace(tzinfo=message_time.tzinfo)
        delta = now - message_time

        if delta < timedelta(minutes=1):
            return "just now"
        elif delta < timedelta(hours=1):
            return f"{delta.seconds // 60}m ago"
        elif delta < timedelta(days=1):
            return f"{delta.seconds // 3600}h ago"
        else:
            days = delta.days
            hours = delta.seconds // 3600
            return f"{days}d {hours}h ago"

    async def format_message(
        self, message: Dict[str, Any], channel_id: str
    ) -> str:
        """Format a Slack message with all its components"""
        user_info = message.get("user_info", {})
        real_name = user_info.get("real_name", "Unknown User")
        text = message.get("text", "")
        timestamp = datetime.fromtimestamp(
            float(message.get("ts", ""))
        ).strftime("%Y-%m-%d %H:%M")
        message_time = datetime.strptime(timestamp, "%Y-%m-%d %H:%M")
        relative_time = self.format_relative_time(message_time)

        # Handle file attachments
        files = message.get("files", [])
        file_urls = [
            file["url_private"] for file in files if "url_private" in file
        ]
        file_str = "\n".join(file_urls) if file_urls else ""

        # Format the message components
        formatted_text = await self.format_user_mentions(text)
        reactions_str = await self.format_reactions(
            message.get("reactions", [])
        )
        replies_text = await self.format_replies(
            message.get("thread_ts"), channel_id
        )

        if file_str:
            formatted_text += f"\nFile URLs:\n{file_str}"

        formatted_message = f"MESS_START:{timestamp}:{relative_time} - {real_name}: {formatted_text}"
        if reactions_str:
            formatted_message += f"\nReactions: {reactions_str}"
        formatted_message += f"{replies_text} MESS_END"

        return formatted_message

    async def get_ticket_info(self, ticket: str) -> Dict[str, Any]:
        """Get JIRA ticket information with caching"""
        self.logger.debug(f"Getting ticket info for {ticket}")
        if ticket in self.ticket_cache:
            self.logger.debug(f"Cache hit for ticket {ticket}")
            return self.ticket_cache[ticket]

        try:
            # Convert synchronous JIRA call to async using to_thread
            issue = await asyncio.to_thread(self.jira_client.issue, ticket)
        except JIRAError as e:
            self.logger.error(f"Error fetching JIRA ticket {ticket}: {e}")
            if e.status_code == 404:
                return {
                    "error": "Issue does not exist or you do not have permission to see it.",
                    "ticket": ticket,
                }
            raise

        # Extract ticket information
        summary = issue.fields.summary[:40]
        status = issue.fields.status.name
        assignee = (
            issue.fields.assignee.displayName
            if issue.fields.assignee
            else "Unassigned"
        )

        # Extract sprint information
        sprints = []
        if (
            hasattr(issue.fields, "customfield_10020")
            and issue.fields.customfield_10020
        ):
            for sprint in issue.fields.customfield_10020:
                if isinstance(sprint, str):
                    # Parse sprint string if it's in string format
                    sprint_info = dict(
                        item.split("=") for item in sprint[1:-1].split(",")
                    )
                    sprints.append(
                        {
                            "name": sprint_info.get("name", "Unknown"),
                            "state": sprint_info.get("state", "Unknown"),
                        }
                    )
                else:
                    # Handle sprint object if available
                    sprints.append(
                        {
                            "name": getattr(sprint, "name", "Unknown"),
                            "state": getattr(sprint, "state", "Unknown"),
                        }
                    )

        created_date = datetime.strptime(
            issue.fields.created, "%Y-%m-%dT%H:%M:%S.%f%z"
        )
        updated_date = datetime.strptime(
            issue.fields.updated, "%Y-%m-%dT%H:%M:%S.%f%z"
        )

        # Count comments by author
        comment_counts: Dict[str, int] = defaultdict(int)
        for comment in issue.fields.comment.comments:
            comment_counts[comment.author.displayName] += 1

        ticket_info = {
            "ticket": ticket,
            "summary": summary,
            "priority": issue.fields.priority.name,
            "issue_type": issue.fields.issuetype.name,
            "status": status,
            "assignee": assignee,
            # Delivery & Timeline
            "due_date": (
                issue.fields.duedate
                if hasattr(issue.fields, "duedate")
                else None
            ),
            "story_points": getattr(
                issue.fields, "customfield_10016", None
            ),  # Adjust field ID based on your JIRA
            "created": self.format_relative_time(created_date),
            "updated": self.format_relative_time(updated_date),
            # Dependencies & Links
            "blocks": [
                link.outwardIssue.key
                for link in issue.fields.issuelinks
                if hasattr(link, "outwardIssue") and link.type.name == "Blocks"
            ],
            "blocked_by": [
                link.inwardIssue.key
                for link in issue.fields.issuelinks
                if hasattr(link, "inwardIssue") and link.type.name == "Blocks"
            ],
            "depends_on": [
                link.outwardIssue.key
                for link in issue.fields.issuelinks
                if hasattr(link, "outwardIssue")
                and link.type.name == "Depends"
            ],
            "related": [
                link.outwardIssue.key
                for link in issue.fields.issuelinks
                if hasattr(link, "outwardIssue")
                and link.type.name == "Relates"
            ],
            # Progress & Components
            "components": [comp.name for comp in issue.fields.components],
            "labels": issue.fields.labels,
            "fix_versions": (
                [ver.name for ver in issue.fields.fixVersions]
                if hasattr(issue.fields, "fixVersions")
                else []
            ),
            "resolution": (
                issue.fields.resolution.name
                if issue.fields.resolution
                else None
            ),
            "progress": {
                "total": (
                    issue.fields.progress.total
                    if hasattr(issue.fields, "progress")
                    else 0
                ),
                "progress": (
                    issue.fields.progress.progress
                    if hasattr(issue.fields, "progress")
                    else 0
                ),
            },
            # Team & Project
            "project": issue.fields.project.key,
            "team": getattr(
                issue.fields, "customfield_10021", None
            ),  # Adjust field ID for team field
            "epic_link": getattr(
                issue.fields, "customfield_10014", None
            ),  # Adjust field ID for epic link
            # Existing fields
            "comments": dict(comment_counts),
            "sprints": sprints,
        }

        self.ticket_cache[ticket] = ticket_info
        self.logger.debug(f"Cached ticket info for {ticket}")
        return ticket_info

    @staticmethod
    def extract_jira_tickets(text: str) -> Optional[List[str]]:
        """Extract JIRA ticket IDs from text"""
        jira_link_pattern = r"(?<=\b)[A-Z]+-\d+(?=\b)"
        matches = re.findall(jira_link_pattern, text)
        return list(set(matches)) if matches else None

    async def load_channel_messages(
        self, channel_id: str, days_ago: int
    ) -> List[Dict[str, Any]]:
        """Load messages from a channel for the specified time period"""
        current_time = datetime.now()
        start_time = (current_time - timedelta(days=days_ago)).timestamp()
        end_time = current_time.timestamp()

        return await self.get_messages(channel_id, start_time, end_time)

    def format_ticket_metadata(self, metadata: Dict[str, Any]) -> str:
        """Format ticket metadata, excluding empty/null values"""

        def is_valuable(value: Any) -> bool:
            """Check if a value is worth including in the output"""
            if value is None or value == "":
                return False
            if isinstance(value, (list, dict)) and not value:
                return False
            return True

        # Priority fields to show first (if they exist and have value)
        priority_fields = ["summary", "status", "assignee", "priority"]
        formatted_parts = []

        # Add priority fields first
        for field in priority_fields:
            if field in metadata and is_valuable(metadata[field]):
                formatted_parts.append(f"{field}: {metadata[field]}")

        # Add other valuable fields
        for key, value in metadata.items():
            if key not in priority_fields and is_valuable(value):
                if key == "sprints":
                    if value:  # If there are any sprints
                        sprint_info = []
                        for sprint in value:
                            sprint_str = f"{sprint['name']}({sprint['state']})"
                            sprint_info.append(sprint_str)
                        formatted_parts.append(
                            f"sprints: {', '.join(sprint_info)}"
                        )
                elif key == "progress":
                    if value["total"] > 0:
                        progress_pct = (
                            value["progress"] / value["total"]
                        ) * 100
                        formatted_parts.append(
                            f"progress: {progress_pct:.0f}%"
                        )
                elif key == "comments":
                    comment_count = sum(value.values())
                    if comment_count > 0:
                        formatted_parts.append(f"comments: {comment_count}")
                elif key not in [
                    "ticket",
                    "_cached_time",
                ]:  # Exclude internal fields
                    formatted_parts.append(f"{key}: {value}")

        return f"[{' | '.join(formatted_parts)}]"

    async def process_channel_messages(
        self, messages: List[Dict[str, Any]], channel_id: str
    ) -> tuple[List[str], List[str], List[str]]:
        self.logger.debug(
            f"Processing {len(messages)} messages for channel {channel_id}"
        )
        messages_out: List[str] = []
        jira_tickets: List[str] = []  # This should only contain ticket IDs
        user_ids_in_channel: Set[str] = set()

        for message in messages:
            # Format the message and await the result
            message_formatted = await self.format_message(message, channel_id)

            # Extract and process JIRA tickets
            jira_tickets_temp = self.extract_jira_tickets(message_formatted)
            if jira_tickets_temp:
                jira_tickets.extend(
                    jira_tickets_temp
                )  # Add just the ticket IDs

                # Fetch all ticket info concurrently
                ticket_tasks = [
                    self.get_ticket_info(ticket)
                    for ticket in jira_tickets_temp
                ]
                ticket_infos = await asyncio.gather(*ticket_tasks)

                # Process all tickets for this message
                for jira_ticket, jira_metadata in zip(
                    jira_tickets_temp, ticket_infos
                ):
                    jira_metadata_str = self.format_ticket_metadata(
                        jira_metadata
                    )
                    ticket_link = f"<https://your-domain.atlassian.net/browse/{jira_ticket}>"
                    ticket_with_metadata = f"{jira_ticket} {jira_metadata_str}"

                    message_formatted = (
                        message_formatted.replace(
                            ticket_link, ticket_with_metadata
                        )
                        if ticket_link in message_formatted
                        else message_formatted.replace(
                            jira_ticket, ticket_with_metadata
                        )
                    )

            messages_out.append(message_formatted)
            user_ids_in_channel.add(message.get("user", ""))

        # Get user names for the channel
        users = [
            self.user_cache.get(user_id, {}).get("name", "")
            for user_id in user_ids_in_channel
            if user_id
        ]

        return (
            messages_out,
            users,
            list(set(jira_tickets)),
        )  # Deduplicate tickets before returning

    async def process_channels(
        self,
        channels_of_interest: List[Dict[str, str]],
        days: int = 4,
        hours: int = 0,
    ) -> Dict[str, Dict[str, List[str]]]:
        """Process multiple channels in parallel

        Args:
            channels_of_interest: List of channel dictionaries with 'name' and 'id'
            days: Number of days to look back (default: 0)
            hours: Number of hours to look back (default: 4)
        """
        channel_data = {}
        tasks = []

        # Calculate time window
        current_time = datetime.now()
        time_delta = timedelta(days=days, hours=hours)
        start_time = (current_time - time_delta).timestamp()
        end_time = current_time.timestamp()

        # Create tasks for both getting messages and processing them
        for channel in channels_of_interest:

            async def process_single_channel(
                channel: Dict[str, str]
            ) -> tuple[str, Dict[str, List[str]]]:
                messages = await self.get_messages(
                    channel["id"], start_time, end_time
                )
                (
                    messages_processed,
                    users,
                    jira_items,
                ) = await self.process_channel_messages(
                    messages, channel["id"]
                )
                return channel["name"], {
                    "messages": messages_processed,
                    "users": users,
                    "jira_items": jira_items,
                }

            tasks.append(process_single_channel(channel))

        # Execute all tasks in parallel
        results = await asyncio.gather(*tasks)

        # Combine results
        for channel_name, data in results:
            channel_data[channel_name] = data

        return channel_data

    def get_all_users(self) -> List[str]:
        """Get a list of all users in the cache"""
        return [
            f"Real Name: {user_info.get('real_name', 'Unknown User')}"
            for user_info in self.user_cache.values()
        ]

    # Pydantic Model Conversion Methods
    def _convert_to_slack_user(self, user_data: Dict[str, Any]) -> SlackUser:
        """Convert raw Slack user data to SlackUser model"""
        return SlackUser(
            id=user_data.get("id", ""),
            name=user_data.get("name"),
            real_name=user_data.get("real_name"),
            display_name=user_data.get("display_name"),
            email=user_data.get("profile", {}).get("email"),
            is_bot=user_data.get("is_bot", False),
        )

    def _convert_to_slack_message(
        self, message_data: Dict[str, Any]
    ) -> SlackMessage:
        """Convert raw Slack message data to SlackMessage model"""
        # Convert user info if available
        user_info = None
        if message_data.get("user_info"):
            user_info = self._convert_to_slack_user(message_data["user_info"])

        # Convert reactions
        reactions = []
        for reaction_data in message_data.get("reactions", []):
            reactions.append(
                SlackReaction(
                    name=reaction_data.get("name", ""),
                    count=reaction_data.get("count", 0),
                    users=reaction_data.get("users", []),
                )
            )

        # Convert files
        files = []
        for file_data in message_data.get("files", []):
            files.append(
                SlackFile(
                    id=file_data.get("id", ""),
                    name=file_data.get("name"),
                    url_private=file_data.get("url_private"),
                    mimetype=file_data.get("mimetype"),
                    size=file_data.get("size"),
                )
            )

        return SlackMessage(
            ts=message_data.get("ts", ""),
            user=message_data.get("user"),
            text=message_data.get("text", ""),
            thread_ts=message_data.get("thread_ts"),
            user_info=user_info,
            reactions=reactions,
            files=files,
            replies_count=message_data.get("reply_count", 0),
        )

    def _convert_to_jira_ticket(
        self, ticket_data: Dict[str, Any]
    ) -> JiraTicket:
        """Convert raw JIRA ticket data to JiraTicket model"""
        # Convert sprints
        sprints = []
        for sprint_data in ticket_data.get("sprints", []):
            sprints.append(
                JiraSprint(
                    name=sprint_data.get("name", ""),
                    state=sprint_data.get("state", ""),
                )
            )

        # Convert progress
        progress_data = ticket_data.get("progress", {})
        progress = JiraProgress(
            total=progress_data.get("total", 0),
            progress=progress_data.get("progress", 0),
        )

        return JiraTicket(
            ticket=ticket_data.get("ticket", ""),
            summary=ticket_data.get("summary", ""),
            priority=ticket_data.get("priority", ""),
            issue_type=ticket_data.get("issue_type", ""),
            status=ticket_data.get("status", ""),
            assignee=ticket_data.get("assignee", ""),
            due_date=ticket_data.get("due_date"),
            story_points=ticket_data.get("story_points"),
            created=ticket_data.get("created", ""),
            updated=ticket_data.get("updated", ""),
            blocks=ticket_data.get("blocks", []),
            blocked_by=ticket_data.get("blocked_by", []),
            depends_on=ticket_data.get("depends_on", []),
            related=ticket_data.get("related", []),
            components=ticket_data.get("components", []),
            labels=ticket_data.get("labels", []),
            fix_versions=ticket_data.get("fix_versions", []),
            resolution=ticket_data.get("resolution"),
            progress=progress,
            project=ticket_data.get("project", ""),
            team=ticket_data.get("team"),
            epic_link=ticket_data.get("epic_link"),
            comments=ticket_data.get("comments", {}),
            sprints=sprints,
        )

    def _convert_to_channel_analytics(
        self, channel_name: str, data: Dict[str, List[str]]
    ) -> ChannelAnalytics:
        """Convert raw channel data to ChannelAnalytics model"""
        return ChannelAnalytics(
            channel_name=channel_name,
            messages=data.get("messages", []),
            users=data.get("users", []),
            jira_items=data.get("jira_items", []),
        )

    async def process_channels_structured(
        self, channels: List[SlackChannel], time_window: TimeWindow
    ) -> Dict[str, ChannelAnalytics]:
        """Process multiple channels and return structured Pydantic models

        Args:
            channels: List of SlackChannel models
            time_window: TimeWindow model for time range

        Returns:
            Dictionary mapping channel names to ChannelAnalytics models
        """
        # Convert to the format expected by the existing method
        channels_dict = [{"name": ch.name, "id": ch.id} for ch in channels]

        # Use existing method to get raw data
        raw_data = await self.process_channels(
            channels_dict, days=time_window.days, hours=time_window.hours
        )

        # Convert to structured models
        structured_data = {}
        for channel_name, data in raw_data.items():
            structured_data[channel_name] = self._convert_to_channel_analytics(
                channel_name, data
            )

        return structured_data

    async def get_structured_messages(
        self, channel: SlackChannel, time_window: TimeWindow
    ) -> List[SlackMessage]:
        """Get messages as structured Pydantic models

        Args:
            channel: SlackChannel model
            time_window: TimeWindow model

        Returns:
            List of SlackMessage models
        """
        raw_messages = await self.get_messages(
            channel.id, time_window.start_time, time_window.end_time
        )

        return [self._convert_to_slack_message(msg) for msg in raw_messages]

    async def get_structured_ticket_info(self, ticket_id: str) -> JiraTicket:
        """Get JIRA ticket as structured Pydantic model

        Args:
            ticket_id: JIRA ticket ID

        Returns:
            JiraTicket model
        """
        raw_ticket_data = await self.get_ticket_info(ticket_id)
        return self._convert_to_jira_ticket(raw_ticket_data)

    async def fetch_jira_tickets_batch(
        self, ticket_ids: List[str]
    ) -> List[JiraTicket]:
        """Fetch multiple JIRA tickets in parallel with rate limiting

        This method fetches JIRA tickets in parallel while respecting rate limits.
        Failed ticket fetches are logged as warnings and excluded from results.

        Args:
            ticket_ids: List of unique JIRA ticket IDs to fetch

        Returns:
            List of successfully fetched JiraTicket models
            (excludes tickets that failed to fetch)

        Example:
            >>> manager = SlackChannelManager()
            >>> ticket_ids = ["PRD-123", "PRD-456", "PRD-789"]
            >>> tickets = await manager.fetch_jira_tickets_batch(ticket_ids)
            >>> print(f"Fetched {len(tickets)} tickets")
        """
        semaphore = asyncio.Semaphore(10)  # Max 10 concurrent JIRA requests

        async def fetch_one(ticket_id: str) -> Optional[JiraTicket]:
            """Fetch a single JIRA ticket with rate limiting"""
            async with semaphore:
                try:
                    raw_data = await self.get_ticket_info(ticket_id)
                    # Check if the response is an error
                    if "error" in raw_data:
                        self.logger.warning(
                            f"JIRA ticket {ticket_id} not found or inaccessible: "
                            f"{raw_data.get('error')}"
                        )
                        return None
                    return self._convert_to_jira_ticket(raw_data)
                except Exception as e:
                    self.logger.warning(
                        f"Failed to fetch JIRA ticket {ticket_id}: {e}"
                    )
                    return None  # Continue with warning

        # Fetch all tickets in parallel
        results = await asyncio.gather(
            *[fetch_one(ticket_id) for ticket_id in ticket_ids],
            return_exceptions=False
        )

        # Filter out None (failed fetches) and return successful tickets
        successful_tickets = [ticket for ticket in results if ticket is not None]

        self.logger.info(
            f"Successfully fetched {len(successful_tickets)} of "
            f"{len(ticket_ids)} JIRA tickets"
        )

        return successful_tickets

    async def get_thread_data(
        self, thread_ts: str, channel_id: str
    ) -> Optional[SlackThread]:
        """Get complete thread data as structured model

        Args:
            thread_ts: Thread timestamp (parent message timestamp)
            channel_id: Slack channel ID

        Returns:
            SlackThread model with all replies
        """
        try:
            # Get all messages in the thread
            replies_result = await self.client.conversations_replies(
                channel=channel_id, ts=thread_ts
            )
            thread_messages = (
                replies_result.data.get("messages", [])
                if hasattr(replies_result, "data")
                and isinstance(replies_result.data, dict)
                else []
            )

            if not thread_messages:
                return None

            # First message is the parent, rest are replies
            parent_raw = thread_messages[0]
            replies_raw = (
                thread_messages[1:] if len(thread_messages) > 1 else []
            )

            # Convert to structured models
            parent_message = self._convert_to_slack_message(parent_raw)
            reply_messages = [
                self._convert_to_slack_message(reply) for reply in replies_raw
            ]

            # Extract JIRA tickets from entire thread
            all_text = (
                parent_message.text
                + " "
                + " ".join([reply.text for reply in reply_messages])
            )
            jira_tickets = self.extract_jira_tickets(all_text) or []

            # Create thread model
            thread = SlackThread(
                parent_message=parent_message,
                replies=reply_messages,
                total_participants=len(
                    set(
                        [parent_message.user]
                        + [
                            reply.user
                            for reply in reply_messages
                            if reply.user
                        ]
                    )
                ),
                jira_tickets_mentioned=jira_tickets,
            )

            return thread

        except SlackApiError as e:
            self.logger.error(f"Error fetching thread data: {e}")
            return None

    async def generate_thread_summary(
        self, thread_ts: str, channel_id: str
    ) -> str:
        """Generate a comprehensive textual summary of a thread

        Args:
            thread_ts: Thread timestamp
            channel_id: Slack channel ID

        Returns:
            Formatted thread summary string
        """
        thread = await self.get_thread_data(thread_ts, channel_id)
        if not thread:
            return "Thread not found or empty"

        summary_lines = []

        # Header
        summary_lines.append("=" * 60)
        summary_lines.append("THREAD SUMMARY")
        summary_lines.append("=" * 60)

        # Basic info
        summary_lines.append(thread.generate_summary())
        summary_lines.append("")

        # Parent message
        parent_user = (
            thread.parent_message.user_info.real_name
            if thread.parent_message.user_info
            else "Unknown"
        )
        parent_time = thread.parent_message.timestamp.strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        summary_lines.append(
            f"ORIGINAL MESSAGE ({parent_time}) - {parent_user}:"
        )
        summary_lines.append(f"  {thread.parent_message.text}")
        summary_lines.append("")

        # Replies summary
        if thread.replies:
            summary_lines.append("REPLIES:")
            for i, reply in enumerate(thread.replies, 1):
                reply_user = (
                    reply.user_info.real_name if reply.user_info else "Unknown"
                )
                reply_time = reply.timestamp.strftime("%H:%M:%S")
                summary_lines.append(
                    f"  {i}. ({reply_time}) {reply_user}: {reply.text[:100]}{'...' if len(reply.text) > 100 else ''}"
                )

        # JIRA tickets if any
        if thread.jira_tickets_mentioned:
            summary_lines.append("")
            summary_lines.append("JIRA TICKETS MENTIONED:")
            for ticket in thread.jira_tickets_mentioned:
                try:
                    ticket_info = await self.get_structured_ticket_info(ticket)
                    summary_lines.append(
                        f"  • {ticket}: {ticket_info.summary} [{ticket_info.status}]"
                    )
                except Exception:
                    summary_lines.append(
                        f"  • {ticket}: (Could not fetch details)"
                    )

        summary_lines.append("=" * 60)
        return "\n".join(summary_lines)

    async def find_threads_in_channel(
        self, channel: SlackChannel, time_window: TimeWindow
    ) -> List[SlackThread]:
        """Find all threads in a channel within the time window

        Args:
            channel: SlackChannel model
            time_window: TimeWindow model

        Returns:
            List of SlackThread models
        """
        # Get all messages
        messages = await self.get_messages(
            channel.id, time_window.start_time, time_window.end_time
        )

        # Find messages that are thread parents (have replies)
        thread_parents = []
        for message in messages:
            if (
                message.get("thread_ts") == message.get("ts")
                and message.get("reply_count", 0) > 0
            ):
                thread_parents.append(message)

        # Get full thread data for each parent
        threads = []
        for parent in thread_parents:
            thread = await self.get_thread_data(parent["ts"], channel.id)
            if thread:
                threads.append(thread)

        return threads

    async def generate_llm_optimized_text(
        self, channel: SlackChannel, time_window: TimeWindow
    ) -> str:
        """Generate text output optimized for LLM consumption with spatial clustering

        This method creates a chronologically ordered conversation view where:
        - Messages and their thread replies are spatially clustered together
        - JIRA tickets are enriched with metadata inline
        - The format is optimized for LLM understanding of conversation flow

        Args:
            channel: SlackChannel model
            time_window: TimeWindow model for time range

        Returns:
            Formatted text string ready for LLM consumption
        """
        # Get all messages in chronological order
        raw_messages = await self.get_messages(
            channel.id, time_window.start_time, time_window.end_time
        )

        if not raw_messages:
            return f"📱 Channel: {channel.name}\nNo messages found in the specified time window."

        # Sort messages by timestamp to ensure chronological order
        raw_messages.sort(key=lambda msg: float(msg.get("ts", "0")))

        # Separate parent messages from thread replies
        parent_messages = []
        thread_replies = defaultdict(list)

        for msg in raw_messages:
            if msg.get("thread_ts") and msg.get("thread_ts") != msg.get("ts"):
                # This is a thread reply
                thread_replies[msg["thread_ts"]].append(msg)
            else:
                # This is either a standalone message or thread parent
                parent_messages.append(msg)

        # Sort thread replies by timestamp within each thread
        for thread_ts in thread_replies:
            thread_replies[thread_ts].sort(
                key=lambda msg: float(msg.get("ts", "0"))
            )

        # Build the formatted output
        output_lines = []
        output_lines.append("=" * 80)
        output_lines.append(f"📱 SLACK CHANNEL: {channel.name}")
        output_lines.append(
            f"⏰ TIME WINDOW: {time_window.days}d {time_window.hours}h ago to now"
        )
        output_lines.append("=" * 80)
        output_lines.append("")

        # Process each parent message with its threads
        message_count = 0
        for parent_msg in parent_messages:
            message_count += 1

            # Format parent message
            formatted_parent = await self._format_message_for_llm(
                parent_msg, channel.id
            )
            output_lines.append(f"💬 MESSAGE #{message_count}")
            output_lines.append(formatted_parent)

            # Check if this message is a thread parent and fetch ALL replies
            parent_ts = parent_msg.get("ts")
            thread_ts = parent_msg.get("thread_ts")

            # For thread parents (where ts == thread_ts), fetch complete thread replies
            if thread_ts == parent_ts:
                try:
                    # Use conversations_replies to get ALL thread messages regardless of time window
                    replies_result = await self.client.conversations_replies(
                        channel=channel.id, ts=parent_ts
                    )
                    all_thread_messages = (
                        replies_result.data.get("messages", [])
                        if hasattr(replies_result, "data")
                        and isinstance(replies_result.data, dict)
                        else []
                    )

                    # Skip the first message (parent) and get actual replies
                    actual_replies = (
                        all_thread_messages[1:]
                        if len(all_thread_messages) > 1
                        else []
                    )

                    if actual_replies:
                        output_lines.append("")
                        output_lines.append("  🧵 THREAD REPLIES:")

                        for i, reply in enumerate(actual_replies, 1):
                            # Add user info to reply if not present
                            user_id = reply.get("user")
                            if user_id and user_id not in self.user_cache:
                                try:
                                    user_info = await self.client.users_info(
                                        user=user_id
                                    )
                                    self.user_cache[user_id] = (
                                        user_info.data.get("user", "Unknown")
                                        if hasattr(user_info, "data")
                                        and isinstance(user_info.data, dict)
                                        else "Unknown"
                                    )
                                except:
                                    pass
                            reply["user_info"] = self.user_cache.get(
                                user_id, {}
                            )

                            formatted_reply = (
                                await self._format_message_for_llm(
                                    reply, channel.id, is_thread_reply=True
                                )
                            )
                            output_lines.append(
                                f"    ↳ REPLY #{i}: {formatted_reply}"
                            )

                except Exception as e:
                    self.logger.warning(
                        f"Error fetching thread replies for {parent_ts}: {e}"
                    )
                    # Fallback to replies from time window if any
                    if (
                        parent_ts in thread_replies
                        and thread_replies[parent_ts]
                    ):
                        output_lines.append("")
                        output_lines.append(
                            "  🧵 THREAD REPLIES (partial - within time window):"
                        )

                        for i, reply in enumerate(
                            thread_replies[parent_ts], 1
                        ):
                            formatted_reply = (
                                await self._format_message_for_llm(
                                    reply, channel.id, is_thread_reply=True
                                )
                            )
                            output_lines.append(
                                f"    ↳ REPLY #{i}: {formatted_reply}"
                            )

            # Handle non-thread parent messages that might have replies in time window
            elif parent_ts in thread_replies and thread_replies[parent_ts]:
                output_lines.append("")
                output_lines.append("  🧵 THREAD REPLIES (within time window):")

                for i, reply in enumerate(thread_replies[parent_ts], 1):
                    formatted_reply = await self._format_message_for_llm(
                        reply, channel.id, is_thread_reply=True
                    )
                    output_lines.append(f"    ↳ REPLY #{i}: {formatted_reply}")

            output_lines.append("")
            output_lines.append("-" * 60)
            output_lines.append("")

        # Handle orphaned thread replies (replies without parents in time window)
        orphaned_replies = []
        for thread_ts, replies in thread_replies.items():
            # Check if parent exists in our parent_messages
            parent_exists = any(
                msg.get("ts") == thread_ts for msg in parent_messages
            )
            if not parent_exists and replies:
                orphaned_replies.extend(replies)

        if orphaned_replies:
            output_lines.append(
                "🔗 ORPHANED THREAD REPLIES (parent messages outside time window):"
            )
            output_lines.append("")

            for i, reply in enumerate(orphaned_replies, 1):
                message_count += 1
                formatted_reply = await self._format_message_for_llm(
                    reply, channel.id
                )
                output_lines.append(
                    f"💬 MESSAGE #{message_count} (📎 Reply to older thread)"
                )
                output_lines.append(formatted_reply)
                output_lines.append("")
                output_lines.append("-" * 60)
                output_lines.append("")

        # Add summary statistics
        total_replies = sum(
            len(replies) for replies in thread_replies.values()
        )
        output_lines.append("📊 CONVERSATION SUMMARY:")
        output_lines.append(f"   • Total Messages: {len(parent_messages)}")
        output_lines.append(f"   • Total Thread Replies: {total_replies}")
        output_lines.append(
            f"   • Active Threads: {len([ts for ts, replies in thread_replies.items() if replies])}"
        )

        return "\n".join(output_lines)

    async def _format_message_for_llm(
        self,
        message: Dict[str, Any],
        channel_id: str,
        is_thread_reply: bool = False,
    ) -> str:
        """Format a single message optimized for LLM consumption"""
        user_info = message.get("user_info", {})
        user_name = user_info.get("real_name", "Unknown User")
        text = message.get("text", "")

        # Format timestamp
        timestamp = datetime.fromtimestamp(
            float(message.get("ts", ""))
        ).strftime("%Y-%m-%d %H:%M")
        relative_time = self.format_relative_time(
            datetime.fromtimestamp(float(message.get("ts", "")))
        )

        # Format user mentions
        formatted_text = await self.format_user_mentions(text)

        # Extract and enrich JIRA tickets inline
        jira_tickets = self.extract_jira_tickets(formatted_text)
        if jira_tickets:
            for ticket in jira_tickets:
                try:
                    ticket_info = await self.get_ticket_info(ticket)
                    ticket_metadata = self.format_ticket_metadata(ticket_info)
                    # Replace ticket reference with enriched version
                    formatted_text = formatted_text.replace(
                        ticket, f"{ticket} {ticket_metadata}"
                    )
                except Exception as e:
                    self.logger.warning(
                        f"Could not enrich JIRA ticket {ticket}: {e}"
                    )

        # Handle file attachments
        files = message.get("files", [])
        if files:
            file_info = []
            for file in files:
                file_name = file.get("name", "unknown")
                file_type = file.get("mimetype", "unknown")
                file_info.append(f"{file_name} ({file_type})")
            formatted_text += f"\n    📎 Files: {', '.join(file_info)}"

        # Handle reactions
        reactions = message.get("reactions", [])
        if reactions:
            reaction_strs = []
            for reaction in reactions:
                name = reaction.get("name", "")
                count = reaction.get("count", 0)
                reaction_strs.append(f"{name}({count})")
            formatted_text += f"\n    😊 Reactions: {', '.join(reaction_strs)}"

        # Format the complete message
        indent = "    " if is_thread_reply else ""
        return f"{indent}👤 {user_name} at {timestamp} ({relative_time}):\n{indent}   {formatted_text}"


# Example usage
if __name__ == "__main__":
    logger = logging.getLogger(__name__)
    logger.info("Starting Slack Channel processing")

    # Example channels configuration - replace with your own channel IDs
    CHANNELS_OF_INTEREST = [
        {"name": "general", "id": "C0123456789"},
        {"name": "engineering", "id": "C9876543210"},
        # Add more channels as needed
    ]

    async def main() -> None:
        from rich.console import Console
        from rich.panel import Panel
        from rich.progress import Progress, SpinnerColumn, TextColumn

        console = Console()
        slack_manager = SlackChannelManager()

        # Configuration - focusing on LLM-optimized text generation
        channels = [
            SlackChannel(name=ch["name"], id=ch["id"])
            for ch in CHANNELS_OF_INTEREST
        ]
        time_window = TimeWindow(days=4, hours=0)  # Look back 4 days

        # Header
        console.print(
            Panel.fit(
                "[bold blue]🤖 LLM-Optimized Slack Channel Text Generation[/bold blue]\n"
                f"Processing {len(channels)} channels for optimal LLM consumption\n"
                f"Time window: {time_window.days} days {time_window.hours} hours (expanded to capture thread parents)",
                border_style="blue",
            )
        )

        # Process each channel and generate LLM-optimized text
        for channel in channels:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                task = progress.add_task(
                    f"Processing {channel.name}...", total=None
                )

                # Generate LLM-optimized text
                llm_text = await slack_manager.generate_llm_optimized_text(
                    channel, time_window
                )
                progress.update(task, completed=True)

            # Display the LLM-optimized output
            console.print(
                Panel.fit(
                    f"[bold green]📝 LLM-Optimized Text Output for {channel.name}[/bold green]",
                    border_style="green",
                )
            )

            # Show a preview of the formatted text (first 2000 chars for readability)
            preview_text = (
                llm_text[:2000] + "..." if len(llm_text) > 2000 else llm_text
            )
            console.print(
                "[bold cyan]📝 LLM-Ready Text Preview (first 2000 chars):[/bold cyan]"
            )
            console.print(f"[dim]{preview_text}[/dim]")

            # Display text statistics
            console.print(
                f"\n[bold cyan]📊 Text Statistics for {channel.name}:[/bold cyan]"
            )
            lines = llm_text.split("\n")
            message_lines = [
                line
                for line in lines
                if line.strip().startswith("💬 MESSAGE #")
            ]
            thread_lines = [line for line in lines if "↳ REPLY #" in line]
            jira_matches = len(
                slack_manager.extract_jira_tickets(llm_text) or []
            )

            console.print(
                f"  • Total text length: {len(llm_text):,} characters"
            )
            console.print(f"  • Total lines: {len(lines):,}")
            console.print(f"  • Parent messages: {len(message_lines)}")
            console.print(f"  • Thread replies: {len(thread_lines)}")
            console.print(f"  • JIRA tickets mentioned: {jira_matches}")
            console.print()

            # Option to save to file for actual LLM processing
            if len(llm_text) > 500:  # Only for non-empty channels
                filename = f"llm_output_{channel.name}_{time_window.days}d.txt"
                console.print(
                    f"[bold yellow]💾 Saving full output to: {filename}[/bold yellow]"
                )
                try:
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(llm_text)
                    console.print(
                        f"[green]✅ Saved {len(llm_text):,} characters to {filename}[/green]"
                    )
                except Exception as e:
                    console.print(f"[red]❌ Error saving file: {e}[/red]")

            console.print("-" * 80)
            console.print()

        # Final summary
        console.print(
            Panel.fit(
                "[bold blue]🎯 LLM Processing Ready[/bold blue]\n"
                "Text files have been generated with optimal formatting for LLM consumption:\n"
                "• Messages and threads are spatially clustered\n"
                "• JIRA tickets are enriched with metadata\n"
                "• Chronological order is preserved\n"
                "• Content is optimized for context understanding",
                border_style="blue",
            )
        )

    # Run the async main function
    asyncio.run(main())
