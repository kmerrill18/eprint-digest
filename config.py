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
class LLMConfig:
    interests: str
    model: str = "anthropic/claude-opus-5-5"  # any LiteLLM model string
    max_top_picks: int = 5
    abstract_preview_chars: int = 300  # "Also relevant" previews; 0 = none, -1 = full
    api_base: str | None = None  # for local/self-hosted servers


@dataclass
class Config:
    filter: Filter
    email: EmailConfig | None  # None if the [email] section is absent
    llm: LLMConfig | None = None  # None if the [llm] section is absent


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
    _check_keys("top level", data, {"filter", "email", "llm"})

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

    llm = None
    if "llm" in data:
        lt = data["llm"]
        _check_keys(
            "llm", lt,
            {"interests", "model", "max_top_picks", "abstract_preview_chars", "api_base"},
        )
        interests = lt.get("interests")
        if not isinstance(interests, str) or not interests.strip():
            raise ValueError("[llm] needs a non-empty `interests` paragraph")
        llm = LLMConfig(
            interests=interests.strip(),
            model=lt.get("model", LLMConfig.model),
            max_top_picks=_int("llm", "max_top_picks", lt.get("max_top_picks", 5), min_=0),
            abstract_preview_chars=_int(
                "llm", "abstract_preview_chars", lt.get("abstract_preview_chars", 300), min_=-1
            ),
            api_base=lt.get("api_base"),
        )

    return Config(filter=filt, email=email, llm=llm)


def _int(section: str, key: str, value: Any, min_: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < min_:
        raise ValueError(f"[{section}] {key} must be an integer >= {min_}")
    return value
