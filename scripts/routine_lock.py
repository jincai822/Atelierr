#!/usr/bin/env python3
"""Distributed lock for local routines via DynamoDB conditional put.

Coordinates scheduled routines across multiple machines sharing the same
vault. Each machine's launchd fires the routine on schedule; this module
ensures only one machine actually executes per cycle.

Lock primitive: DynamoDB `PutItem` with `attribute_not_exists(pk)`.
Server-side atomic — no race window regardless of filesystem sync delays.
TTL column auto-expires stale locks (crashed mid-run).

When coordination is disabled (no AWS credentials or config says "none"),
all operations are no-ops that return success, so single-machine setups
work without any AWS dependency.

Usage:
    # Acquire (exits 0 = acquired, 1 = held by another, 2 = error)
    routine_lock.py acquire <routine> [--cycle <id>] [--ttl 3600]

    # Release (best-effort; TTL handles crashes)
    routine_lock.py release <routine> [--cycle <id>]

    # Query
    routine_lock.py status <routine> [--cycle <id>]

    # One-time table setup
    routine_lock.py setup-table
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

TABLE_NAME = "atelier-routine-locks"
TTL_DEFAULT = 3600  # 1 hour
AWS_REGION = os.environ.get("ATELIER_AWS_REGION", "us-west-2")


def _coordination_mode() -> str:
    """Read coordination mode from env or routine_watch.toml."""
    explicit = os.environ.get("ATELIER_COORDINATION")
    if explicit:
        return explicit.lower()

    ov = os.environ.get("OV")
    if not ov:
        return "none"

    try:
        import tomllib
    except ImportError:
        return "none"

    watch = Path(ov) / "_meta" / "routine_watch.toml"
    if not watch.is_file():
        return "none"

    try:
        config = tomllib.loads(watch.read_text())
        return config.get("coordination", {}).get("backend", "none")
    except Exception:
        return "none"


def _get_client():
    """Get a boto3 DynamoDB client. Returns None if unavailable."""
    try:
        import boto3
    except ImportError:
        print("ERROR: boto3 not installed. Run: uv pip install boto3", file=sys.stderr)
        return None

    try:
        return boto3.client("dynamodb", region_name=AWS_REGION)
    except Exception as exc:
        print(f"ERROR: failed to create DynamoDB client: {exc}", file=sys.stderr)
        return None


def _cycle_id(explicit: str | None) -> str:
    """Default cycle ID is today's date."""
    if explicit:
        return explicit
    return date.today().isoformat()


def _hostname() -> str:
    return platform.node() or "unknown"


def acquire(routine: str, cycle: str | None, ttl: int) -> int:
    """Attempt to acquire the lock. Returns 0=acquired, 1=held, 2=error."""
    mode = _coordination_mode()
    if mode == "none":
        return 0

    client = _get_client()
    if not client:
        return 2

    cycle_id = _cycle_id(cycle)
    pk = f"{routine}#{cycle_id}"
    now = int(time.time())
    hostname = _hostname()

    try:
        client.put_item(
            TableName=TABLE_NAME,
            Item={
                "pk": {"S": pk},
                "routine": {"S": routine},
                "cycle_id": {"S": cycle_id},
                "machine": {"S": hostname},
                "claimed_at": {"S": datetime.now(timezone.utc).isoformat()},
                "status": {"S": "running"},
                "ttl": {"N": str(now + ttl)},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        print(json.dumps({"acquired": True, "machine": hostname, "cycle": cycle_id}))
        return 0

    except client.exceptions.ConditionalCheckFailedException:
        try:
            resp = client.get_item(
                TableName=TABLE_NAME,
                Key={"pk": {"S": pk}},
            )
            item = resp.get("Item", {})
            holder = item.get("machine", {}).get("S", "unknown")
            status = item.get("status", {}).get("S", "unknown")
            print(json.dumps({"acquired": False, "held_by": holder, "status": status, "cycle": cycle_id}))
        except Exception:
            print(json.dumps({"acquired": False, "cycle": cycle_id}))
        return 1

    except Exception as exc:
        print(f"ERROR: DynamoDB put failed: {exc}", file=sys.stderr)
        return 2


def release(routine: str, cycle: str | None) -> int:
    """Release the lock (update status to completed). Returns 0=ok, 2=error."""
    mode = _coordination_mode()
    if mode == "none":
        return 0

    client = _get_client()
    if not client:
        return 2

    cycle_id = _cycle_id(cycle)
    pk = f"{routine}#{cycle_id}"
    hostname = _hostname()

    try:
        client.update_item(
            TableName=TABLE_NAME,
            Key={"pk": {"S": pk}},
            UpdateExpression="SET #s = :s, completed_at = :t",
            ConditionExpression="machine = :m",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={
                ":s": {"S": "completed"},
                ":t": {"S": datetime.now(timezone.utc).isoformat()},
                ":m": {"S": hostname},
            },
        )
        print(json.dumps({"released": True, "cycle": cycle_id}))
        return 0

    except client.exceptions.ConditionalCheckFailedException:
        print(json.dumps({"released": False, "reason": "not_owner", "cycle": cycle_id}))
        return 0  # not an error; another machine owns it

    except Exception as exc:
        print(f"ERROR: DynamoDB update failed: {exc}", file=sys.stderr)
        return 2


def status(routine: str, cycle: str | None) -> int:
    """Query lock status. Returns 0 always."""
    mode = _coordination_mode()
    if mode == "none":
        print(json.dumps({"coordination": "none", "routine": routine}))
        return 0

    client = _get_client()
    if not client:
        return 2

    cycle_id = _cycle_id(cycle)
    pk = f"{routine}#{cycle_id}"

    try:
        resp = client.get_item(
            TableName=TABLE_NAME,
            Key={"pk": {"S": pk}},
        )
        item = resp.get("Item")
        if not item:
            print(json.dumps({"exists": False, "cycle": cycle_id}))
        else:
            out = {
                "exists": True,
                "cycle": cycle_id,
                "machine": item.get("machine", {}).get("S"),
                "status": item.get("status", {}).get("S"),
                "claimed_at": item.get("claimed_at", {}).get("S"),
                "completed_at": item.get("completed_at", {}).get("S"),
            }
            print(json.dumps({k: v for k, v in out.items() if v is not None}))
        return 0

    except Exception as exc:
        print(f"ERROR: DynamoDB get failed: {exc}", file=sys.stderr)
        return 2


def setup_table() -> int:
    """Create the DynamoDB table (one-time setup)."""
    client = _get_client()
    if not client:
        return 2

    try:
        client.create_table(
            TableName=TABLE_NAME,
            AttributeDefinitions=[
                {"AttributeName": "pk", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "pk", "KeyType": "HASH"},
            ],
            BillingMode="PROVISIONED",
            ProvisionedThroughput={
                "ReadCapacityUnits": 1,
                "WriteCapacityUnits": 1,
            },
        )
        print(f"Table '{TABLE_NAME}' created. Waiting for ACTIVE status...")

        waiter = client.get_waiter("table_exists")
        waiter.wait(TableName=TABLE_NAME)

        client.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={
                "Enabled": True,
                "AttributeName": "ttl",
            },
        )
        print(f"TTL enabled on 'ttl' column. Table ready.")
        return 0

    except client.exceptions.ResourceInUseException:
        print(f"Table '{TABLE_NAME}' already exists.")
        return 0

    except Exception as exc:
        print(f"ERROR: table creation failed: {exc}", file=sys.stderr)
        return 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Distributed routine lock via DynamoDB.")
    sub = parser.add_subparsers(dest="command")

    acq = sub.add_parser("acquire")
    acq.add_argument("routine")
    acq.add_argument("--cycle")
    acq.add_argument("--ttl", type=int, default=TTL_DEFAULT)

    rel = sub.add_parser("release")
    rel.add_argument("routine")
    rel.add_argument("--cycle")

    st = sub.add_parser("status")
    st.add_argument("routine")
    st.add_argument("--cycle")

    sub.add_parser("setup-table")

    args = parser.parse_args()

    if args.command == "acquire":
        return acquire(args.routine, args.cycle, args.ttl)
    elif args.command == "release":
        return release(args.routine, args.cycle)
    elif args.command == "status":
        return status(args.routine, args.cycle)
    elif args.command == "setup-table":
        return setup_table()
    else:
        parser.print_help()
        return 2


if __name__ == "__main__":
    sys.exit(main())
