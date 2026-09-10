# Interview Coach

An AI-powered interview screening platform that automates candidate evaluation from job descriptions. A FastAPI and LangGraph backend dynamically generates role-specific screening questions, conducts conversational interviews with voice and text input, and evaluates responses to produce a structured pass/fail assessment with actionable feedback. 


- **Prompt caching** — messages that get reused across multiple LLM calls within a run (like the job
  description and the compiled answers) are marked cacheable, so the model doesn't have to reprocess them
  from scratch each time.
- **Short-term memory** — each interview's progress is checkpointed as it goes, so an in-progress interview
  can resume across separate requests (and even a server restart) without losing state.
- **Long-term memory** — completed attempts are persisted per user and job description. When a user
  practices the same questions again, the feedback and decider agents are given the prior attempt so they
  can judge improvement rather than scoring in isolation. Past attempts are also browsable per job in the
  UI's practice history.

## Setup

Requires Python >=3.11, [uv](https://docs.astral.sh/uv/), Node.js, and Docker (for local Postgres).

```bash
# 1. Start Postgres
docker compose up -d

# 2. Install backend dependencies
uv sync


# 3. Run the API
uv run fastapi dev backend/main.py

# 4. Install and run the frontend (separate terminal)
cd frontend
npm install
npm run dev
```
