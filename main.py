"""Command-line entry point: fetch recent ePrint papers and filter them.

Examples:
    python3 main.py                                   # everything from the last 7 days
    python3 main.py --keyword lattice --keyword '\\bMPC\\b'
    python3 main.py --author Ostrovsky --since 2026-11-20
    python3 main.py --keyword lattice --json > out.json
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from filters import Filter
from harvest import harvest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Fetch ePrint papers updated since a time and filter them."
    )
    p.add_argument(
        "--since",
        help="ISO date or timestamp, UTC if no timezone given (default: 7 days ago)",
    )
    p.add_argument(
        "--days", type=float, default=7, help="look back this many days (default: 7)"
    )
    p.add_argument(
        "-k", "--keyword", action="append",
        help="regex searched in title + abstract; repeat for more",
    )
    p.add_argument(
        "-a", "--author", action="append",
        help="text searched in author names; repeat for more",
    )
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.since:
        since = datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    else:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    try:
        # Flags that weren't given stay None, which means "don't filter on this".
        filt = Filter(keywords=args.keyword, authors=args.author)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    papers = list(harvest(since))
    kept = list(filt.apply(papers))

    if args.json:
        json.dump([asdict(p) for p in kept], sys.stdout, default=str, indent=2)
        print()
    else:
        for p in kept:
            print(f"[{p.id}] {p.title}")
            print(f"  {', '.join(p.authors)}")
            print(f"  {p.url}\n")
    print(
        f"{len(kept)} of {len(papers)} papers updated since "
        f"{since:%Y-%m-%d %H:%M} UTC matched",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
