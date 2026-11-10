from langchain_anthropic import ChatAnthropic
from langgraph.graph import StateGraph, START, END
from typing_extensions import TypedDict
from langgraph.types import interrupt, Command
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.base import BaseStore
from langchain_core.messages import HumanMessage, SystemMessage
from .job_description import JOB_DESCRIPTION
from dotenv import load_dotenv
from langchain_core.callbacks import get_usage_metadata_callback
from prompts.screening_agent_prompts import FEEDBACK_AGENT_PROMPT, DECIDER_AGENT_PROMPT
from .research import research_interview_questions, ResearchResult
import hashlib
import json
import time
import uuid

load_dotenv()


def user_namespace_hash(user_id: str) -> str:
    return hashlib.sha256(user_id.encode()).hexdigest()[:16]


def job_namespace_hash(job_description: str) -> str:
    return hashlib.sha256(job_description.encode()).hexdigest()[:16]


def memory_namespace(user_id: str, job_description: str) -> tuple[str, str]:
    """Namespace labels for the long-term store. Hashed because store namespace labels
    can't contain periods (or other special characters), which real user_ids like emails do.
    """
    return (user_namespace_hash(user_id), job_namespace_hash(job_description))


# Shared config for the feedback and decider agents.
# - effort "low": recommended starting point for classification / short content generation on Sonnet 5.5.
# - max_tokens: thinking counts toward it, so leave headroom beyond the short structured reply.
# - fallbacks "default": if Sonnet 5.5 declines a request, the API retries it server-side on a fallback model.
JUDGE_MODEL_KWARGS = dict(
    model="claude-sonnet-5-5",
    max_tokens=16000,
    effort="low",
    betas=["server-side-fallback-2026-07-01"],
    model_kwargs={"fallbacks": "default"},
)


# Bump the version when the shape or filtering of research results changes, to ignore stale entries.
RESEARCH_CACHE_NAMESPACE = ("research_cache_v2",)
RESEARCH_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60


def research_cache_key(company: str, job_description: str) -> str:
    raw = f"{company.strip().lower()}|{job_description}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]

'''
Screening Graph:
Start -> Research Questions -> Generate Questions -> Ask Questions -> Compile Feedback Input -> [Feedback Agent, Decider Agent] (parallel) -> End

Research Questions:
    - Web search (open web, first-hand reports preferred) for questions candidates report being asked at this company/role
    - Cached in the store for 7 days per company + job description

Generate Questions:
    - Generate 5 questions for the user to answer, preferring reported questions from research

Ask Questions (Interviewer Agent):
    - Ask the questions to the user one at a time via interrupt()
    - Save answers in state

Compile Feedback Input:
    - Build the question -> answer mapping once, shared by both downstream agents

Feedback Agent:
    - Runs in parallel with Decider Agent
    - Generates qualitative feedback on the candidate's answers

Decider Agent:
    - Runs in parallel with Feedback Agent
    - Returns a pass/fail decision

End:
    - Returns the pass/fail decision and the feedback
'''

class QuestionFormat(TypedDict):
    question1: str
    question2: str
    question3: str
    question4: str
    question5: str


class SourcedQuestion(TypedDict):
    text: str
    reported_index: int  # index into the reported questions list, or -1 if generated


class SourcedQuestionFormat(TypedDict):
    question1: SourcedQuestion
    question2: SourcedQuestion
    question3: SourcedQuestion
    question4: SourcedQuestion
    question5: SourcedQuestion

class FeedbackOutput(TypedDict):
    feedback: str

class DecisionOutput(TypedDict):
    result: bool


class ScreeningAgent(TypedDict):
    result: DecisionOutput          # the result of the screening
    questions: QuestionFormat       # the questions to ask the user
    job_description: str            # the job description
    responses: list
    feedback_input: dict
    feedback_output: FeedbackOutput
    user_id: str
    menu_choice: str
    previous_attempt: dict
    company: str                    # optional, user-provided; research identifies it if blank
    research: ResearchResult        # questions candidates reported online (via web search)
    question_sources: dict          # question key -> {"reported_date": "YYYY-MM"|"YYYY"|"", "source": site display name, e.g. "Glassdoor", or "generated", "url": str}


async def research_questions(state: ScreeningAgent, *, store: BaseStore) -> dict:
    """Find questions candidates report being asked for this company/role, with a 7-day cache"""
    company = (state.get("company") or "").strip()
    job_description = state["job_description"]
    key = research_cache_key(company, job_description)

    cached = await store.aget(RESEARCH_CACHE_NAMESPACE, key)
    if cached and time.time() - cached.value["timestamp"] < RESEARCH_CACHE_TTL_SECONDS:
        research = cached.value["research"]
    else:
        research = await research_interview_questions(job_description, company or None)
        # Don't cache empty results; they're often transient (search/API errors).
        if research["questions"]:
            await store.aput(RESEARCH_CACHE_NAMESPACE, key, {"research": research, "timestamp": time.time()})

    return {"research": research, "company": company or research["company"]}


def generate_questions(state: ScreeningAgent) -> dict:
    """Generate 5 questions, using as many relevant reported questions as possible and generating the rest"""
    model = ChatAnthropic(
        model="claude-haiku-4-5-20251001",
        temperature=0.0,
    )
    model = model.with_structured_output(SourcedQuestionFormat, method="json_schema")

    reported = state.get("research", {}).get("questions", [])
    if reported:
        reported_text = "\n".join(
            f"[{i}] {q['text']}" + (f" (reported {q['reported_date']})" if q.get("reported_date") else "")
            for i, q in enumerate(reported)
        )
        instructions = (
            "Below are questions candidates report being asked for this company/role. Use as many of them as "
            "are relevant to the job description and answerable verbally in a screening call, up to 5. Keep "
            "their meaning (light rewording for clarity is fine) and set reported_index to the number in "
            "brackets. When relevance is similar, prefer more recently reported questions. Generate the remaining "
            "questions from the job description with reported_index -1. "
            "Order the questions as a natural screening conversation.\n\n"
            f"Reported questions:\n{reported_text}"
        )
    else:
        instructions = "Generate all 5 questions from the job description, each with reported_index -1."

    response = model.invoke([
        SystemMessage(
            content=[{
                "type": "text",
                "text": "You are a helpful assistant that generates 5 questions for an initial screening interview.",
            }]
        ),
        HumanMessage(content=[
            {
                "type": "text",
                "text": f"Generate questions based on job description: {state['job_description']}",
                "cache_control": {"type": "ephemeral"}
            },
            {"type": "text", "text": instructions},
        ])
    ])

    questions = {}
    question_sources = {}
    used_indexes = set()
    for key, item in response.items():
        questions[key] = item["text"]
        idx = item["reported_index"]
        # Guard against out-of-range or reused indexes so a source is never mis-attributed.
        if 0 <= idx < len(reported) and idx not in used_indexes:
            used_indexes.add(idx)
            question_sources[key] = {
                "source": reported[idx]["source"],
                "url": reported[idx]["url"],
                "reported_date": reported[idx].get("reported_date", ""),
            }
        else:
            question_sources[key] = {"source": "generated", "url": "", "reported_date": ""}

    return {"questions": questions, "question_sources": question_sources}


def ask_questions(state: ScreeningAgent) -> dict:
    """Ask the questions to the user, one at a time, pausing for each answer"""
    questions = state["questions"]
    responses = state.get("responses", [])

    idx = len(responses)
    keys = list(questions.keys())
    if idx >= len(keys):
        return {"responses": responses}

    current_key = keys[idx]
    source = state.get("question_sources", {}).get(current_key, {"source": "generated", "url": ""})
    answer = interrupt({
        "question": questions[current_key],
        "question_key": current_key,
        "question_source": source["source"],
        "question_url": source["url"],
        "question_reported_date": source.get("reported_date", ""),
    })

    responses = responses + [answer]
    return {"responses": responses}


def should_continue_asking(state: ScreeningAgent) -> str:
    if len(state.get("responses", [])) < len(state["questions"]):
        return "ask_questions"
    return "compile_feedback_input"


async def compile_feedback_input(state: ScreeningAgent, *, store: BaseStore) -> dict:
    """Build the question -> answer mapping once, shared by both downstream agents.

    Also looks up the most recent prior attempt (if any) for this user + job description
    so the downstream agents can judge improvement rather than scoring in isolation.
    """
    questions = state["questions"]
    responses = state["responses"]
    feedback_input = {}
    for i, key in enumerate(questions):
        feedback_input[questions[key]] = responses[i]

    namespace = memory_namespace(state["user_id"], state["job_description"])
    items = await store.asearch(namespace)

    previous_attempt = None
    if items:
        previous_attempt = max(items, key=lambda item: item.value["timestamp"]).value

    return {"feedback_input": feedback_input, "previous_attempt": previous_attempt}


def _feedback_input_text(state: ScreeningAgent) -> str:
    text = json.dumps(state["feedback_input"], indent=2)

    previous_attempt = state.get("previous_attempt")
    if previous_attempt:
        previous_input = dict(zip(previous_attempt["questions"].values(), previous_attempt["responses"]))
        text += (
            "\n\nPrevious attempt at these same questions (for comparison):\n"
            f"{json.dumps(previous_input, indent=2)}\n\n"
            "Previous feedback given:\n"
            f"{previous_attempt['feedback_output']}"
        )

    return text


def decider_agent(state: ScreeningAgent) -> dict:
    """Decides if the candidate cleared the interview"""
    job_description = state["job_description"]

    model = ChatAnthropic(**JUDGE_MODEL_KWARGS)
    model = model.with_structured_output(DecisionOutput, method="json_schema")

    response = model.invoke([
        SystemMessage(content=[{
            "type": "text",
            "text": f"{DECIDER_AGENT_PROMPT}: {job_description}"
        }]),
        HumanMessage(content=[{
            "type": "text",
            "text": _feedback_input_text(state),
            "cache_control": {"type": "ephemeral"}
        }])
    ])

    return {"result": response["result"]}


def feedback_agent(state: ScreeningAgent) -> dict:
    """Generate feedback for the user's answers"""
    model = ChatAnthropic(**JUDGE_MODEL_KWARGS)
    model = model.with_structured_output(FeedbackOutput, method="json_schema")

    response = model.invoke([
        SystemMessage(content=[{
            "type": "text",
            "text": FEEDBACK_AGENT_PROMPT
        }]),
        HumanMessage(content=[{
            "type": "text",
            "text": _feedback_input_text(state),
            "cache_control": {"type": "ephemeral"}
        }])
    ])

    return {"feedback_output": response["feedback"]}


async def present_results(state: ScreeningAgent, *, store: BaseStore) -> dict:
    """Persist the completed attempt to long-term memory, keyed by user + job description"""
    job_description = state["job_description"]
    namespace = memory_namespace(state["user_id"], job_description)

    attempt = {
        "job_description": job_description,
        "questions": state["questions"],
        "question_sources": state.get("question_sources", {}),
        "company": state.get("company", ""),
        "responses": state["responses"],
        "feedback_output": state["feedback_output"],
        "result": state["result"],
        "timestamp": time.time(),
    }

    await store.aput(namespace, str(uuid.uuid4()), attempt)

    choice = interrupt({
        "menu": ["practice_again", "exit"],
        "result": state["result"],
        "feedback_output": state["feedback_output"],
    })

    if choice == "practice_again":
        return {"menu_choice": choice, "responses": []}

    return {"menu_choice": choice}


def route_after_menu(state: ScreeningAgent) -> str:
    if state.get("menu_choice") == "practice_again":
        return "ask_questions"
    return END


# Graph Definition
graph = StateGraph(ScreeningAgent)

# add nodes
graph.add_node("research_questions", research_questions)
graph.add_node("generate_questions", generate_questions)
graph.add_node("ask_questions", ask_questions)
graph.add_node("compile_feedback_input", compile_feedback_input)
graph.add_node("feedback_agent", feedback_agent)
graph.add_node("decider_agent", decider_agent)
graph.add_node("present_results", present_results)

# add edges
graph.add_edge(START, "research_questions")
graph.add_edge("research_questions", "generate_questions")
graph.add_edge("generate_questions", "ask_questions")
graph.add_conditional_edges("ask_questions", should_continue_asking)

graph.add_edge("compile_feedback_input", "feedback_agent")
graph.add_edge("compile_feedback_input", "decider_agent")

graph.add_edge("feedback_agent", "present_results")
graph.add_edge("decider_agent", "present_results")
graph.add_conditional_edges("present_results", route_after_menu)

if __name__ == "__main__":
    from langgraph.store.memory import InMemoryStore

    compiled_graph = graph.compile(checkpointer=MemorySaver(), store=InMemoryStore())
    config = {"configurable": {"thread_id": "session-1"}}

    with get_usage_metadata_callback() as cb:
        result = compiled_graph.invoke({"job_description": JOB_DESCRIPTION}, config=config)

        while "__interrupt__" in result:
            payload = result["__interrupt__"][0].value
            answer = input(payload["question"])
            result = compiled_graph.invoke(Command(resume=answer), config=config)

        print(result["result"])
        print(result["feedback_output"])

    print()
    for model_name, usage in cb.usage_metadata.items():
        print(f"{model_name}")
        for key, value in usage.items():
            print(f"  {key:<28}: {value}")