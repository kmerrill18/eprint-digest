"""Load digest settings from a TOML file (see config.toml)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from filters import Filter


@dataclass
class EmailConfig:
    from_addr: str
    to: list[str]
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    username: str | None = None  # defaults to from_addr

    @property
    def login(self) -> str:
        return self.username or self.from_addr


@dataclass
class Config:
    filter: Filter
    email: EmailConfig | None  # None if the [email] section is absent


def _check_keys(section: str, table: dict[str, Any], allowed: set[str]) -> None:
    """Fail loudly on typos like `keyword =` instead of silently ignoring them."""
    unknown = set(table) - allowed
    if unknown:
        raise ValueError(
            f"unknown setting(s) in [{section}]: {', '.join(sorted(unknown))} "
            f"(allowed: {', '.join(sorted(allowed))})"
        )


def _str_list(section: str, key: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ValueError(f"[{section}] {key} must be a list of strings")
    return value


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    _check_keys("top level", data, {"filter", "email"})

    # [filter]: a missing key means "don't filter on this".
    ft = data.get("filter", {})
    _check_keys("filter", ft, {"keywords", "authors"})
    filt = Filter(
        keywords=_str_list("filter", "keywords", ft["keywords"]) if "keywords" in ft else None,
        authors=_str_list("filter", "authors", ft["authors"]) if "authors" in ft else None,
    )

    email = None
    if "email" in data:
        et = data["email"]
        _check_keys("email", et, {"from", "to", "smtp_host", "smtp_port", "username"})
        for key in ("from", "to"):
            if key not in et:
                raise ValueError(f"[email] is missing required setting `{key}`")
        to = et["to"]
        email = EmailConfig(
            from_addr=et["from"],
            to=[to] if isinstance(to, str) else _str_list("email", "to", to),
            smtp_host=et.get("smtp_host", "smtp.gmail.com"),
            smtp_port=int(et.get("smtp_port", 587)),
            username=et.get("username"),
        )

    return Config(filter=filt, email=email)
