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
from .parquet_message_reader import ParquetMessageReader
from .thread_reconstructor import ThreadReconstructor
from .message_view_formatter import MessageViewFormatter, ViewContext

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
                from datetime import datetime as dt

                messages_by_date = defaultdict(list)
                for msg in messages:
                    # Extract date from message timestamp
                    if msg.timestamp:
                        # Parse ISO timestamp and get date
                        try:
                            msg_dt = dt.fromisoformat(msg.timestamp.replace('Z', '+00:00'))
                            msg_date = msg_dt.strftime('%Y-%m-%d')
                            messages_by_date[msg_date].append(msg)
                        except (ValueError, AttributeError):
                            # Fallback to partition_date if timestamp is invalid
                            messages_by_date[date_str].append(msg)
                    else:
                        # No timestamp, use partition date
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

                # Calculate total size
                file_size_mb = total_size / (1024 * 1024)

                results.append({
                    "channel": channel.name,
                    "messages": len(messages),
                    "status": "cached",
                    "path": f"{len(partition_paths)} partitions: {min(messages_by_date.keys())} to {max(messages_by_date.keys())}",
                    "size_mb": file_size_mb
                })

                console.print(f"[green]  ✓ Cached {len(messages)} messages from {channel.name}[/green]")

            except Exception as e:
                console.print(f"[red]  ✗ Error processing {channel.name}: {e}[/red]")
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
        # Initialize reader
        reader = ParquetMessageReader(base_path=cache_path)

        # Handle channel naming: try exact name first, then with "channel_" prefix
        # This handles both config-based channels (named) and CLI channel IDs
        def try_read_channel(channel_name: str, date: str):
            """Try reading channel, handling both named channels and raw IDs"""
            # Try exact name first
            messages = reader.read_channel(channel_name, date)
            if messages:
                return messages, channel_name

            # If no messages and channel name doesn't start with "channel_", try with prefix
            if not channel_name.startswith("channel_"):
                prefixed_name = f"channel_{channel_name}"
                messages = reader.read_channel(prefixed_name, date)
                if messages:
                    return messages, prefixed_name

            return [], channel_name

        # Determine date range
        if start_date and end_date:
            date_range_str = f"{start_date} to {end_date}"
            console.print(f"[dim]Reading messages from {channel} ({date_range_str})...[/dim]")
            flat_messages = reader.read_channel_range(channel, start_date, end_date)
            # TODO: Handle channel prefix for date ranges too
        elif date:
            date_range_str = date
            console.print(f"[dim]Reading messages from {channel} ({date})...[/dim]")
            flat_messages, actual_channel = try_read_channel(channel, date)
            channel = actual_channel  # Update channel name for display
        else:
            # Default to today
            date_str = datetime.now().strftime("%Y-%m-%d")
            date_range_str = date_str
            console.print(f"[dim]Reading messages from {channel} ({date_str})...[/dim]")
            flat_messages, actual_channel = try_read_channel(channel, date_str)
            channel = actual_channel  # Update channel name for display

        if not flat_messages:
            console.print(f"[yellow]No messages found in {channel} for {date_range_str}[/yellow]")
            console.print("[dim]Try a different date range or check 'slack-intel stats' to see available data.[/dim]")
            return

        console.print(f"[green]Found {len(flat_messages)} messages[/green]")

        # Reconstruct threads
        console.print("[dim]Reconstructing thread structure...[/dim]")
        reconstructor = ThreadReconstructor()
        structured_messages = reconstructor.reconstruct(flat_messages)

        # Format view
        console.print("[dim]Formatting view...[/dim]")
        context = ViewContext(
            channel_name=channel,
            date_range=date_range_str
        )
        formatter = MessageViewFormatter()
        view_output = formatter.format(structured_messages, context)

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


if __name__ == "__main__":
    cli()
