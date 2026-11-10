"""Finds interview questions candidates have reported for a company/role.

Uses Claude's server-side web search across the open web, steered toward first-hand reports
(Glassdoor, Blind, LeetCode Discuss, interview-experience write-ups). Nothing is scraped directly: the
search tool only sees what sites expose publicly to search, which avoids login walls, anti-bot measures
and terms-of-service problems.

Reddit never appears in results: it blocks Anthropic's crawler (naming `reddit.com` in
`allowed_domains` is a 400). Adding Reddit would need its official API as a separate source.

Only questions reported in the last MAX_REPORT_AGE_MONTHS months are kept, using the report's own
date when the model can see one and the search result's page_age otherwise. Undated questions are
kept but ranked after dated ones.

Research is best-effort. Any failure (API error, refusal, nothing found) returns no questions, and
question generation falls back to working from the job description alone.
"""

import logging
import re
from datetime import date, datetime, timedelta
from typing import TypedDict
from urllib.parse import urlparse

import anthropic

logger = logging.getLogger(__name__)

RESEARCH_MODEL = "claude-opus-5-5"
MAX_SEARCHES = 8
MAX_CONTINUATIONS = 5

# Interview processes change; questions reported longer ago than this are dropped.
MAX_REPORT_AGE_MONTHS = 24

# Friendly names for common sources; anything else is labeled by its hostname.
KNOWN_SOURCES = {
    "glassdoor.com": "Glassdoor",
    "glassdoor.co.in": "Glassdoor",
    "glassdoor.co.uk": "Glassdoor",
    "teamblind.com": "Blind",
    "leetcode.com": "LeetCode",
    "medium.com": "Medium",
    "indeed.com": "Indeed",
    "levels.fyi": "Levels.fyi",
    "interviewing.io": "interviewing.io",
    "igotanoffer.com": "IGotAnOffer",
    "prepfully.com": "Prepfully",
}

REPORT_TOOL_NAME = "report_findings"


class ReportedQuestion(TypedDict):
    text: str
    source: str  # display name of the site, e.g. "Glassdoor" or "example.com"
    url: str
    reported_date: str  # "YYYY-MM" (or "YYYY") when known, else ""


class ResearchResult(TypedDict):
    company: str
    role: str
    questions: list[ReportedQuestion]


EMPTY_RESULT: ResearchResult = {"company": "", "role": "", "questions": []}

RESEARCH_SYSTEM_PROMPT = """You research what candidates report being asked in interviews, so a candidate \
can practice realistic questions.

Use web search to find interview questions that candidates say they were actually asked for this company \
and role, preferring the screening/recruiter/early rounds. Try a few query phrasings (e.g. "<company> <role> \
interview questions", "<company> interview experience <role>", "site:glassdoor.com <company> interview").

Prefer first-hand sources: Glassdoor interview reviews, Blind posts, LeetCode Discuss interview \
experiences, and personal blog/Medium write-ups of a specific interview. Skip generic listicles \
("top 50 interview questions") and prep-course marketing pages unless they cite questions reported for \
this specific company.

Rules:
- Only report questions reported within the time window given in the request. Interview processes change, \
so recent reports matter. Adding the current or previous year to queries helps surface recent posts.
- For each question, give reported_date: the date of the review/post/interview itself (YYYY-MM, or YYYY if \
only the year is known), taken from the result content - not when the page was last updated. Aggregate \
pages like Glassdoor list many reviews with their own dates; use the date of the review containing the \
question. Use an empty string if no date is visible.
- Only report questions that a source actually says was asked. Do not invent, generalize, or infer questions.
- Each question must come with the URL of the search result it came from.
- Rewrite each question as a single clear question an interviewer would say aloud, keeping its meaning.
- Drop duplicates, pure coding-puzzle statements that can't be answered verbally, and anything unrelated to \
the role.
- Report at most 10 questions, most relevant to the job description first.
- If you find nothing credible, report an empty list. That is a fine outcome.

When you are done searching, call the report_findings tool exactly once with your results."""

REPORT_TOOL = {
    "name": REPORT_TOOL_NAME,
    "description": "Report the company, role, and the interview questions found during research. Call once, at the end.",
    "strict": True,
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["company", "role", "questions"],
        "properties": {
            "company": {
                "type": "string",
                "description": "The hiring company's name, or an empty string if it can't be determined.",
            },
            "role": {"type": "string", "description": "The role/job title being hired for."},
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "url", "reported_date"],
                    "properties": {
                        "text": {"type": "string", "description": "The interview question."},
                        "url": {"type": "string", "description": "URL of the search result reporting it."},
                        "reported_date": {
                            "type": "string",
                            "description": "Date of the report itself as YYYY-MM or YYYY, or empty string if unknown.",
                        },
                    },
                },
            },
        },
    },
}


def source_for_url(url: str) -> str | None:
    """Display name for the site a URL is on, or None if the URL has no host."""
    host = (urlparse(url).hostname or "").lower()
    if not host:
        return None
    for domain, name in KNOWN_SOURCES.items():
        if host == domain or host.endswith("." + domain):
            return name
    return host.removeprefix("www.")


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("old.")
    return f"{host}{parsed.path.rstrip('/')}"


_RELATIVE_AGE = re.compile(r"(\d+)\s+(hour|day|week|month|year)s?\s+ago", re.IGNORECASE)
_DAYS_PER_UNIT = {"hour": 0, "day": 1, "week": 7, "month": 30, "year": 365}


def _parse_page_age(page_age: str | None, today: date) -> date | None:
    """Search results give page_age like "326 days ago" (sometimes an absolute date, or nothing)."""
    if not page_age:
        return None
    match = _RELATIVE_AGE.search(page_age)
    if match:
        return today - timedelta(days=int(match.group(1)) * _DAYS_PER_UNIT[match.group(2).lower()])
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(page_age.strip()[:19], fmt).date()
        except ValueError:
            continue
    return None


def _parse_reported_date(value: str) -> date | None:
    """Parse the model-extracted "YYYY-MM" / "YYYY". A bare year is treated as its last day (most lenient)."""
    value = value.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}", value):
            return datetime.strptime(value, "%Y-%m").date()
        if re.fullmatch(r"\d{4}", value):
            return date(int(value), 12, 31)
    except ValueError:
        pass
    return None


def _months_ago(today: date, months: int) -> date:
    total = today.year * 12 + (today.month - 1) - months
    return date(total // 12, total % 12 + 1, 1)


def _searched_pages(content: list, today: date) -> dict[str, date | None]:
    """Normalized URL -> page date (from page_age) for every result web search actually returned."""
    pages: dict[str, date | None] = {}
    for block in content:
        # On error, content is a single error object rather than a list of results.
        if block.type == "web_search_tool_result" and isinstance(block.content, list):
            for result in block.content:
                pages[_normalize_url(result.url)] = _parse_page_age(result.page_age, today)
    return pages


async def research_interview_questions(job_description: str, company: str | None) -> ResearchResult:
    today = date.today()
    cutoff = _months_ago(today, MAX_REPORT_AGE_MONTHS)
    company_line = (
        f"Company: {company}" if company else "Company: not given - identify it from the job description."
    )
    # Date goes in the user message, not the system prompt, so the system prompt stays stable.
    messages = [{
        "role": "user",
        "content": (
            f"Today is {today.isoformat()}. Only report questions reported on or after {cutoff:%Y-%m} "
            f"(the last {MAX_REPORT_AGE_MONTHS} months).\n\n"
            f"{company_line}\n\nJob description:\n{job_description}"
        ),
    }]

    client = anthropic.AsyncAnthropic()
    seen_pages: dict[str, date | None] = {}

    try:
        for _ in range(MAX_CONTINUATIONS + 1):
            response = await client.beta.messages.create(
                model=RESEARCH_MODEL,
                max_tokens=16000,
                system=RESEARCH_SYSTEM_PROMPT,
                output_config={"effort": "medium"},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                tools=[
                    {
                        "type": "web_search_20260209",
                        "name": "web_search",
                        "max_uses": MAX_SEARCHES,
                    },
                    REPORT_TOOL,
                ],
                messages=messages,
            )
            seen_pages |= _searched_pages(response.content, today)

            if response.stop_reason == "pause_turn":
                # Server-side search loop hit its iteration limit; re-send to let it resume.
                messages = messages[:1] + [{"role": "assistant", "content": response.content}]
                continue
            break
    except anthropic.APIError as exc:
        logger.warning("Interview question research failed: %s", exc)
        return EMPTY_RESULT

    if response.stop_reason == "refusal":
        logger.warning("Interview question research was declined: %s", response.stop_details)
        return EMPTY_RESULT

    report = next(
        (block.input for block in response.content if block.type == "tool_use" and block.name == REPORT_TOOL_NAME),
        None,
    )
    if report is None:
        logger.warning("Research ended without reporting findings (stop_reason=%s)", response.stop_reason)
        return EMPTY_RESULT

    # Keep only questions whose URL was actually returned by search (so a hallucinated or mis-attributed
    # source never reaches the user) and that aren't older than the cutoff.
    dated: list[ReportedQuestion] = []
    undated: list[ReportedQuestion] = []
    for item in report["questions"]:
        source = source_for_url(item["url"])
        normalized = _normalize_url(item["url"])
        if not source or normalized not in seen_pages or not item["text"].strip():
            continue

        # A page last updated before the cutoff can't hold a recent report (even if the model says so);
        # a recently updated page (e.g. a Glassdoor aggregate) can still hold old reports, so the
        # report's own date is checked too.
        reported = _parse_reported_date(item["reported_date"])
        page_date = seen_pages[normalized]
        if (page_date and page_date < cutoff) or (reported and reported < cutoff):
            continue

        question: ReportedQuestion = {
            "text": item["text"].strip(),
            "source": source,
            "url": item["url"],
            "reported_date": item["reported_date"].strip() if reported else "",
        }
        (dated if reported else undated).append(question)

    # Within each group keep the model's order, which is by relevance to the job description.
    return {"company": report["company"], "role": report["role"], "questions": dated + undated}
