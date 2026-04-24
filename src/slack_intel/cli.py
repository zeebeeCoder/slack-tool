"""CLI interface for Slack Intelligence tool"""

import asyncio
import click
import duckdb
import yaml
from pathlib import Path
from datetime import datetime
from typing import List, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
import json

from .slack_channels import SlackChannelManager, SlackChannel, TimeWindow
from .parquet_cache import ParquetCache
from .utils import convert_slack_dicts_to_messages
from .parquet_user_reader import ParquetUserReader
from .thread_reconstructor import ThreadReconstructor
from .message_view_formatter import MessageViewFormatter, ViewContext
from .sql_view_composer import SqlViewComposer
from .enriched_message_view_formatter import EnrichedMessageViewFormatter
from .s3_sync import create_syncer

console = Console()


# Default channels configuration
DEFAULT_CHANNELS = [
    {"name": "general", "id": "C0123456789"},
    {"name": "engineering", "id": "C9876543210"},
    {"name": "random", "id": "C1111111111"},
]


def load_config() -> List[dict]:
    """Load channels from config file or use defaults (legacy format)

    Looks for .slack-intel.yaml in current directory or home directory.
    Falls back to DEFAULT_CHANNELS if no config found.

    Returns: List of {"name": str, "id": str} channel dicts
    """
    from .config import load_config as load_full_config, get_channel_list_for_legacy_code

    try:
        full_config = load_full_config()
        return get_channel_list_for_legacy_code(full_config)
    except Exception as e:
        # Fallback to defaults
        return DEFAULT_CHANNELS


def load_full_config_with_fallback():
    """Load full SlackIntelConfig with organization context

    Returns: SlackIntelConfig object
    """
    from .config import load_config as load_full_config

    return load_full_config()


@click.group()
def cli():
    """Slack Intelligence - Cache and query Slack messages in Parquet format"""
    pass


@cli.command()
@click.option('--config-only', is_flag=True, help='Only create config file, skip credential prompts')
def setup(config_only):
    """Interactive setup for slack-intel configuration

    This command helps you set up slack-intel for the first time by:
    1. Creating the config directory (~/.config/slack-intel/)
    2. Prompting for API credentials (Slack, JIRA, OpenAI)
    3. Testing Slack connection
    4. Generating initial organizational config
    5. Setting secure file permissions

    You can also run `config init` afterward to add organizational context.
    """
    import os
    import stat
    from .credentials import check_config_file_security

    console.print(Panel.fit(
        "[bold cyan]Slack Intelligence Setup[/bold cyan]\n"
        "This wizard will help you configure slack-intel",
        border_style="cyan"
    ))
    console.print()

    # Create config directory
    config_dir = Path.home() / ".config" / "slack-intel"
    config_file = config_dir / "config.yaml"

    if not config_dir.exists():
        config_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created config directory: {config_dir}")
    else:
        console.print(f"[dim]Config directory exists: {config_dir}[/dim]")

    # Check if config already exists
    if config_file.exists() and not config_only:
        console.print()
        overwrite = click.confirm(
            f"Config file already exists at {config_file}. Overwrite?",
            default=False
        )
        if not overwrite:
            console.print("[yellow]Setup cancelled.[/yellow]")
            return

    console.print()

    # Gather credentials (unless config-only mode)
    credentials = {}
    if not config_only:
        console.print("[bold]Step 1: API Credentials[/bold]")
        console.print("[dim]You can also set these as environment variables later[/dim]")
        console.print()

        # Slack token
        console.print("[cyan]Slack API Token[/cyan]")
        console.print("Get your token from: https://api.slack.com/apps")
        slack_token = click.prompt(
            "Enter Slack Bot Token (xoxb-...) or User Token (xoxp-...)",
            hide_input=True,
            default="",
            show_default=False
        )

        if slack_token:
            if slack_token.startswith("xoxp-"):
                credentials.setdefault("slack", {})["user_token"] = slack_token
            elif slack_token.startswith("xoxb-"):
                credentials.setdefault("slack", {})["bot_token"] = slack_token
            else:
                console.print("[yellow]Warning: Token doesn't start with xoxp- or xoxb-[/yellow]")
                credentials.setdefault("slack", {})["bot_token"] = slack_token

        console.print()

        # JIRA credentials
        console.print("[cyan]JIRA Credentials[/cyan]")
        console.print("Get your API token from: https://id.atlassian.com/manage-profile/security/api-tokens")
        jira_server = click.prompt(
            "JIRA Server URL (e.g., https://your-domain.atlassian.net)",
            default="",
            show_default=False
        )
        jira_username = click.prompt(
            "JIRA Username/Email",
            default="",
            show_default=False
        )
        jira_token = click.prompt(
            "JIRA API Token",
            hide_input=True,
            default="",
            show_default=False
        )

        if jira_server or jira_username or jira_token:
            credentials.setdefault("jira", {})
            if jira_server:
                credentials["jira"]["server"] = jira_server
            if jira_username:
                credentials["jira"]["username"] = jira_username
            if jira_token:
                credentials["jira"]["api_token"] = jira_token

        console.print()

        # OpenAI API key (optional)
        console.print("[cyan]OpenAI API Key (Optional)[/cyan]")
        console.print("Only needed for `process` command with LLM analysis")
        console.print("Get your key from: https://platform.openai.com/api-keys")
        openai_key = click.prompt(
            "OpenAI API Key (sk-...)",
            hide_input=True,
            default="",
            show_default=False
        )

        if openai_key:
            credentials.setdefault("openai", {})["api_key"] = openai_key

        # Test Slack connection if token provided
        if slack_token:
            console.print()
            console.print("[bold]Testing Slack connection...[/bold]")
            try:
                # Temporarily set env var for testing
                os.environ["SLACK_API_TOKEN"] = slack_token
                manager = SlackChannelManager()
                # Try to list channels (will validate token)
                console.print("[green]✓[/green] Slack connection successful!")
            except Exception as e:
                console.print(f"[yellow]⚠[/yellow]  Could not verify Slack connection: {e}")
                console.print("[dim]You can continue anyway and fix the token later[/dim]")

    console.print()
    console.print("[bold]Step 2: Creating configuration file[/bold]")

    # Build config structure
    config_data = {
        "organization": {
            "name": "My Organization",
            "description": "Organization description",
            "stakeholders": [],
            "stakeholder_context": ""
        },
        "channels": [],
        "cache": {
            "path": "~/.cache/slack-intel"
        }
    }

    # Add credentials if provided
    if credentials:
        config_data["credentials"] = credentials

    # Add JIRA server to jira section (backward compatibility)
    if credentials.get("jira", {}).get("server"):
        config_data["jira"] = {"server": credentials["jira"]["server"]}

    # Write config file
    try:
        with open(config_file, 'w') as f:
            yaml.dump(config_data, f, default_flow_style=False, sort_keys=False)
        console.print(f"[green]✓[/green] Created config file: {config_file}")

        # Set secure permissions (600 - owner read/write only)
        config_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
        console.print("[green]✓[/green] Set secure file permissions (600)")

    except Exception as e:
        console.print(f"[red]✗[/red] Failed to create config: {e}")
        return

    # Create cache directory
    console.print()
    cache_dir = Path.home() / ".cache" / "slack-intel"
    if not cache_dir.exists():
        cache_dir.mkdir(parents=True, exist_ok=True)
        console.print(f"[green]✓[/green] Created cache directory: {cache_dir}")

    # Success summary
    console.print()
    console.print(Panel.fit(
        "[bold green]Setup Complete! [/bold green]\n\n"
        f"Config file: {config_file}\n"
        f"Cache directory: {cache_dir}\n\n"
        "[bold]Next steps:[/bold]\n"
        "1. Run `slack-intel config init` to generate organizational context\n"
        "2. Run `slack-intel cache --channel <channel-name>` to start caching\n"
        "3. Run `slack-intel view --channel <channel-name>` to view messages",
        border_style="green"
    ))

    # Security reminder
    if credentials:
        console.print()
        console.print("[yellow]Security Note:[/yellow]")
        console.print("Your credentials are stored in the config file with secure permissions (600).")
        console.print("For production/shared systems, consider using environment variables instead:")
        console.print("  export SLACK_API_TOKEN='your-token'")
        console.print("  export JIRA_API_TOKEN='your-token'")
        console.print("  export OPENAI_API_KEY='your-key'")


@cli.command()
@click.option('--channel', '-c', multiple=True, help='Channel ID(s) to cache (overrides config)')
@click.option('--days', '-d', default=7, help='Days to look back (default: 7)')
@click.option('--end-date', help='End date for window YYYY-MM-DD (default: today)')
@click.option('--cache-path', default='cache/raw', help='Cache directory (default: cache/raw)')
@click.option('--enrich-jira', is_flag=True, help='Fetch and cache JIRA ticket metadata')
def cache(channel, days, end_date, cache_path, enrich_jira):
    """Fetch messages from Slack and save to Parquet cache

    Examples:
        \b
        # Cache last 7 days from default channels (default)
        slack-intel cache

        \b
        # Cache last 30 days
        slack-intel cache --days 30

        \b
        # Cache specific channel
        slack-intel cache --channel C9876543210 --days 3

        \b
        # Cache 7 days ending on specific date
        slack-intel cache --days 7 --end-date 2025-10-20

        \b
        # Cache with JIRA enrichment
        slack-intel cache --enrich-jira --days 7
    """
    asyncio.run(_cache_async(channel, days, end_date, cache_path, enrich_jira))


async def _cache_async(channel_ids, days, end_date, cache_path, enrich_jira):
    """Async implementation of cache command"""

    # Determine channels to process
    if channel_ids:
        # Use CLI-provided channels
        channels = [SlackChannel(name=f"channel_{ch_id}", id=ch_id) for ch_id in channel_ids]
        console.print(f"[dim]Using {len(channels)} channel(s) from CLI arguments[/dim]")
    else:
        # Load from config
        config_channels = load_config()
        channels = [SlackChannel(name=ch["name"], id=ch["id"]) for ch in config_channels]
        console.print(f"[dim]Using {len(channels)} channel(s) from config[/dim]")

    # Initialize
    manager = SlackChannelManager()
    parquet_cache = ParquetCache(base_path=cache_path)
    time_window = TimeWindow(days=days, hours=0)
    date_str = end_date or datetime.now().strftime("%Y-%m-%d")

    # Header
    console.print(Panel.fit(
        f"[bold blue]📦 Slack to Parquet Cache[/bold blue]\n"
        f"Processing {len(channels)} channels\n"
        f"Time window: {days} days (ending {date_str})\n"
        f"Cache path: {cache_path}\n"
        f"Partitioning: By message timestamp (not cache date)\n"
        f"JIRA enrichment: {'[green]enabled[/green]' if enrich_jira else '[dim]disabled[/dim]'}",
        border_style="blue"
    ))

    # Results table and JIRA ticket collection
    results = []
    all_jira_ticket_ids = set()  # Collect unique JIRA tickets across all channels
    all_mentioned_user_ids = set()  # Collect unique mentioned users across all channels

    # Process each channel
    for channel in channels:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task(
                f"[cyan]Fetching {channel.name}...", total=None
            )

            try:
                # Fetch messages from Slack
                raw_messages = await manager.get_messages(
                    channel.id,
                    time_window.start_time,
                    time_window.end_time
                )

                if not raw_messages:
                    console.print(f"[yellow]  ⚠ No messages found in {channel.name}[/yellow]")
                    results.append({
                        "channel": channel.name,
                        "messages": 0,
                        "status": "empty",
                        "path": "-"
                    })
                    continue

                # Convert to SlackMessage objects
                messages = convert_slack_dicts_to_messages(raw_messages)

                progress.update(task, description=f"[cyan]Caching {channel.name} ({len(messages)} messages)...")

                # Group messages by their actual date (from timestamp)
                # This allows querying by message date, not cache date
                from collections import defaultdict

                messages_by_date = defaultdict(list)
                for msg in messages:
                    # Extract date from message timestamp (which is already a datetime object)
                    try:
                        if hasattr(msg, 'timestamp') and msg.timestamp:
                            # msg.timestamp is a datetime object, format it directly
                            msg_date = msg.timestamp.strftime('%Y-%m-%d')
                            messages_by_date[msg_date].append(msg)
                        else:
                            # No timestamp, use partition date
                            messages_by_date[date_str].append(msg)
                    except (ValueError, AttributeError, TypeError):
                        # Fallback to partition_date if timestamp is invalid
                        messages_by_date[date_str].append(msg)

                # Save messages partitioned by their actual date
                total_size = 0
                partition_paths = []
                for msg_date, date_messages in sorted(messages_by_date.items()):
                    file_path = parquet_cache.save_messages(date_messages, channel, msg_date)
                    partition_paths.append(file_path)
                    total_size += Path(file_path).stat().st_size

                # Extract JIRA tickets from messages if enrichment is enabled
                if enrich_jira:
                    for message in messages:
                        jira_tickets = message.to_parquet_dict().get('jira_tickets', [])
                        if jira_tickets:
                            all_jira_ticket_ids.update(jira_tickets)

                # Extract user mentions from message text for user cache
                import re
                mention_pattern = r'<@(U[A-Z0-9]+)>'
                for message in messages:
                    message_text = message.text if hasattr(message, 'text') else ""
                    if message_text:
                        mentions = re.findall(mention_pattern, message_text)
                        all_mentioned_user_ids.update(mentions)

                # Calculate total size
                file_size_mb = total_size / (1024 * 1024)

                # Format partition info
                if len(partition_paths) > 1:
                    date_range = f"{min(messages_by_date.keys())} to {max(messages_by_date.keys())}"
                    path_info = f"{len(partition_paths)} partitions: {date_range}"
                elif len(partition_paths) == 1:
                    path_info = partition_paths[0]
                else:
                    path_info = "-"

                results.append({
                    "channel": channel.name,
                    "messages": len(messages),
                    "status": "cached",
                    "path": path_info,
                    "size_mb": file_size_mb
                })

                console.print(f"[green]  ✓ Cached {len(messages)} messages from {channel.name}[/green]")

            except Exception as e:
                import traceback
                console.print(f"[red]  ✗ Error processing {channel.name}: {e}[/red]")
                console.print(f"[dim]{traceback.format_exc()}[/dim]")
                results.append({
                    "channel": channel.name,
                    "messages": 0,
                    "status": "error",
                    "path": str(e)
                })

    # Summary table
    if results:
        console.print()
        table = Table(title="Cache Summary", show_header=True, header_style="bold cyan")
        table.add_column("Channel", style="cyan")
        table.add_column("Messages", justify="right")
        table.add_column("Size (MB)", justify="right")
        table.add_column("Status")
        table.add_column("Path", overflow="fold")

        for result in results:
            status_color = "green" if result["status"] == "cached" else "yellow" if result["status"] == "empty" else "red"
            table.add_row(
                result["channel"],
                str(result["messages"]),
                f"{result.get('size_mb', 0):.2f}" if result["status"] == "cached" else "-",
                f"[{status_color}]{result['status']}[/{status_color}]",
                result["path"]
            )

        console.print(table)

        # Overall stats
        total_messages = sum(r["messages"] for r in results)
        total_size = sum(r.get("size_mb", 0) for r in results)
        console.print(f"\n[bold]Total:[/bold] {total_messages} messages, {total_size:.2f} MB cached")

    # JIRA Enrichment Phase
    if enrich_jira and all_jira_ticket_ids:
        console.print()
        console.print(Panel.fit(
            f"[bold cyan]🎫 JIRA Enrichment Phase[/bold cyan]\n"
            f"Fetching metadata for {len(all_jira_ticket_ids)} unique tickets",
            border_style="cyan"
        ))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task(
                f"[cyan]Fetching {len(all_jira_ticket_ids)} JIRA tickets...",
                total=len(all_jira_ticket_ids)
            )

            try:
                # Fetch JIRA tickets in parallel
                jira_tickets = await manager.fetch_jira_tickets_batch(
                    list(all_jira_ticket_ids)
                )
                progress.update(task, completed=len(all_jira_ticket_ids))

                # Save JIRA tickets to cache
                if jira_tickets:
                    jira_path = parquet_cache.save_jira_tickets(jira_tickets, date_str)
                    jira_file_size = Path(jira_path).stat().st_size / (1024 * 1024)

                    console.print(
                        f"[green]  ✓ Cached {len(jira_tickets)} JIRA tickets "
                        f"({jira_file_size:.2f} MB)[/green]"
                    )
                    console.print(f"[dim]  Path: {jira_path}[/dim]")

                    # Show warnings if some tickets failed
                    failed_count = len(all_jira_ticket_ids) - len(jira_tickets)
                    if failed_count > 0:
                        console.print(
                            f"[yellow]  ⚠ {failed_count} tickets failed to fetch "
                            f"(see warnings above)[/yellow]"
                        )
                else:
                    console.print(
                        "[yellow]  ⚠ No JIRA tickets were successfully fetched[/yellow]"
                    )

            except Exception as e:
                console.print(f"[red]  ✗ JIRA enrichment failed: {e}[/red]")

    elif enrich_jira and not all_jira_ticket_ids:
        console.print()
        console.print("[yellow]No JIRA tickets found in messages[/yellow]")

    # User Cache Enrichment Phase (always runs)
    if all_mentioned_user_ids:
        console.print()
        console.print(Panel.fit(
            f"[bold cyan]👥 User Cache Enrichment Phase[/bold cyan]\n"
            f"Fetching profiles for {len(all_mentioned_user_ids)} unique mentioned users",
            border_style="cyan"
        ))

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console
        ) as progress:
            task = progress.add_task(
                f"[cyan]Fetching {len(all_mentioned_user_ids)} user profiles...",
                total=len(all_mentioned_user_ids)
            )

            try:
                # Fetch user info in parallel using existing manager infrastructure
                # The manager already has user_cache populated with message authors
                # Now we'll fill in mentioned users who might not be authors

                semaphore = asyncio.Semaphore(10)  # Limit concurrent requests

                async def fetch_user_safe(user_id: str):
                    """Fetch user info with rate limiting"""
                    async with semaphore:
                        if user_id not in manager.user_cache:
                            try:
                                await manager.get_user_info(user_id)
                            except Exception as e:
                                console.print(f"[dim]  Warning: Could not fetch user {user_id}: {e}[/dim]")

                # Fetch all mentioned users
                await asyncio.gather(*[fetch_user_safe(uid) for uid in all_mentioned_user_ids])
                progress.update(task, completed=len(all_mentioned_user_ids))

                # Save user cache to global Parquet file
                if manager.user_cache:
                    from datetime import datetime as dt
                    import pyarrow as pa
                    import pyarrow.parquet as pq

                    # Save to parent of cache_path (e.g., cache/users.parquet when cache_path=cache/raw)
                    users_cache_path = Path(cache_path).parent / "users.parquet"

                    # Load existing users if file exists
                    existing_users = {}
                    if users_cache_path.exists():
                        try:
                            existing_table = pq.read_table(str(users_cache_path))
                            existing_df = existing_table.to_pydict()
                            for i in range(len(existing_df['user_id'])):
                                user_id = existing_df['user_id'][i]
                                existing_users[user_id] = {
                                    'user_id': user_id,
                                    'user_name': existing_df['user_name'][i],
                                    'user_real_name': existing_df['user_real_name'][i],
                                    'user_email': existing_df.get('user_email', [None] * len(existing_df['user_id']))[i],
                                    'is_bot': existing_df.get('is_bot', [False] * len(existing_df['user_id']))[i],
                                    'cached_at': existing_df.get('cached_at', [None] * len(existing_df['user_id']))[i]
                                }
                        except Exception as e:
                            console.print(f"[yellow]  ⚠ Could not load existing user cache: {e}[/yellow]")

                    # Merge with new users (upsert)
                    cached_at = dt.now().isoformat()
                    for user_id, user_data in manager.user_cache.items():
                        existing_users[user_id] = {
                            'user_id': user_id,
                            'user_name': user_data.get('name'),
                            'user_real_name': user_data.get('real_name'),
                            'user_email': user_data.get('profile', {}).get('email') if isinstance(user_data, dict) else None,
                            'is_bot': user_data.get('is_bot', False) if isinstance(user_data, dict) else False,
                            'cached_at': cached_at
                        }

                    # Convert to PyArrow table
                    users_list = list(existing_users.values())
                    table = pa.Table.from_pylist(users_list)

                    # Save to Parquet
                    users_cache_path.parent.mkdir(parents=True, exist_ok=True)
                    pq.write_table(table, str(users_cache_path))

                    file_size = users_cache_path.stat().st_size / (1024 * 1024)
                    console.print(
                        f"[green]  ✓ Cached {len(existing_users)} users "
                        f"({file_size:.2f} MB)[/green]"
                    )
                    console.print(f"[dim]  Path: {users_cache_path}[/dim]")
                else:
                    console.print("[yellow]  ⚠ No users to cache[/yellow]")

            except Exception as e:
                console.print(f"[red]  ✗ User cache enrichment failed: {e}[/red]")
                import traceback
                console.print(f"[dim]{traceback.format_exc()}[/dim]")

    elif all_mentioned_user_ids:
        console.print()
        console.print("[dim]No mentioned users found in messages[/dim]")


@cli.command()
@click.option('--query', '-q', help='SQL query to run')
@click.option('--interactive', '-i', is_flag=True, help='Interactive SQL mode (REPL)')
@click.option('--cache-path', default='cache/raw', help='Cache directory (default: cache/raw)')
@click.option('--format', type=click.Choice(['table', 'json', 'csv']), default='table', help='Output format')
@click.option('--limit', '-l', default=100, help='Limit rows in output (default: 100)')
def query(query, interactive, cache_path, format, limit):
    """Query cached messages with SQL (DuckDB)

    Examples:
        \b
        # Run a SQL query
        slack-intel query -q "SELECT user_real_name, COUNT(*) FROM 'cache/raw/messages/**/*.parquet' GROUP BY user_real_name"

        \b
        # Interactive mode
        slack-intel query --interactive

        \b
        # Export as JSON
        slack-intel query -q "SELECT * FROM 'cache/raw/messages/**/*.parquet' WHERE dt='2023-10-18'" --format json
    """
    messages_path = Path(cache_path) / "messages"

    if not messages_path.exists():
        console.print(f"[red]Error: Cache directory not found: {messages_path}[/red]")
        console.print(f"[yellow]Run 'slack-intel cache' first to create cache.[/yellow]")
        return

    conn = duckdb.connect()

    if interactive:
        _interactive_query(conn, cache_path)
    elif query:
        _run_query(conn, query, cache_path, format, limit)
    else:
        console.print("[yellow]Please specify --query or --interactive[/yellow]")
        console.print("Example: slack-intel query -q \"SELECT * FROM 'cache/raw/messages/**/*.parquet' LIMIT 10\"")


def _run_query(conn, sql_query, cache_path, output_format, limit):
    """Execute a single SQL query"""
    try:
        # Add LIMIT if not present in query
        if "limit" not in sql_query.lower() and limit:
            sql_query = f"{sql_query} LIMIT {limit}"

        result = conn.execute(sql_query).fetchdf()

        if output_format == 'json':
            console.print(result.to_json(orient='records', indent=2))
        elif output_format == 'csv':
            console.print(result.to_csv(index=False))
        else:  # table
            if len(result) == 0:
                console.print("[yellow]No results found[/yellow]")
                return

            table = Table(show_header=True, header_style="bold cyan")

            # Add columns
            for col in result.columns:
                table.add_column(col)

            # Add rows (limit to avoid overwhelming output)
            for _, row in result.head(limit).iterrows():
                table.add_row(*[str(val) for val in row])

            console.print(table)
            console.print(f"\n[dim]Showing {min(len(result), limit)} of {len(result)} rows[/dim]")

    except Exception as e:
        console.print(f"[red]Query error: {e}[/red]")


def _interactive_query(conn, cache_path):
    """Interactive SQL REPL"""
    console.print(Panel.fit(
        "[bold blue]Interactive Query Mode[/bold blue]\n"
        "Type SQL queries to execute. Type 'exit' or 'quit' to leave.\n"
        f"Cache path: {cache_path}/messages/**/*.parquet",
        border_style="blue"
    ))

    # Sample queries
    console.print("\n[dim]Sample queries:[/dim]")
    samples = [
        "SELECT COUNT(*) FROM 'cache/raw/messages/**/*.parquet'",
        "SELECT user_real_name, COUNT(*) as msg_count FROM 'cache/raw/messages/**/*.parquet' GROUP BY user_real_name",
        "SELECT * FROM read_parquet('cache/raw/messages/**/*.parquet', hive_partitioning=1) WHERE dt='2023-10-18'",
    ]
    for i, sample in enumerate(samples, 1):
        console.print(f"  [cyan]{i}.[/cyan] {sample}")

    console.print()

    while True:
        try:
            query = console.input("[bold green]sql>[/bold green] ").strip()

            if query.lower() in ('exit', 'quit', '\\q'):
                console.print("[yellow]Goodbye![/yellow]")
                break

            if not query:
                continue

            _run_query(conn, query, cache_path, 'table', 100)

        except KeyboardInterrupt:
            console.print("\n[yellow]Use 'exit' to quit[/yellow]")
        except EOFError:
            break


@cli.command()
@click.option('--cache-path', default='cache/raw', help='Cache directory (default: cache/raw)')
@click.option('--format', type=click.Choice(['table', 'json']), default='table', help='Output format')
def stats(cache_path, format):
    """Show cache statistics and partition info

    Examples:
        \b
        # Show cache stats
        slack-intel stats

        \b
        # Export as JSON
        slack-intel stats --format json
    """
    parquet_cache = ParquetCache(base_path=cache_path)

    try:
        info = parquet_cache.get_partition_info()

        if format == 'json':
            console.print(json.dumps(info, indent=2))
            return

        # Display as Rich table
        if info["total_partitions"] == 0:
            console.print(f"[yellow]No cache found at: {cache_path}[/yellow]")
            console.print("[dim]Run 'slack-intel cache' to create cache.[/dim]")
            return

        # Summary panel
        console.print(Panel.fit(
            f"[bold blue]Cache Statistics[/bold blue]\n"
            f"Total partitions: {info['total_partitions']}\n"
            f"Total messages: {info['total_messages']:,}\n"
            f"Total size: {info['total_size_bytes'] / (1024 * 1024):.2f} MB\n"
            f"Cache path: {cache_path}",
            border_style="blue"
        ))

        # Partition table
        if info["partitions"]:
            table = Table(title="Partitions", show_header=True, header_style="bold cyan")
            table.add_column("Path", overflow="fold")
            table.add_column("Messages", justify="right")
            table.add_column("Size (KB)", justify="right")

            for partition in info["partitions"]:
                table.add_row(
                    partition["path"],
                    str(partition["row_count"]),
                    f"{partition['size_bytes'] / 1024:.1f}"
                )

            console.print()
            console.print(table)

    except Exception as e:
        console.print(f"[red]Error reading cache: {e}[/red]")


@cli.command()
@click.option('--channel', '-c', multiple=True, help='Channel name(s) to view')
@click.option('--merge-channels', is_flag=True, help='Merge all channels from manifest')
@click.option('--user', '-u', help='Filter messages by username (e.g., zeebee)')
@click.option('--include-mentions', is_flag=True, help='Include threads where user was mentioned')
@click.option('--bucket-by', type=click.Choice(['hour', 'day', 'none']), default='hour',
              help='Time bucketing for multi-channel view (default: hour)')
@click.option('--days', '-d', default=7, help='Days to look back (default: 7)')
@click.option('--end-date', help='End date for window YYYY-MM-DD (default: today)')
@click.option('--cache-path', default='cache', help='Cache directory (default: cache)')
@click.option('--output', '-o', help='Output file (default: print to console)')
@click.option('--auto-save', is_flag=True, help='Auto-save to timestamped file (e.g., backend-devs_2025-10-20_143022.txt)')
def view(channel, merge_channels, user, include_mentions, bucket_by, days, end_date, cache_path, output, auto_save):
    """Generate formatted message view from Parquet cache

    Examples:
        \\b
        # View last 7 days from single channel (default)
        slack-intel view --channel backend-devs

        \\b
        # View last 30 days
        slack-intel view --channel backend-devs --days 30

        \\b
        # View 7 days ending on specific date
        slack-intel view --channel backend-devs --days 7 --end-date 2025-10-20

        \\b
        # Merge ALL channels from manifest
        slack-intel view --merge-channels --days 14

        \\b
        # User timeline across all channels
        slack-intel view --user zeebee --days 30

        \\b
        # User timeline in specific channels with mentions
        slack-intel view --user zeebee -c backend-devs --include-mentions

        \\b
        # Save to file
        slack-intel view -c general --days 1 -o output.txt

        \\b
        # Auto-save with timestamped filename
        slack-intel view -c backend-devs --days 7 --auto-save
        # → saves to backend-devs_2025-10-20_143022.txt
    """
    try:
        # Determine channels to view
        channels_to_view = []
        is_user_timeline = bool(user)

        if is_user_timeline:
            # User timeline mode
            if channel:
                # Use specified channels for user timeline
                channels_to_view = list(channel)
                console.print(f"[dim]User timeline in {len(channels_to_view)} channel(s)[/dim]")
            else:
                # Default: search all channels from manifest
                config_channels = load_config()
                channels_to_view = [ch["name"] for ch in config_channels]
                console.print(f"[dim]User timeline across {len(channels_to_view)} channels[/dim]")
        elif merge_channels:
            # Load all channels from manifest
            config_channels = load_config()
            channels_to_view = [ch["name"] for ch in config_channels]
            console.print(f"[dim]Merging {len(channels_to_view)} channels from manifest[/dim]")
        elif channel:
            # Use specified channels
            channels_to_view = list(channel)
            console.print(f"[dim]Viewing {len(channels_to_view)} channel(s)[/dim]")
        else:
            console.print("[red]Error: Must specify --channel, --merge-channels, or --user[/red]")
            console.print("[yellow]Examples:[/yellow]")
            console.print("  slack-intel view --channel backend-devs")
            console.print("  slack-intel view --merge-channels")
            console.print("  slack-intel view --user zeebee")
            return

        # Initialize SQL view composer and user reader
        composer = SqlViewComposer(base_path=cache_path)
        user_reader = ParquetUserReader(base_path=cache_path)

        # Load cached users for mention resolution
        console.print("[dim]Loading user cache...[/dim]")
        cached_users = user_reader.read_users()
        if cached_users:
            console.print(f"[dim]Loaded {len(cached_users)} users from cache[/dim]")
        else:
            console.print("[dim]No user cache found (mentions may not be resolved)[/dim]")

        # Normalize channel names (handle "channel_" prefix)
        def normalize_channel_name(channel_name: str) -> str:
            """Try both exact name and with 'channel_' prefix"""
            # For multi-channel, we'll try the exact name first
            # The composer will handle fallback internally
            if not channel_name.startswith("channel_"):
                # Check if data exists for exact name or prefixed name
                return channel_name
            return channel_name

        normalized_channels = [normalize_channel_name(ch) for ch in channels_to_view]

        # Determine date range using unified days parameter
        from datetime import timedelta
        if end_date:
            end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")
        else:
            end_date_dt = datetime.now()

        start_date_dt = end_date_dt - timedelta(days=days - 1)  # -1 because end date is inclusive
        start_date = start_date_dt.strftime("%Y-%m-%d")
        end_date = end_date_dt.strftime("%Y-%m-%d")

        if days == 1:
            date_range_str = end_date
        else:
            date_range_str = f"{start_date} to {end_date}"

        # Read messages based on user timeline vs regular view
        if is_user_timeline:
            # User timeline mode - fetch user's messages across channels
            # Resolve username to user_id and get actual user_name
            user_id = user_reader.find_user_by_name(user)
            if not user_id:
                console.print(f"[yellow]Could not find user '{user}' in cache[/yellow]")
                console.print("[dim]User lookup uses cached data - try a different name or check available users[/dim]")
                return

            # Get the actual user_name from cache (e.g., "tarun465" for display name "Tarun")
            user_data = user_reader.get_user(user_id)
            actual_user_name = user_data.get('user_name') if user_data else user
            user_display_name = user_data.get('user_real_name', actual_user_name) if user_data else user

            console.print(f"[dim]Reading messages from {user_display_name} (@{actual_user_name}) ({date_range_str})...[/dim]")

            # Normalize channel names (try with prefix)
            channels_with_data = []
            for ch in normalized_channels:
                # Try exact name first
                test_messages = composer.read_messages_enriched_range(ch, start_date, end_date)
                if test_messages:
                    channels_with_data.append(ch)
                elif not ch.startswith("channel_"):
                    # Try with prefix
                    prefixed = f"channel_{ch}"
                    test_messages = composer.read_messages_enriched_range(prefixed, start_date, end_date)
                    if test_messages:
                        channels_with_data.append(prefixed)

            if not channels_with_data:
                console.print(f"[yellow]No channel data found for {date_range_str}[/yellow]")
                return

            # Fetch user timeline with SQL-level filtering using actual user_name
            flat_messages = composer.read_user_timeline_enriched(
                user_name=actual_user_name,
                channels=channels_with_data,
                start_date=start_date,
                end_date=end_date,
                include_mentions=include_mentions,
                user_id=user_id
            )
            normalized_channels = channels_with_data

            if not flat_messages:
                console.print(f"[yellow]No messages found from user '{user}' in {date_range_str}[/yellow]")
                console.print("[dim]Try a different date range or verify the username is correct[/dim]")
                return

        elif len(normalized_channels) == 1:
            # Single channel - use original logic
            single_channel = normalized_channels[0]
            console.print(f"[dim]Reading enriched messages from {single_channel} ({date_range_str})...[/dim]")
            flat_messages = composer.read_messages_enriched_range(single_channel, start_date, end_date)

            # Try with channel_ prefix if no messages found
            if not flat_messages and not single_channel.startswith("channel_"):
                prefixed_name = f"channel_{single_channel}"
                flat_messages = composer.read_messages_enriched_range(prefixed_name, start_date, end_date)
                if flat_messages:
                    single_channel = prefixed_name
                    normalized_channels = [prefixed_name]

            if not flat_messages:
                console.print(f"[yellow]No messages found in {single_channel} for {date_range_str}[/yellow]")
                console.print("[dim]Try a different date range or check 'slack-intel stats' to see available data.[/dim]")
                return
        else:
            # Multi-channel - merge all channels
            console.print(f"[dim]Reading enriched messages from {len(normalized_channels)} channels ({date_range_str})...[/dim]")

            # Try both exact names and with prefix
            channels_with_data = []
            for ch in normalized_channels:
                # Try exact name first
                test_messages = composer.read_messages_enriched_range(ch, start_date, end_date)
                if test_messages:
                    channels_with_data.append(ch)
                elif not ch.startswith("channel_"):
                    # Try with prefix
                    prefixed = f"channel_{ch}"
                    test_messages = composer.read_messages_enriched_range(prefixed, start_date, end_date)
                    if test_messages:
                        channels_with_data.append(prefixed)

            if not channels_with_data:
                console.print(f"[yellow]No messages found in any channel for {date_range_str}[/yellow]")
                console.print("[dim]Try a different date range or check 'slack-intel stats' to see available data.[/dim]")
                return

            console.print(f"[dim]Found data in {len(channels_with_data)} channel(s)[/dim]")
            flat_messages = composer.read_multi_channel_messages_enriched(
                channels_with_data,
                start_date,
                end_date
            )
            normalized_channels = channels_with_data

        console.print(f"[green]Found {len(flat_messages)} messages[/green]")

        # Reconstruct threads
        console.print("[dim]Reconstructing thread structure...[/dim]")
        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)

        # Format view with JIRA enrichment
        console.print("[dim]Formatting enriched view...[/dim]")

        # Determine view type and formatter
        is_multi_channel = len(normalized_channels) > 1

        if is_user_timeline:
            # User timeline - no bucketing, show channel names
            user_data = cached_users.get(user_id) if user_id else None
            display_name = user_data.get('user_real_name') if user_data else user

            context = ViewContext(
                channel_name=f"User: {display_name or user}",
                date_range=date_range_str,
                channels=normalized_channels  # Multi-channel for showing channel names
            )
            # No bucketing for user timeline
            formatter = EnrichedMessageViewFormatter(bucket_type=None)
        elif is_multi_channel:
            context = ViewContext(
                channel_name="Multi-Channel",
                date_range=date_range_str,
                channels=normalized_channels
            )
            formatter = EnrichedMessageViewFormatter(bucket_type=bucket_by)
        else:
            context = ViewContext(
                channel_name=normalized_channels[0],
                date_range=date_range_str
            )
            formatter = EnrichedMessageViewFormatter()

        view_output = formatter.format(structured_messages, context, cached_users=cached_users)

        # Resolve output path: explicit -o takes priority, then --auto-save
        if not output and auto_save:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
            if is_user_timeline:
                prefix = f"user-{user}"
            elif merge_channels:
                prefix = "merged"
            elif len(normalized_channels) == 1:
                prefix = normalized_channels[0]
            else:
                prefix = f"{len(normalized_channels)}ch"
            output = f"{prefix}_{timestamp}.txt"

        # Output
        if output:
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(view_output)
            console.print(f"[green]✓ View saved to {output}[/green]")
        else:
            console.print()
            console.print(view_output)

    except Exception as e:
        console.print(f"[red]Error generating view: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


@cli.command()
@click.option('--channel', '-c', multiple=True, help='Channel name(s) to process')
@click.option('--merge-channels', is_flag=True, help='Merge all channels from manifest')
@click.option('--user', '-u', help='Process user timeline across channels')
@click.option('--include-mentions', is_flag=True, help='Include threads where user was mentioned')
@click.option('--bucket-by', type=click.Choice(['hour', 'day', 'none']), default='hour',
              help='Time bucketing for multi-channel view (default: hour)')
@click.option('--days', '-d', default=7, help='Days to look back (default: 7)')
@click.option('--end-date', help='End date for window YYYY-MM-DD (default: today)')
@click.option('--cache-path', default='cache', help='Cache directory (default: cache)')
@click.option('--input', '-i', help='Input file with view output (skip view generation)')
@click.option('--output', '-o', help='Output file for summary (default: print to console)')
@click.option('--model', default='gpt-5', help='OpenAI model (default: gpt-5)')
@click.option('--temperature', default=0.7, type=float, help='Sampling temperature (default: 0.7, not used for GPT-5)')
@click.option('--max-tokens', default=4000, type=int, help='Maximum tokens in response (default: 4000, not used for GPT-5)')
@click.option('--reasoning-effort', type=click.Choice(['low', 'medium', 'high']), default='medium',
              help='Reasoning effort for GPT-5 (default: medium)')
@click.option('--instructions', help='Custom analysis instructions (overrides default prompt)')
@click.option('--instructions-file', type=click.Path(exists=True), help='Load instructions from file')
@click.option('--format', type=click.Choice(['text', 'json']), default='text', help='Output format (default: text)')
def process(channel, merge_channels, user, include_mentions, bucket_by, days, end_date, cache_path, input, output, model, temperature, max_tokens, reasoning_effort, instructions, instructions_file, format):
    """Process Slack messages with LLM to generate summaries and insights

    This command uses OpenAI's API to analyze Slack conversations. It can either:
    1. Generate a view from cache and process it (specify --channel)
    2. Process an existing view file (specify --input)

    Examples:
        \\b
        # Process last 7 days from single channel (default)
        slack-intel process --channel backend-devs

        \\b
        # Process last 30 days
        slack-intel process -c backend-devs --days 30

        \\b
        # Process with GPT-5
        slack-intel process -c backend-devs --model gpt-5 --reasoning-effort high

        \\b
        # Process existing view file
        slack-intel process --input view-output.txt --output summary.txt

        \\b
        # Process with JSON output
        slack-intel process --merge-channels --days 14 --format json -o insights.json

        \\b
        # Use custom parameters
        slack-intel process -c general --temperature 0.5 --max-tokens 2000
    """
    import os
    from .pipeline import ChainProcessor
    from .credentials import get_openai_key, CredentialError

    # Check for OpenAI API key (env var or config file)
    try:
        openai_api_key = get_openai_key()
    except CredentialError as e:
        console.print("[red]Error: OpenAI API key not found[/red]")
        console.print("[yellow]Please set your OpenAI API key:[/yellow]")
        console.print("  Option 1: Environment variable")
        console.print("    export OPENAI_API_KEY='your-api-key-here'")
        console.print("  Option 2: Config file")
        console.print("    Run 'slack-intel setup' to configure")
        return

    try:
        # Load custom instructions if provided
        custom_instructions = None
        if instructions_file:
            # Load from file
            instructions_path = Path(instructions_file)
            console.print(f"[dim]Loading custom instructions from {instructions_file}...[/dim]")
            custom_instructions = instructions_path.read_text()
        elif instructions:
            # Use inline string
            custom_instructions = instructions

        # Initialize processor
        processor = ChainProcessor(openai_api_key)

        # Determine message content and metadata
        if input:
            # Read from input file
            input_path = Path(input)
            if not input_path.exists():
                console.print(f"[red]Error: Input file not found: {input}[/red]")
                return

            console.print(f"[dim]Reading view from {input}...[/dim]")
            message_content = input_path.read_text()
            channel_name = "Input File"
            date_range_str = "unknown"
            view_type = "single_channel"  # Default for input files
            normalized_channels = []
        else:
            # Generate view from cache (same logic as view command)
            if not channel and not merge_channels and not user:
                console.print("[red]Error: Must specify --channel, --merge-channels, --user, or --input[/red]")
                console.print("[yellow]Examples:[/yellow]")
                console.print("  slack-intel process --channel backend-devs")
                console.print("  slack-intel process --merge-channels")
                console.print("  slack-intel process --user zeebee")
                console.print("  slack-intel process --input view.txt")
                return

            # Determine channels to view
            channels_to_view = []

            if user:
                # User timeline processing - will use different logic below
                console.print(f"[dim]Processing timeline for user: {user}[/dim]")
                channels_to_view = []  # Will be populated from user data
            elif merge_channels:
                config_channels = load_config()
                channels_to_view = [ch["name"] for ch in config_channels]
                console.print(f"[dim]Processing {len(channels_to_view)} channels from manifest[/dim]")
            elif channel:
                channels_to_view = list(channel)
                console.print(f"[dim]Processing {len(channels_to_view)} channel(s)[/dim]")

            # Initialize SQL view composer and user reader
            composer = SqlViewComposer(base_path=cache_path)
            user_reader = ParquetUserReader(base_path=cache_path)

            # Load cached users
            console.print("[dim]Loading user cache...[/dim]")
            cached_users = user_reader.read_users()

            # Normalize channel names
            normalized_channels = channels_to_view

            # Determine date range using unified days parameter
            from datetime import timedelta
            if end_date:
                end_date_dt = datetime.strptime(end_date, "%Y-%m-%d")
            else:
                end_date_dt = datetime.now()

            start_date_dt = end_date_dt - timedelta(days=days - 1)  # -1 because end date is inclusive
            start_date = start_date_dt.strftime("%Y-%m-%d")
            end_date = end_date_dt.strftime("%Y-%m-%d")

            if days == 1:
                date_range_str = end_date
            else:
                date_range_str = f"{start_date} to {end_date}"

            # Read messages based on view type
            if user:
                # User timeline mode - fetch user's messages across channels
                # Resolve username to user_id and get actual user_name
                user_id = user_reader.find_user_by_name(user)
                if not user_id:
                    console.print(f"[yellow]Could not find user '{user}' in cache[/yellow]")
                    console.print("[dim]User lookup uses cached data - try a different name or check available users[/dim]")
                    return

                # Get the actual user_name from cache
                user_data = user_reader.get_user(user_id)
                actual_user_name = user_data.get('user_name') if user_data else user
                user_display_name = user_data.get('user_real_name', actual_user_name) if user_data else user

                console.print(f"[dim]Reading messages from {user_display_name} (@{actual_user_name}) ({date_range_str})...[/dim]")

                # Get all channels from config if not specified
                if not channels_to_view:
                    config_channels = load_config()
                    channels_to_view = [ch["name"] for ch in config_channels]

                # Normalize channel names (try with prefix)
                channels_with_data = []
                for ch in channels_to_view:
                    test_messages = composer.read_messages_enriched_range(ch, start_date, end_date)
                    if test_messages:
                        channels_with_data.append(ch)
                    elif not ch.startswith("channel_"):
                        prefixed = f"channel_{ch}"
                        test_messages = composer.read_messages_enriched_range(prefixed, start_date, end_date)
                        if test_messages:
                            channels_with_data.append(prefixed)

                if not channels_with_data:
                    console.print(f"[yellow]No channel data found for {date_range_str}[/yellow]")
                    return

                # Fetch user timeline with SQL-level filtering
                flat_messages = composer.read_user_timeline_enriched(
                    user_name=actual_user_name,
                    channels=channels_with_data,
                    start_date=start_date,
                    end_date=end_date,
                    include_mentions=include_mentions,
                    user_id=user_id
                )
                normalized_channels = channels_with_data
                channel_name = f"{user_display_name} (@{actual_user_name})"

                if not flat_messages:
                    console.print(f"[yellow]No messages found from user '{user}' in {date_range_str}[/yellow]")
                    return

            elif len(normalized_channels) == 1:
                # Single channel mode
                single_channel = normalized_channels[0]
                console.print(f"[dim]Reading messages from {single_channel} ({date_range_str})...[/dim]")
                flat_messages = composer.read_messages_enriched_range(single_channel, start_date, end_date)

                if not flat_messages and not single_channel.startswith("channel_"):
                    prefixed_name = f"channel_{single_channel}"
                    flat_messages = composer.read_messages_enriched_range(prefixed_name, start_date, end_date)
                    if flat_messages:
                        single_channel = prefixed_name
                        normalized_channels = [prefixed_name]

                if not flat_messages:
                    console.print(f"[yellow]No messages found in {single_channel} for {date_range_str}[/yellow]")
                    return

                channel_name = single_channel

            else:
                # Multi-channel mode
                console.print(f"[dim]Reading messages from {len(normalized_channels)} channels ({date_range_str})...[/dim]")
                channels_with_data = []
                for ch in normalized_channels:
                    test_messages = composer.read_messages_enriched_range(ch, start_date, end_date)
                    if test_messages:
                        channels_with_data.append(ch)
                    elif not ch.startswith("channel_"):
                        prefixed = f"channel_{ch}"
                        test_messages = composer.read_messages_enriched_range(prefixed, start_date, end_date)
                        if test_messages:
                            channels_with_data.append(prefixed)

                if not channels_with_data:
                    console.print(f"[yellow]No messages found in any channel for {date_range_str}[/yellow]")
                    return

                flat_messages = composer.read_multi_channel_messages_enriched(
                    channels_with_data,
                    start_date,
                    end_date
                )
                normalized_channels = channels_with_data
                channel_name = "Multi-Channel"

            console.print(f"[green]Found {len(flat_messages)} messages[/green]")

            # Reconstruct threads and format view
            console.print("[dim]Reconstructing threads and formatting view...[/dim]")
            reconstructor = ThreadReconstructor()
            structured_messages = reconstructor.reconstruct(flat_messages)

            # Load full config for org context
            full_config = load_full_config_with_fallback()

            # Build org_context dict from config
            org_context = {
                "name": full_config.organization.name,
                "description": full_config.organization.description,
                "stakeholders": [
                    {
                        "name": s.name,
                        "weight": s.weight,
                        "role": s.role,
                        "description": s.description
                    }
                    for s in full_config.organization.stakeholders
                ],
                "stakeholder_context": full_config.organization.stakeholder_context
            }

            # Compute metadata from messages
            from .message_view_formatter import MessageViewFormatter
            metadata = MessageViewFormatter.compute_metadata(
                messages=structured_messages,
                org_context=org_context,
                high_engagement_threshold=5
            )

            # Determine view type for processor
            if user:
                view_type = "user_timeline"
                context = ViewContext(
                    channel_name=channel_name,
                    date_range=date_range_str,
                    channels=normalized_channels,
                    org_context=org_context,
                    metadata=metadata
                )
                formatter = EnrichedMessageViewFormatter(bucket_type=bucket_by)
            elif len(normalized_channels) > 1:
                view_type = "multi_channel"
                context = ViewContext(
                    channel_name="Multi-Channel",
                    date_range=date_range_str,
                    channels=normalized_channels,
                    org_context=org_context,
                    metadata=metadata
                )
                formatter = EnrichedMessageViewFormatter(bucket_type=bucket_by)
            else:
                view_type = "single_channel"
                context = ViewContext(
                    channel_name=channel_name,
                    date_range=date_range_str,
                    org_context=org_context,
                    metadata=metadata
                )
                formatter = EnrichedMessageViewFormatter()

            message_content = formatter.format(structured_messages, context, cached_users=cached_users)

        # Process with LLM
        console.print()

        # Build panel content based on model
        if model.startswith("gpt-5") or model == "gpt-5":
            panel_content = (
                f"[bold blue]🤖 LLM Processing[/bold blue]\n"
                f"Channel: {channel_name}\n"
                f"Date Range: {date_range_str}\n"
                f"Model: {model}\n"
                f"Reasoning Effort: {reasoning_effort}"
            )
        else:
            panel_content = (
                f"[bold blue]🤖 LLM Processing[/bold blue]\n"
                f"Channel: {channel_name}\n"
                f"Date Range: {date_range_str}\n"
                f"Model: {model}\n"
                f"Temperature: {temperature}\n"
                f"Max Tokens: {max_tokens}"
            )

        console.print(Panel.fit(panel_content, border_style="blue"))
        console.print("[cyan]Analyzing messages with LLM...[/cyan]")

        # Run analysis
        result = processor.analyze_messages(
            message_content=message_content,
            channel_name=channel_name,
            date_range=date_range_str,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            reasoning_effort=reasoning_effort,
            view_type=view_type,
            channels=normalized_channels,
            org_context=org_context,
            custom_instructions=custom_instructions
        )

        # Display results
        console.print()
        if format == 'json':
            # JSON output
            output_data = result.to_dict()
            output_str = json.dumps(output_data, indent=2)
        else:
            # Text output
            output_str = f"""# Slack Channel Analysis

Channel: {result.channel_name}
Date Range: {result.date_range}
Model: {result.model_used}
Processing Time: {result.total_processing_time:.2f}s

## Summary

{result.summary}

---
Generated by slack-intel on {result.timestamp.strftime('%Y-%m-%d %H:%M:%S')}
"""

        # Output
        if output:
            output_path = Path(output)
            output_path.write_text(output_str)
            console.print(f"[green]✓ Summary saved to {output}[/green]")
        else:
            console.print(output_str)

        # Display metrics
        console.print()
        table = Table(title="Processing Metrics", show_header=True, header_style="bold cyan")
        table.add_column("Step", style="cyan")
        table.add_column("Input", style="dim")
        table.add_column("Output", style="dim")
        table.add_column("Time (s)", justify="right")
        table.add_column("Status")

        for step in result.processing_steps:
            status_color = "green" if step.success else "red"
            status_text = "✓" if step.success else "✗"
            table.add_row(
                step.step_name,
                step.input_data,
                step.output_data,
                f"{step.processing_time:.2f}",
                f"[{status_color}]{status_text}[/{status_color}]"
            )

        console.print(table)

    except Exception as e:
        console.print(f"[red]Error processing messages: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


@cli.command()
@click.option('--bucket', '-b', help='S3 bucket name (overrides config file)')
@click.option('--prefix', '-p', help='S3 prefix/folder (overrides config file)')
@click.option('--cache-path', default='cache/raw', help='Local cache directory (default: cache/raw)')
@click.option('--region', help='AWS region (overrides config file)')
@click.option('--profile', help='AWS profile name (overrides config file, supports SSO)')
@click.option('--delete', is_flag=True, help='Delete S3 files not present locally')
@click.option('--dry-run', is_flag=True, help='Show what would be synced without uploading')
def sync(bucket, prefix, cache_path, region, profile, delete, dry_run):
    """Sync cached Parquet files to S3

    Uses incremental sync - only uploads new or modified files.
    Preserves directory structure including Hive-style partitions.

    Examples:
        \b
        # Sync using config file (.slack-intel.yaml)
        slack-intel sync

        \b
        # Override config with CLI options
        slack-intel sync --bucket my-slack-data --profile AdministratorAccess-276780518338

        \b
        # Sync with prefix
        slack-intel sync --prefix production/

        \b
        # Dry run to see what would be synced
        slack-intel sync --dry-run

        \b
        # Sync with deletion of remote files not present locally
        slack-intel sync --delete

        \b
        # Use specific AWS profile and region (overrides config)
        slack-intel sync --profile prod --region us-west-2
    """
    # Load config
    config_channels = load_config()

    # Extract S3 storage config from loaded config
    storage_config = {}
    config_paths = [
        Path(".slack-intel.yaml"),
        Path.home() / ".slack-intel.yaml",
    ]

    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    if config and "storage" in config:
                        storage_config = config["storage"]
                        console.print(f"[dim]Loaded S3 config from {config_path}[/dim]")
                        break
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to load {config_path}: {e}[/yellow]")
                continue

    # Merge config with CLI options (CLI options take precedence)
    final_bucket = bucket or storage_config.get("bucket")
    final_prefix = prefix if prefix is not None else storage_config.get("prefix", "")
    final_region = region or storage_config.get("region")
    final_profile = profile or storage_config.get("profile")

    # Validate required bucket
    if not final_bucket:
        console.print("[red]Error: S3 bucket not specified[/red]")
        console.print("[yellow]Either:[/yellow]")
        console.print("  - Specify --bucket on command line")
        console.print("  - Configure 'storage.bucket' in .slack-intel.yaml")
        console.print("\n[dim]Example .slack-intel.yaml:[/dim]")
        console.print("[dim]storage:")
        console.print("  bucket: my-slack-data")
        console.print("  prefix: production/")
        console.print("  profile: AdministratorAccess-276780518338[/dim]")
        return

    cache_dir = Path(cache_path)

    if not cache_dir.exists():
        console.print(f"[red]Error: Cache directory not found: {cache_path}[/red]")
        console.print("[yellow]Run 'slack-intel cache' first to create cache.[/yellow]")
        return

    # Display sync info
    console.print(Panel.fit(
        f"[bold blue]☁️  S3 Sync[/bold blue]\n"
        f"Source: {cache_path}\n"
        f"Destination: s3://{final_bucket}/{final_prefix}\n"
        f"Profile: {final_profile or '[dim]default[/dim]'}\n"
        f"Region: {final_region or '[dim]default[/dim]'}\n"
        f"Delete remote: {'[red]yes[/red]' if delete else '[dim]no[/dim]'}\n"
        f"Mode: {'[yellow]DRY RUN[/yellow]' if dry_run else '[green]live[/green]'}",
        border_style="blue"
    ))

    try:
        # Create S3 syncer
        console.print("[dim]Initializing S3 syncer...[/dim]")
        syncer = create_syncer(
            bucket=final_bucket,
            prefix=final_prefix,
            region=final_region,
            aws_profile=final_profile
        )

        # Perform sync
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task(
                f"[cyan]{'Checking' if dry_run else 'Syncing'} files...",
                total=None
            )

            result = syncer.sync(
                local_path=cache_dir,
                delete=delete,
                dry_run=dry_run,
                include_patterns=["**/*.parquet"]
            )

            progress.update(task, completed=True)

        # Display results
        if dry_run:
            console.print("\n[yellow]DRY RUN - No files were actually uploaded[/yellow]")
        else:
            console.print()
            table = Table(title="Sync Results", show_header=True, header_style="bold cyan")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", justify="right")

            table.add_row("Files Uploaded", str(result.files_uploaded))
            table.add_row("Files Skipped", str(result.files_skipped))
            if delete:
                table.add_row("Files Deleted", str(result.files_deleted))
            table.add_row("Data Transferred", f"{result.bytes_transferred / (1024*1024):.2f} MB")

            console.print(table)

            if result.success:
                console.print(f"\n[green]✓ Sync completed successfully[/green]")
            else:
                console.print(f"\n[yellow]⚠ Sync completed with warnings[/yellow]")

    except ValueError as e:
        console.print(f"[red]Configuration error: {e}[/red]")
        console.print("\n[yellow]Tips:[/yellow]")
        console.print("  - Check that the bucket name is correct")
        console.print("  - For AWS SSO: Run 'aws sso login --profile YOUR_PROFILE'")
        console.print("  - For standard AWS: Run 'aws configure'")
        console.print("  - Verify you have permissions to access the bucket")
        if final_profile:
            console.print(f"  - Test profile with: aws --profile {final_profile} s3 ls s3://{final_bucket}/")
    except Exception as e:
        console.print(f"[red]Sync failed: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


@cli.group()
def config():
    """Configuration management commands"""
    pass


@config.command('init')
@click.option('--cache-path', default='cache', help='Cache directory to read users from (default: cache)')
@click.option('--org-name', default='My Organization', help='Organization name')
@click.option('--output', '-o', default='.slack-intel.yaml', help='Output config file path')
@click.option('--force', '-f', is_flag=True, help='Overwrite existing config file')
def config_init(cache_path, org_name, output, force):
    """Initialize .slack-intel.yaml from cached users and channels (first-time setup)

    Generates a config file with:
    - All users from cache (with default weight 5)
    - All channels from cache
    - Ready for you to edit weights and descriptions

    Examples:
        \\b
        # Generate config from cache (first time)
        slack-intel config init

        \\b
        # Custom organization name and output path
        slack-intel config init --org-name "Acme Corp" --output my-config.yaml

        \\b
        # Overwrite existing config (start over)
        slack-intel config init --force
    """
    from .config import generate_initial_config

    output_path = Path(output)

    # Check if file exists
    if output_path.exists() and not force:
        console.print(f"[red]Error: {output} already exists[/red]")
        console.print("[yellow]Use --force to overwrite, or use 'config sync-users' to add new users[/yellow]")
        return

    console.print(Panel.fit(
        f"[bold cyan]🔧 Config Initialization[/bold cyan]\n"
        f"Generating config from cache",
        border_style="cyan"
    ))

    try:
        # Read users from cache
        console.print("[dim]Reading users from cache...[/dim]")
        user_reader = ParquetUserReader(base_path=cache_path)
        cached_users = user_reader.read_users()

        if not cached_users:
            console.print("[yellow]Warning: No users found in cache[/yellow]")
            console.print("[dim]Run 'slack-intel cache' first to populate cache[/dim]")
            cached_users = {}

        # Get channels from existing config or use defaults
        console.print("[dim]Loading existing channels...[/dim]")
        try:
            existing_config = load_config()
            channels = existing_config
        except Exception:
            channels = DEFAULT_CHANNELS

        # Generate config
        console.print(f"[dim]Generating config with {len(cached_users)} users and {len(channels)} channels...[/dim]")
        yaml_content = generate_initial_config(
            users=cached_users,
            channels=channels,
            org_name=org_name,
            output_path=output_path
        )

        # Summary
        console.print()
        console.print(f"[green]✓ Config generated: {output}[/green]")
        console.print()
        console.print("[bold]Next steps:[/bold]")
        console.print(f"  1. Edit {output}:")
        console.print("     - Set weight 7-10 for key stakeholders (CEO, VPs, leads)")
        console.print("     - Delete entries you don't need to track")
        console.print("     - Add channel descriptions and signal_type (critical/high/medium/low)")
        console.print("  2. Run analysis:")
        console.print("     slack-intel process --merge-channels --days 7")
        console.print()
        console.print("[dim]Later: Use 'slack-intel config sync-users' to add new team members[/dim]")

    except Exception as e:
        console.print(f"[red]Error generating config: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


@config.command('sync-users')
@click.option('--cache-path', default='cache', help='Cache directory to read users from (default: cache)')
@click.option('--config-path', default='.slack-intel.yaml', help='Config file path (default: .slack-intel.yaml)')
def config_sync_users(cache_path, config_path):
    """Add new users from cache to existing config (keeps your edits)

    Merges new team members from cache into your config without overwriting
    existing weights or descriptions. New users get default weight 5.

    Examples:
        \\b
        # Add new users to existing config
        slack-intel config sync-users

        \\b
        # Use custom config path
        slack-intel config sync-users --config-path my-config.yaml
    """
    from .config import load_config, sync_users_to_config

    config_file = Path(config_path)

    # Check if config exists
    if not config_file.exists():
        console.print(f"[red]Error: {config_path} not found[/red]")
        console.print("[yellow]Run 'slack-intel config init' first to create initial config[/yellow]")
        return

    console.print(Panel.fit(
        f"[bold cyan]👥 Sync Users to Config[/bold cyan]\n"
        f"Adding new users from cache",
        border_style="cyan"
    ))

    try:
        # Load existing config
        console.print(f"[dim]Loading config from {config_path}...[/dim]")
        existing_config = load_config(config_file)

        existing_count = len(existing_config.organization.stakeholders)
        console.print(f"[dim]Current config has {existing_count} stakeholders[/dim]")

        # Read users from cache
        console.print("[dim]Reading users from cache...[/dim]")
        user_reader = ParquetUserReader(base_path=cache_path)
        cached_users = user_reader.read_users()

        if not cached_users:
            console.print("[yellow]Warning: No users found in cache[/yellow]")
            console.print("[dim]Run 'slack-intel cache' first to populate cache[/dim]")
            return

        console.print(f"[dim]Found {len(cached_users)} users in cache[/dim]")

        # Sync users
        console.print("[dim]Merging new users into config...[/dim]")
        updated_config, new_users = sync_users_to_config(
            existing_config=existing_config,
            cached_users=cached_users,
            output_path=config_file
        )

        # Summary
        console.print()
        if new_users:
            console.print(f"[green]✓ Added {len(new_users)} new users to {config_path}[/green]")
            console.print()
            console.print("[bold]New users added:[/bold]")
            for user in new_users[:20]:  # Show first 20
                console.print(f"  • {user} (weight: 5)")
            if len(new_users) > 20:
                console.print(f"  ... and {len(new_users) - 20} more")

            console.print()
            console.print("[bold]Next steps:[/bold]")
            console.print(f"  1. Edit {config_path}:")
            console.print("     - Adjust weights for new leaders (7-10)")
            console.print("     - Delete unneeded entries")
            console.print("  2. Run analysis with updated config")
        else:
            console.print(f"[yellow]No new users found - config is up to date[/yellow]")
            console.print(f"[dim]All {len(cached_users)} cached users already in config[/dim]")

    except Exception as e:
        console.print(f"[red]Error syncing users: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")


if __name__ == "__main__":
    cli()
