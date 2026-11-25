"""Command-line entry point: fetch recent ePrint papers and filter them.

Examples:
    python3 main.py                                   # everything from the last 7 days
    python3 main.py --keyword lattice --keyword '\\bMPC\\b'
    python3 main.py --author Lastname --since 2026-11-20
    python3 main.py --keyword lattice --json > out.json
    python3 main.py --config config.toml              # filters from a config file
    python3 main.py -c config.toml --preview out.html # write the digest email as HTML
    python3 main.py -c config.toml --send             # email it (needs EPRINT_DIGEST_SMTP_PASSWORD)
    python3 main.py -c config.toml --no-llm           # skip the [llm] ranking step
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict
from datetime import datetime, timedelta, timezone

from config import Config, load_config
from email_digest import PASSWORD_ENV, Entry, build_message, send
from filters import Filter
from harvest import Paper, harvest
from rank import RankError, RankResult, rank


def _redact(addr: str) -> str:
    """"example@example.com" -> "e******@example.com"."""
    user, at, domain = addr.partition("@")
    return f"{user[:1]}{'*' * max(len(user) - 1, 1)}{at}{domain}"


def assemble(
    papers: list[Paper], filt: Filter, result: RankResult
) -> tuple[list[Entry], list[Entry]]:
    """Split papers into (top picks, also relevant) using filters + LLM judgments.

    A paper is included if a keyword/author filter matched it OR the LLM marked it
    top/relevant. With no filters configured, only the LLM's picks are included.
    """
    top: list[Entry] = []
    rest: list[Entry] = []
    for p in papers:
        tags = sorted(filt.match_reasons(p))  # "author", "keyword"
        j = result.judgments.get(p.id)
        if j is not None:
            tags.append("LLM")
        if not tags:
            continue
        entry = Entry(paper=p, tags=tags, reason=j.reason if j else "")
        (top if j is not None and j.tier == "top" else rest).append(entry)

    def score(e: Entry) -> int:
        j = result.judgments.get(e.paper.id)
        return j.score if j else -1

    # Stable sorts: equal scores keep ePrint's order.
    top.sort(key=score, reverse=True)
    rest.sort(key=score, reverse=True)
    return top, rest


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
    p.add_argument(
        "--no-llm", action="store_true",
        help="skip the [llm] ranking step even if the config has one",
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

    # Optional LLM step. Any failure falls back to the plain filter-only digest.
    result: RankResult | None = None
    note = footer = None
    if cfg is not None and cfg.llm is not None and not args.no_llm:
        try:
            result = rank(papers, cfg.llm)
        except RankError as e:
            print(f"warning: {e}; falling back to filter matches only", file=sys.stderr)
            note = "Top picks are unavailable this week (the LLM step failed); showing filter matches only."
        else:
            footer = result.usage.summary(result.model)
            print(footer, file=sys.stderr)

    if result is not None:
        top, rest = assemble(papers, filt, result)
    else:
        top, rest = [], [Entry(paper=p) for p in kept]

    if args.send or args.preview:
        assert cfg is not None and cfg.email is not None
        msg = build_message(
            top, rest, since, until, cfg.email,
            ranked=result is not None,
            preview_chars=cfg.llm.abstract_preview_chars if cfg.llm else -1,
            note=note,
            footer=footer,
        )
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

    entries = [(e, "top") for e in top] + [(e, "relevant" if result else None) for e in rest]
    if args.json:
        out = []
        for e, section in entries:
            d = asdict(e.paper)
            if result is not None:
                j = result.judgments.get(e.paper.id)
                d |= {"section": section, "tags": e.tags,
                      "score": j.score if j else None, "reason": e.reason}
            out.append(d)
        json.dump(out, sys.stdout, default=str, indent=2)
        print()
    else:
        for e, section in entries:
            p = e.paper
            label = f"{'TOP ' if section == 'top' else ''}[{p.id}]"
            print(f"{label} {p.title}")
            print(f"  {', '.join(p.authors)}")
            if e.tags:
                print(f"  [{'] ['.join(e.tags)}]")
            if e.reason:
                print(f"  Why: {e.reason}")
            print(f"  {p.url}\n")
    if result is not None:
        print(
            f"{len(top)} top picks + {len(rest)} more of {len(papers)} papers updated since "
            f"{since:%Y-%m-%d %H:%M} UTC",
            file=sys.stderr,
        )
    else:
        print(
            f"{len(kept)} of {len(papers)} papers updated since "
            f"{since:%Y-%m-%d %H:%M} UTC matched",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
