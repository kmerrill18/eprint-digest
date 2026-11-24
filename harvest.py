"""Harvest paper metadata from the IACR ePrint OAI-PMH endpoint.

Docs: https://eprint.iacr.org/rss/  (endpoint: https://eprint.iacr.org/oai)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterator

OAI_URL = "https://eprint.iacr.org/oai"
NS = {
    "oai": "http://www.openarchives.org/OAI/2.0/",
    "oai_dc": "http://www.openarchives.org/OAI/2.0/oai_dc/",
    "dc": "http://purl.org/dc/elements/1.1/",
}


@dataclass
class Paper:
    id: str  # e.g. "2026/3000"
    url: str
    title: str
    authors: list[str]
    abstract: str
    datestamp: datetime  # last-modified time per OAI (includes revisions)
    subjects: list[str] = field(default_factory=list)


def _fmt(ts: datetime) -> str:
    """Format a datetime as the OAI second-granularity UTC string."""
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _fetch(params: dict[str, str], retries: int = 3) -> ET.Element:
    url = f"{OAI_URL}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "eprint-digest/0.1"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return ET.fromstring(resp.read())
        except urllib.error.HTTPError as e:
            # OAI servers use 503 + Retry-After for flow control.
            if e.code == 503 and attempt < retries - 1:
                time.sleep(int(e.headers.get("Retry-After", 10)))
                continue
            raise
        except urllib.error.URLError:
            if attempt < retries - 1:
                time.sleep(2**attempt)
                continue
            raise
    raise RuntimeError("unreachable")


def _text(el: ET.Element, path: str) -> str:
    found = el.find(path, NS)
    return " ".join((found.text or "").split()) if found is not None else ""


def _parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.strip().replace("Z", "+00:00"))


def _parse_record(rec: ET.Element) -> Paper | None:
    header = rec.find("oai:header", NS)
    if header is None or header.get("status") == "deleted":
        return None
    dc = rec.find("oai:metadata/oai_dc:dc", NS)
    if dc is None:
        return None
    oai_id = _text(header, "oai:identifier")
    return Paper(
        id=oai_id.removeprefix("oai:eprint.iacr.org:"),
        url=_text(dc, "dc:identifier"),
        title=_text(dc, "dc:title"),
        authors=[" ".join((c.text or "").split()) for c in dc.findall("dc:creator", NS)],
        abstract=_text(dc, "dc:description"),
        datestamp=_parse_ts(_text(header, "oai:datestamp")),
        subjects=[(s.text or "").strip() for s in dc.findall("dc:subject", NS) if s.text],
    )


def harvest(since: datetime, until: datetime | None = None) -> Iterator[Paper]:
    """Yield every paper whose OAI datestamp is >= `since` (and <= `until`).

    Note: the OAI datestamp is the last-modified time, so revised older papers
    show up too. Follows resumptionTokens for paging.
    """
    params = {"verb": "ListRecords", "metadataPrefix": "oai_dc", "from": _fmt(since)}
    if until is not None:
        params["until"] = _fmt(until)
    while True:
        root = _fetch(params)
        err = root.find("oai:error", NS)
        if err is not None:
            if err.get("code") == "noRecordsMatch":
                return
            raise RuntimeError(f"OAI error {err.get('code')}: {err.text}")
        for rec in root.iterfind("oai:ListRecords/oai:record", NS):
            paper = _parse_record(rec)
            if paper is not None:
                yield paper
        token = root.find("oai:ListRecords/oai:resumptionToken", NS)
        token_text = (token.text or "").strip() if token is not None else ""
        if not token_text:
            return
        params = {"verb": "ListRecords", "resumptionToken": token_text}


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Fetch ePrint papers since a timestamp.")
    p.add_argument("--since", help="ISO timestamp (UTC if no tz). Default: 7 days ago.")
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text.")
    args = p.parse_args(argv)

    since = (
        datetime.fromisoformat(args.since)
        if args.since
        else datetime.now(timezone.utc) - timedelta(days=7)
    )
    papers = list(harvest(since))
    if args.json:
        json.dump([asdict(x) for x in papers], sys.stdout, default=str, indent=2)
        print()
    else:
        for x in papers:
            print(f"[{x.id}] {x.title}\n  {', '.join(x.authors)}\n  {x.abstract[:200]}...\n")
        print(f"{len(papers)} papers since {_fmt(since)}", file=sys.stderr)


if __name__ == "__main__":
    main()
