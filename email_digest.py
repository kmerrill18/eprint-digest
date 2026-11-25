"""Format the filtered papers as an email and send it over SMTP."""

from __future__ import annotations

import os
import smtplib
import ssl
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from html import escape

from config import EmailConfig
from harvest import Paper

# The SMTP password is read from this environment variable (a GitHub secret
# in Actions). It is never stored in the config file.
PASSWORD_ENV = "EPRINT_DIGEST_SMTP_PASSWORD"


def _date_range(since: datetime, until: datetime) -> str:
    return f"{since:%b %-d} – {until:%b %-d, %Y}"


@dataclass
class Entry:
    """One paper in the digest, plus why it's there (only shown when ranked)."""

    paper: Paper
    tags: list[str] = field(default_factory=list)  # e.g. ["keyword", "LLM"]
    reason: str = ""  # the LLM's one-line "why"


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def _preview(abstract: str, chars: int) -> str:
    """First `chars` characters, cut at a word boundary. -1 = full, 0 = none."""
    if chars < 0 or len(abstract) <= chars:
        return abstract
    if chars == 0:
        return ""
    cut = abstract[: chars + 1].rsplit(" ", 1)[0] if " " in abstract[:chars] else abstract[:chars]
    return cut.rstrip(" ,;:.") + "…"


def build_message(
    top: list[Entry],
    rest: list[Entry],
    since: datetime,
    until: datetime,
    cfg: EmailConfig,
    *,
    ranked: bool = False,
    preview_chars: int = -1,
    note: str | None = None,
    footer: str | None = None,
) -> EmailMessage:
    """Build a digest email with a plain-text body and an HTML alternative.

    ranked=False: one flat list (`rest`) with full abstracts, as before the LLM step.
    ranked=True:  "Top picks" (full abstracts + reasons), then "Also relevant"
                  (abstracts shortened to `preview_chars`, tagged with why they matched).
    `note` (e.g. "LLM picks unavailable") goes under the intro; `footer` at the end.
    """
    span = _date_range(since, until)
    n = len(top) + len(rest)

    msg = EmailMessage()
    if ranked:
        msg["Subject"] = (
            f"ePrint digest: {_plural(len(top), 'top pick')}, {len(rest)} more ({span})"
        )
        intro = (
            f"{_plural(len(top), 'top pick')} and {len(rest)} more relevant "
            f"{'paper' if len(rest) == 1 else 'papers'} posted or updated on IACR ePrint, {span}."
        )
    else:
        msg["Subject"] = f"ePrint digest: {_plural(n, 'paper')} ({span})"
        verb = "was" if n == 1 else "were"
        intro = f"{_plural(n, 'paper')} matching your filters {verb} posted or updated on IACR ePrint, {span}."
        if n == 0:
            intro = f"No papers matching your filters were posted or updated on IACR ePrint, {span}."
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(cfg.to)
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=cfg.from_addr.rpartition("@")[2] or None)

    # (heading, entries, abstract chars, show tags, show "why")
    if ranked:
        sections = [
            ("Top picks", top, -1, True, True),
            ("Also relevant", rest, preview_chars, True, False),
        ]
    else:
        sections = [(None, rest, -1, False, False)]

    # Plain text: shown by mail clients that don't render HTML.
    lines = [intro, ""]
    if note:
        lines += [note, ""]
    for heading, entries, chars, show_tags, show_why in sections:
        if heading:
            lines += [f"== {heading} ({len(entries)}) ==", ""]
        for e in entries:
            p = e.paper
            lines += [f"[{p.id}] {p.title}", f"  {', '.join(p.authors)}", f"  {p.url}"]
            if show_tags and e.tags:
                lines.append(f"  [{'] ['.join(e.tags)}]")
            if show_why and e.reason:
                lines.append(f"  Why: {e.reason}")
            abstract = _preview(p.abstract, chars)
            if abstract:
                lines += ["", *_wrap(abstract, indent="  ")]
            lines += ["", "-" * 72, ""]
    if footer:
        lines += [footer]
    msg.set_content("\n".join(lines))

    # HTML: every field from ePrint is escaped so stray < or & can't break layout.
    def item(e: Entry, chars: int, show_tags: bool, show_why: bool) -> str:
        p = e.paper
        tags = ""
        if show_tags and e.tags:
            tags = " &middot; " + " ".join(
                f'<span style="color:#666;background:#eef1f5;border-radius:3px;'
                f'padding:0 4px;font-size:12px">{escape(t)}</span>'
                for t in e.tags
            )
        reason = (
            f'<div style="font-size:14px;color:#1a4f8b;margin:0 0 6px">'
            f"<b>Why:</b> {escape(e.reason)}</div>"
            if show_why and e.reason
            else ""
        )
        abstract = _preview(p.abstract, chars)
        abstract_html = (
            f'<div style="font-size:14px;line-height:1.5;color:#222">{escape(abstract)}</div>'
            if abstract
            else ""
        )
        return f"""<div style="margin:0 0 28px">
  <div style="font-size:16px;font-weight:600;line-height:1.35">
    <a href="{escape(p.url, quote=True)}" style="color:#1a4f8b;text-decoration:none">{escape(p.title)}</a>
  </div>
  <div style="color:#555;font-size:14px;margin:4px 0 8px">{escape(", ".join(p.authors))}
    &middot; <span style="color:#888">{escape(p.id)}</span>{tags}</div>
  {reason}{abstract_html}
</div>"""

    parts = []
    for heading, entries, chars, show_tags, show_why in sections:
        if heading:
            parts.append(
                f'<h2 style="font-size:18px;color:#333;border-bottom:1px solid #ddd;'
                f'padding-bottom:4px;margin:32px 0 16px">{escape(heading)} ({len(entries)})</h2>'
            )
        parts += [item(e, chars, show_tags, show_why) for e in entries]
    items = "\n".join(parts)
    note_html = (
        f'<p style="font-size:14px;color:#8a5a00;margin:-12px 0 24px">{escape(note)}</p>'
        if note
        else ""
    )
    footer_html = (
        f'<p style="font-size:12px;color:#888;border-top:1px solid #eee;'
        f'padding-top:12px;margin-top:32px">{escape(footer)}</p>'
        if footer
        else ""
    )
    html = f"""<!doctype html>
<html><body style="margin:0;padding:24px 16px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
<div style="max-width:680px;margin:0 auto">
  <p style="font-size:15px;color:#333;margin:0 0 24px">{escape(intro)}</p>
  {note_html}{items}{footer_html}
</div>
</body></html>"""
    msg.add_alternative(html, subtype="html")
    return msg


def _wrap(text: str, indent: str, width: int = 76) -> list[str]:
    return textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=indent)


def send(msg: EmailMessage, cfg: EmailConfig, password: str | None = None) -> None:
    """Send via SMTP. Port 465 uses SSL from the start; other ports use STARTTLS."""
    password = password or os.environ.get(PASSWORD_ENV)
    if not password:
        raise RuntimeError(f"no SMTP password: set the {PASSWORD_ENV} environment variable")
    context = ssl.create_default_context()
    if cfg.smtp_port == 465:
        with smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, context=context, timeout=60) as s:
            s.login(cfg.login, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=60) as s:
            s.starttls(context=context)
            s.login(cfg.login, password)
            s.send_message(msg)
