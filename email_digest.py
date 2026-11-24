"""Format the filtered papers as an email and send it over SMTP."""

from __future__ import annotations

import os
import smtplib
import ssl
import textwrap
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


def build_message(
    papers: list[Paper], since: datetime, until: datetime, cfg: EmailConfig
) -> EmailMessage:
    """Build a digest email with a plain-text body and an HTML alternative."""
    n = len(papers)
    span = _date_range(since, until)
    noun = "paper" if n == 1 else "papers"

    msg = EmailMessage()
    msg["Subject"] = f"ePrint digest: {n} {noun} ({span})"
    msg["From"] = cfg.from_addr
    msg["To"] = ", ".join(cfg.to)
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = make_msgid(domain=cfg.from_addr.rpartition("@")[2] or None)

    verb = "was" if n == 1 else "were"
    intro = f"{n} {noun} matching your filters {verb} posted or updated on IACR ePrint, {span}."
    if n == 0:
        intro = f"No papers matching your filters were posted or updated on IACR ePrint, {span}."

    # Plain text: shown by mail clients that don't render HTML.
    lines = [intro, ""]
    for p in papers:
        lines += [
            f"[{p.id}] {p.title}",
            f"  {', '.join(p.authors)}",
            f"  {p.url}",
            "",
            *_wrap(p.abstract, indent="  "),
            "",
            "-" * 72,
            "",
        ]
    msg.set_content("\n".join(lines))

    # HTML: every field from ePrint is escaped so stray < or & can't break layout.
    items = "\n".join(
        f"""<div style="margin:0 0 28px">
  <div style="font-size:16px;font-weight:600;line-height:1.35">
    <a href="{escape(p.url, quote=True)}" style="color:#1a4f8b;text-decoration:none">{escape(p.title)}</a>
  </div>
  <div style="color:#555;font-size:14px;margin:4px 0 8px">{escape(", ".join(p.authors))}
    &middot; <span style="color:#888">{escape(p.id)}</span></div>
  <div style="font-size:14px;line-height:1.5;color:#222">{escape(p.abstract)}</div>
</div>"""
        for p in papers
    )
    html = f"""<!doctype html>
<html><body style="margin:0;padding:24px 16px;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif">
<div style="max-width:680px;margin:0 auto">
  <p style="font-size:15px;color:#333;margin:0 0 24px">{escape(intro)}</p>
  {items}
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
