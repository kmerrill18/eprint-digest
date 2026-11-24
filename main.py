"""Command-line entry point: fetch recent ePrint papers and filter them.

Examples:
    python3 main.py                                   # everything from the last 7 days
    python3 main.py --keyword lattice --keyword '\\bMPC\\b'
    python3 main.py --author Ostrovsky --since 2026-11-20
    python3 main.py --keyword lattice --json > out.json
    python3 main.py --config config.toml              # filters from a config file
    python3 main.py -c config.toml --preview out.html # write the digest email as HTML
    python3 main.py -c config.toml --send             # email it (needs EPRINT_DIGEST_SMTP_PASSWORD)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from config import Config, load_config
from email_digest import PASSWORD_ENV, build_message, send
from filters import Filter
from harvest import harvest


def _redact(addr: str) -> str:
    """"example@example.com" -> "e******@example.com"."""
    user, at, domain = addr.partition("@")
    return f"{user[:1]}{'*' * max(len(user) - 1, 1)}{at}{domain}"


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
    p.add_argument(
        "-c", "--config",
        help="TOML file with [filter] settings (can't be combined with -k/-a)",
    )
    p.add_argument(
        "--preview", metavar="FILE",
        help="write the digest email's HTML to FILE (needs --config with [email])",
    )
    p.add_argument(
        "--send", action="store_true",
        help=f"email the digest (needs --config with [email] and ${PASSWORD_ENV})",
    )
    p.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = p.parse_args(argv)
    if args.config and (args.keyword or args.author):
        p.error("use either --config or -k/-a, not both")
    if (args.send or args.preview) and not args.config:
        p.error("--send and --preview need --config (for the [email] settings)")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.since:
        since = datetime.fromisoformat(args.since)
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
    else:
        since = datetime.now(timezone.utc) - timedelta(days=args.days)

    cfg: Config | None = None
    try:
        if args.config:
            cfg = load_config(args.config)
            filt = cfg.filter
            if (args.send or args.preview) and cfg.email is None:
                raise ValueError(f"{args.config} has no [email] section")
        else:
            # Flags that weren't given stay None, meaning "don't filter on this".
            filt = Filter(keywords=args.keyword, authors=args.author)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    until = datetime.now(timezone.utc)
    papers = list(harvest(since))
    kept = list(filt.apply(papers))

    if args.send or args.preview:
        assert cfg is not None and cfg.email is not None
        msg = build_message(kept, since, until, cfg.email)
        if args.preview:
            body = msg.get_body(preferencelist=("html",))
            assert body is not None
            with open(args.preview, "w", encoding="utf-8") as f:
                f.write(body.get_content())
            print(f"wrote preview to {args.preview}", file=sys.stderr)
        if args.send:
            try:
                send(msg, cfg.email)
            except Exception as e:
                print(f"error: sending failed: {e}", file=sys.stderr)
                return 1
            to = cfg.email.to
            # Logs of GitHub Actions runs are public for public repos.
            if os.environ.get("GITHUB_ACTIONS") == "true":
                to = [_redact(a) for a in to]
            print(f"sent {msg['Subject']!r} to {', '.join(to)}", file=sys.stderr)
        return 0

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
