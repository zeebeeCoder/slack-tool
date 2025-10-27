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
    """Load channels from config file or use defaults

    Looks for .slack-intel.yaml in current directory or home directory.
    Falls back to DEFAULT_CHANNELS if no config found.
    """
    config_paths = [
        Path(".slack-intel.yaml"),
        Path.home() / ".slack-intel.yaml",
    ]

    for config_path in config_paths:
        if config_path.exists():
            try:
                with open(config_path) as f:
                    config = yaml.safe_load(f)
                    if config and "channels" in config:
                        console.print(f"[dim]Loaded config from {config_path}[/dim]")
                        return config["channels"]
            except Exception as e:
                console.print(f"[yellow]Warning: Failed to load {config_path}: {e}[/yellow]")
                continue

    # Fallback to defaults
    return DEFAULT_CHANNELS


@click.group()
def cli():
    """Slack Intelligence - Cache and query Slack messages in Parquet format"""
    pass


@cli.command()
@click.option('--channel', '-c', multiple=True, help='Channel ID(s) to cache (overrides config)')
@click.option('--days', '-d', default=2, help='Days to look back (default: 2)')
@click.option('--hours', '-h', default=0, help='Hours to look back (default: 0)')
@click.option('--cache-path', default='cache/raw', help='Cache directory (default: cache/raw)')
@click.option('--date', help='Partition date YYYY-MM-DD (default: today)')
@click.option('--enrich-jira', is_flag=True, help='Fetch and cache JIRA ticket metadata')
def cache(channel, days, hours, cache_path, date, enrich_jira):
    """Fetch messages from Slack and save to Parquet cache

    Examples:
        \b
        # Cache last 7 days from default channels
        slack-intel cache --days 7

        \b
        # Cache specific channel
        slack-intel cache --channel C9876543210 --days 3

        \b
        # Override multiple channels
        slack-intel cache -c C9876543210 -c C1111111111 --days 1

        \b
        # Cache with JIRA enrichment
        slack-intel cache --enrich-jira --days 7
    """
    asyncio.run(_cache_async(channel, days, hours, cache_path, date, enrich_jira))


async def _cache_async(channel_ids, days, hours, cache_path, partition_date, enrich_jira):
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
    time_window = TimeWindow(days=days, hours=hours)
    date_str = partition_date or datetime.now().strftime("%Y-%m-%d")

    # Header
    console.print(Panel.fit(
        f"[bold blue]📦 Slack to Parquet Cache[/bold blue]\n"
        f"Processing {len(channels)} channels\n"
        f"Time window: {days} days, {hours} hours\n"
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
@click.option('--channel', '-c', required=True, help='Channel name to view')
@click.option('--date', '-d', help='Date to view (YYYY-MM-DD, default: today)')
@click.option('--start-date', help='Start date for range (YYYY-MM-DD)')
@click.option('--end-date', help='End date for range (YYYY-MM-DD)')
@click.option('--cache-path', default='cache', help='Cache directory (default: cache)')
@click.option('--output', '-o', help='Output file (default: print to console)')
def view(channel, date, start_date, end_date, cache_path, output):
    """Generate formatted message view from Parquet cache

    Examples:
        \\b
        # View single day
        slack-intel view --channel backend-devs --date 2025-10-20

        \\b
        # View date range
        slack-intel view -c engineering --start-date 2025-10-18 --end-date 2025-10-20

        \\b
        # Save to file
        slack-intel view -c general --date 2025-10-20 -o output.txt
    """
    try:
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

        # Handle channel naming: try exact name first, then with "channel_" prefix
        # This handles both config-based channels (named) and CLI channel IDs
        def try_read_channel(channel_name: str, date: str):
            """Try reading channel, handling both named channels and raw IDs"""
            # Try exact name first
            messages = composer.read_messages_enriched(channel_name, date)
            if messages:
                return messages, channel_name

            # If no messages and channel name doesn't start with "channel_", try with prefix
            if not channel_name.startswith("channel_"):
                prefixed_name = f"channel_{channel_name}"
                messages = composer.read_messages_enriched(prefixed_name, date)
                if messages:
                    return messages, prefixed_name

            return [], channel_name

        # Determine date range
        if start_date and end_date:
            date_range_str = f"{start_date} to {end_date}"
            console.print(f"[dim]Reading enriched messages from {channel} ({date_range_str})...[/dim]")
            # Try exact channel name first
            flat_messages = composer.read_messages_enriched_range(channel, start_date, end_date)
            # If no messages and channel doesn't start with "channel_", try with prefix
            if not flat_messages and not channel.startswith("channel_"):
                prefixed_name = f"channel_{channel}"
                flat_messages = composer.read_messages_enriched_range(prefixed_name, start_date, end_date)
                if flat_messages:
                    channel = prefixed_name
        elif date:
            date_range_str = date
            console.print(f"[dim]Reading enriched messages from {channel} ({date})...[/dim]")
            flat_messages, actual_channel = try_read_channel(channel, date)
            channel = actual_channel  # Update channel name for display
        else:
            # Default to last 7 days
            from datetime import timedelta
            end_date_dt = datetime.now()
            start_date_dt = end_date_dt - timedelta(days=7)
            start_date = start_date_dt.strftime("%Y-%m-%d")
            end_date = end_date_dt.strftime("%Y-%m-%d")
            date_range_str = f"{start_date} to {end_date}"
            console.print(f"[dim]Reading enriched messages from {channel} ({date_range_str})...[/dim]")
            # Try exact channel name first
            flat_messages = composer.read_messages_enriched_range(channel, start_date, end_date)
            # If no messages and channel doesn't start with "channel_", try with prefix
            if not flat_messages and not channel.startswith("channel_"):
                prefixed_name = f"channel_{channel}"
                flat_messages = composer.read_messages_enriched_range(prefixed_name, start_date, end_date)
                if flat_messages:
                    channel = prefixed_name

        if not flat_messages:
            console.print(f"[yellow]No messages found in {channel} for {date_range_str}[/yellow]")
            console.print("[dim]Try a different date range or check 'slack-intel stats' to see available data.[/dim]")
            return

        console.print(f"[green]Found {len(flat_messages)} messages[/green]")

        # Reconstruct threads
        console.print("[dim]Reconstructing thread structure...[/dim]")
        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)

        # Format view with JIRA enrichment
        console.print("[dim]Formatting enriched view...[/dim]")
        context = ViewContext(
            channel_name=channel,
            date_range=date_range_str
        )
        formatter = EnrichedMessageViewFormatter()
        view_output = formatter.format(structured_messages, context, cached_users=cached_users)

        # Output
        if output:
            output_path = Path(output)
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


if __name__ == "__main__":
    cli()
