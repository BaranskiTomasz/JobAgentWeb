import re
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._fragments: list[str] = []

    def handle_data(self, data: str) -> None:
        self._fragments.append(data)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"p", "br", "li", "div", "h1", "h2", "h3", "h4", "h5", "h6"}:
            self._fragments.append("\n")

    def to_text(self) -> str | None:
        joined = "".join(self._fragments)
        lines = [" ".join(line.split()) for line in joined.split("\n")]
        result = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
        return result or None


def strip_html(html: str) -> str | None:
    if not html or not html.strip():
        return None
    extractor = _TextExtractor()
    extractor.feed(html)
    return extractor.to_text()


# LinkedIn appends page chrome after the real job text (footer links, "people also
# viewed", pagination), cut at the earliest of these markers. Other sources don't
# have this pattern and pass through unchanged.
_LINKEDIN_JUNK_MARKERS = (
    "Set alert for similar jobs", "Accessibility", "People also viewed",
    "Similar jobs", "Show more", "Show less",
)

# Safety-net cap for every LLM/embedding call that reads a job description; a
# backstop against a pathological outlier, not a real trim in practice.
_MAX_DESCRIPTION_CHARS = 6000

# LinkedIn's fetch_description() already fetches up to 8000 raw chars, and a
# measured sample of 100 recent postings found 20% still over 6000 chars even
# after strip_description_junk, real content getting cut, not junk. Capping at
# 8000 here matches what was already paid for in the stealth fetch.
_MAX_DESCRIPTION_CHARS_BY_SOURCE = {"linkedin": 8000}


def strip_description_junk(description: str, source: str) -> str:
    if source != "linkedin" or not description:
        return description
    cut = len(description)
    for marker in _LINKEDIN_JUNK_MARKERS:
        idx = description.find(marker)
        if idx != -1:
            cut = min(cut, idx)
    return description[:cut].rstrip()


def build_excerpt(description: str | None, source: str) -> str:
    # Every consumption point should go through this rather than reading
    # job['description'] directly, so junk-stripping and the length cap stay
    # consistent instead of each call site picking its own ad-hoc limit.
    if not description:
        return ""
    cleaned = strip_description_junk(description, source)
    cap = _MAX_DESCRIPTION_CHARS_BY_SOURCE.get(source, _MAX_DESCRIPTION_CHARS)
    return cleaned[:cap]


# Below this, an excerpt is treated as a short preview rather than a genuinely
# short (but complete) posting, sized off a real measurement: itpracuj's
# search-result preview runs 113-250 chars, while every other source's true
# minimum sits at 300+. Not source-keyed on purpose: any source can
# occasionally hand back a thin excerpt.
_MIN_COMPLETE_DESCRIPTION_CHARS = 400


def excerpt_looks_incomplete(excerpt: str) -> bool:
    # True only for a short-but-present excerpt; a missing one already
    # returns "" from build_excerpt, a different case handled upstream.
    return 0 < len(excerpt) < _MIN_COMPLETE_DESCRIPTION_CHARS


# Appended by prompt-building call sites when excerpt_looks_incomplete() is
# true, so the LLM never penalizes an absence it can't confirm. Not applied to
# the embedder/reranker: those read the excerpt as plain text for similarity
# scoring, not as an instruction-following LLM, so this note would just be
# noise in their input.
INCOMPLETE_DESCRIPTION_NOTE = (
    " [Note: this description is a short preview, not the full posting, the source "
    "doesn't provide more. Missing requirements/stack/salary/benefits details may "
    "simply not be captured here; treat them as unknown, not as a negative signal.]"
)
