"""Filters for selecting which harvested papers go in the digest."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, Iterator

from harvest import Paper

# Letters that don't decompose into base letter + accent under Unicode rules.
_SPECIAL = str.maketrans(
    {
        "ı": "i",
        "ø": "o",
        "Ø": "O",
        "ł": "l",
        "Ł": "L",
        "đ": "d",
        "Đ": "D",
        "ß": "ss",
        "æ": "ae",
        "Æ": "AE",
        "œ": "oe",
        "Œ": "OE",
    }
)


def _strip_accents(s: str) -> str:
    """Remove accents without changing case: "Alïce Bøb" -> "Alice Bob"."""
    s = unicodedata.normalize("NFKD", s.translate(_SPECIAL))
    return "".join(c for c in s if not unicodedata.combining(c))


def _fold(s: str) -> str:
    """Lowercase and strip accents, so "Alïce Bøb" and "alice bob" compare equal.

    Used for author matching, which is plain substring search and so has no
    case-insensitive flag. Keywords use _strip_accents + re.IGNORECASE instead.
    """
    return _strip_accents(s.casefold())


@dataclass
class Filter:
    r"""Which papers to keep.

    Each field is either None (don't filter on this) or a list of terms.
    Matching ignores case and accents and matches substrings, so "lattice" also
    matches "Lattices", and "Bob" matches "Alice Bob".

    Keywords are regular expressions (e.g. r"\bMPC\b", r"post-?quantum").
    Escape regex symbols to match them literally: r"C\+\+".
    Keywords ignore case unless you turn it off: r"(?-i:\bMPC\b)".

    When several fields are set, a paper is kept if it matches ANY of them
    (e.g. "papers about lattices, plus anything by Bob").
    """

    keywords: list[str] | None = None  # searched in title + abstract
    authors: list[str] | None = None  # searched in each author's name

    _patterns: list[re.Pattern[str]] = field(
        init=False, repr=False, default_factory=list
    )

    def __post_init__(self) -> None:
        # Compile up front so a bad regex fails immediately, not mid-digest.
        # Accents are stripped from both pattern and text; case is handled by
        # re.IGNORECASE so patterns can turn it off with (?-i:...).
        for k in self.keywords or []:
            try:
                self._patterns.append(re.compile(_strip_accents(k), re.IGNORECASE))
            except re.error as e:
                raise ValueError(f"invalid keyword regex {k!r}: {e}") from e

    def match_reasons(self, paper: Paper) -> set[str]:
        """Which filters matched: a subset of {"keyword", "author"}."""
        reasons = set()
        if self.keywords is not None:
            # Keep case so patterns can opt into case-sensitivity, e.g. r"(?-i:MPC)".
            text = _strip_accents(f"{paper.title}\n{paper.abstract}")
            if any(p.search(text) for p in self._patterns):
                reasons.add("keyword")
        if self.authors is not None:
            names = [_fold(a) for a in paper.authors]
            if any(_fold(q) in n for q in self.authors for n in names):
                reasons.add("author")
        return reasons

    def matches(self, paper: Paper) -> bool:
        # No fields set means no filtering: keep everything.
        if self.keywords is None and self.authors is None:
            return True
        return bool(self.match_reasons(paper))

    def apply(self, papers: Iterable[Paper]) -> Iterator[Paper]:
        return (p for p in papers if self.matches(p))
