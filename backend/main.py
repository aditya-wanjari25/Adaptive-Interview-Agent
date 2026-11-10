import os
import uuid
from contextlib import asynccontextmanager
import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from langgraph.types import Command
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.store.postgres.aio import AsyncPostgresStore
from psycopg_pool import AsyncConnectionPool
from typing import Optional
from agents.screening_agent import graph, user_namespace_hash

DATABASE_URL = os.environ["DATABASE_URL"]
ELEVENLABS_API_KEY = os.environ["ELEVENLABS_API_KEY"]
ELEVENLABS_VOICE_ID = os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncConnectionPool(
        conninfo=DATABASE_URL,
        max_size=20,
        kwargs={"autocommit": True, "prepare_threshold": 0},
    ) as pool:
        checkpointer = AsyncPostgresSaver(pool) #short term memory
        postgres_store = AsyncPostgresStore(pool) #long term memory
        await checkpointer.setup() 
        await postgres_store.setup()
        app.state.compiled_graph = graph.compile(checkpointer=checkpointer, store=postgres_store)
        app.state.store = postgres_store
        yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class StartInterviewRequest(BaseModel):
    job_description: str
    user_id: str
    company: Optional[str] = None


class SpeakRequest(BaseModel):
    text: str


class StartInterviewResponse(BaseModel):
    session_id: str
    question: str
    question_key: str
    question_source: str = "generated"  # site display name (e.g. "Glassdoor") or "generated"
    question_url: str = ""
    question_reported_date: str = ""  # "YYYY-MM" / "YYYY" when known
    company: str = ""

class AnswerRequest(BaseModel):
    session_id: str
    answer: str

class AnswerResponse(BaseModel):
    status: str  # "in_progress", "awaiting_menu_choice", or "completed"
    question: Optional[str] = None
    question_key: Optional[str] = None
    question_source: Optional[str] = None
    question_url: Optional[str] = None
    question_reported_date: Optional[str] = None
    menu: Optional[list[str]] = None
    result: Optional[bool] = None
    feedback_output: Optional[str] = None


class JobSummary(BaseModel):
    jd_hash: str
    job_description: str
    attempt_count: int
    last_attempt_at: float
    last_result: Optional[bool] = None
    company: str = ""


class Attempt(BaseModel):
    job_description: str
    questions: dict
    question_sources: dict = {}  # absent on attempts saved before research existed
    company: str = ""
    responses: list
    feedback_output: str
    result: bool
    timestamp: float

@app.get("/")
def root():
    return {"hello": "this is root!"}


@app.get("/users/{user_id}/jobs", response_model=list[JobSummary])
async def list_jobs(user_id: str, request: Request):
    store = request.app.state.store
    user_hash = user_namespace_hash(user_id)
    namespaces = await store.alist_namespaces(prefix=(user_hash,))

    jobs = []
    for namespace in namespaces:
        items = await store.asearch(namespace)
        if not items:
            continue
        latest = max(items, key=lambda item: item.value["timestamp"])
        jobs.append(
            JobSummary(
                jd_hash=namespace[1],
                job_description=latest.value["job_description"],
                attempt_count=len(items),
                last_attempt_at=latest.value["timestamp"],
                last_result=latest.value.get("result"),
                company=latest.value.get("company", ""),
            )
        )

    jobs.sort(key=lambda job: job.last_attempt_at, reverse=True)
    return jobs


@app.get("/users/{user_id}/jobs/{jd_hash}/attempts", response_model=list[Attempt])
async def list_attempts(user_id: str, jd_hash: str, request: Request):
    store = request.app.state.store
    user_hash = user_namespace_hash(user_id)
    items = await store.asearch((user_hash, jd_hash))

    attempts = [Attempt(**item.value) for item in items]
    attempts.sort(key=lambda attempt: attempt.timestamp, reverse=True)
    return attempts


@app.post("/interview/speak")
async def speak(body: SpeakRequest):
    """Proxies text-to-speech through ElevenLabs so the API key never reaches the browser."""
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}",
            headers={
                "xi-api-key": ELEVENLABS_API_KEY,
                "Content-Type": "application/json",
            },
            json={
                "text": body.text,
                "model_id": "eleven_multilingual_v2",
            },
            timeout=60.0,
        )

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=response.text)

    return StreamingResponse(iter([response.content]), media_type="audio/mpeg")

@app.post("/interview/start", response_model=StartInterviewResponse)
async def start_interview(request: Request, body: StartInterviewRequest):
    session_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    result = await request.app.state.compiled_graph.ainvoke(
        {
            "job_description": body.job_description,
            "user_id": body.user_id,
            "company": (body.company or "").strip(),
        },
        config=config,
    )

    if "__interrupt__" not in result:
        raise HTTPException(status_code=500, detail="Graph did not pause as expected")

    payload = result["__interrupt__"][0].value

    return StartInterviewResponse(
        session_id=session_id,
        question=payload["question"],
        question_key=payload["question_key"],
        question_source=payload.get("question_source", "generated"),
        question_url=payload.get("question_url", ""),
        question_reported_date=payload.get("question_reported_date", ""),
        company=result.get("company", ""),
    )




@app.post("/interview/answer", response_model=AnswerResponse)
async def submit_answer(request: Request, body: AnswerRequest):
    config = {"configurable": {"thread_id": body.session_id}}

    state = await request.app.state.compiled_graph.aget_state(config)
    if not state.values:
        raise HTTPException(status_code=404, detail="Session not found or already completed")

    try:
        result = await request.app.state.compiled_graph.ainvoke(Command(resume=body.answer), config=config)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}") from exc

    if "__interrupt__" in result:
        payload = result["__interrupt__"][0].value

        if "menu" in payload:
            return AnswerResponse(
                status="awaiting_menu_choice",
                menu=payload["menu"],
                result=payload.get("result"),
                feedback_output=payload.get("feedback_output"),
            )

        return AnswerResponse(
            status="in_progress",
            question=payload["question"],
            question_key=payload["question_key"],
            question_source=payload.get("question_source", "generated"),
            question_url=payload.get("question_url", ""),
            question_reported_date=payload.get("question_reported_date", ""),
        )

    return AnswerResponse(
        status="completed",
        result=result.get("result"),
        feedback_output=result.get("feedback_output"),
    )