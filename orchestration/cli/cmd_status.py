"""
taskq status command implementation.

Displays task queue status, optionally filtered by task ID or output as JSON.
"""

import sys
import json
import argparse


def cmd_status(cli_instance, args: argparse.Namespace) -> int:
    """Display task queue status.

    Args:
        cli_instance: TaskQCLI instance with store
        args: Parsed command-line arguments with: id (optional), json (optional)

    Returns:
        Exit code (0 on success, 1 on error)
    """
    try:
        records = cli_instance.store.get_all_records()

        # Filter by ID if specified
        if args.id:
            records = [r for r in records if r.id == args.id]
            if not records:
                print(f"No task found with id: {args.id}", file=sys.stderr)
                return 1

        # Output format
        if args.json:
            output = json.dumps(
                [r.to_dict() for r in records],
                indent=2,
                default=str,
            )
            print(output)
        else:
            # Group by status
            by_status = {}
            for record in records:
                if record.status not in by_status:
                    by_status[record.status] = []
                by_status[record.status].append(record)

            # Display grouped output
            status_order = [
                "todo",
                "planning",
                "building",
                "review",
                "done",
                "failed",
                "cancelled",
            ]
            for status in status_order:
                if status in by_status:
                    print(f"\n{status.upper()}:")
                    for record in by_status[status]:
                        print(f"  {record.id}")

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
