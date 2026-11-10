"""Finds interview questions candidates have reported for a company/role.

Uses Claude's server-side web search across the open web, steered toward first-hand reports
(Glassdoor, Blind, LeetCode Discuss, interview-experience write-ups). Nothing is scraped directly: the
search tool only sees what sites expose publicly to search, which avoids login walls, anti-bot measures
and terms-of-service problems.

Reddit never appears in results: it blocks Anthropic's crawler (naming `reddit.com` in
`allowed_domains` is a 400). Adding Reddit would need its official API as a separate source.

Research is best-effort. Any failure (API error, refusal, nothing found) returns no questions, and
question generation falls back to working from the job description alone.
"""

import logging
from typing import TypedDict
from urllib.parse import urlparse

import anthropic

logger = logging.getLogger(__name__)

RESEARCH_MODEL = "claude-opus-5-5"
MAX_SEARCHES = 8
MAX_CONTINUATIONS = 5

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
                    "required": ["text", "url"],
                    "properties": {
                        "text": {"type": "string", "description": "The interview question."},
                        "url": {"type": "string", "description": "URL of the search result reporting it."},
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


def _searched_urls(content: list) -> set[str]:
    """Normalized URLs that actually came back from web search in this response."""
    urls = set()
    for block in content:
        # On error, content is a single error object rather than a list of results.
        if block.type == "web_search_tool_result" and isinstance(block.content, list):
            urls.update(_normalize_url(result.url) for result in block.content)
    return urls


async def research_interview_questions(job_description: str, company: str | None) -> ResearchResult:
    company_line = (
        f"Company: {company}" if company else "Company: not given - identify it from the job description."
    )
    messages = [{
        "role": "user",
        "content": f"{company_line}\n\nJob description:\n{job_description}",
    }]

    client = anthropic.AsyncAnthropic()
    seen_urls: set[str] = set()

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
            seen_urls |= _searched_urls(response.content)

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

    # Keep only questions whose URL was actually returned by search,
    # so a hallucinated or mis-attributed source never reaches the user.
    questions: list[ReportedQuestion] = []
    for item in report["questions"]:
        source = source_for_url(item["url"])
        if source and _normalize_url(item["url"]) in seen_urls and item["text"].strip():
            questions.append({"text": item["text"].strip(), "source": source, "url": item["url"]})

    return {"company": report["company"], "role": report["role"], "questions": questions}
