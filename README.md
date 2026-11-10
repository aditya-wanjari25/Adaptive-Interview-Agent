# Adaptive Interview Agent

Practice screening interviews for a real job. Paste a job description (and optionally the company), and the agent
asks you five questions out loud, then gives a pass/fail verdict and specific feedback.

- **Real questions** — searches the web for questions candidates recently reported being asked at that company
  (last 24 months), blends them with questions generated from the job description, and shows where each came from.
- **Voice or text** — questions are spoken via ElevenLabs; answer by speaking or typing.
- **Tracks improvement** — past attempts are saved per job, and practicing again is judged against your last attempt.

Built with FastAPI, LangGraph (Postgres-backed memory), Claude, and React.

## Setup

Requires Python >=3.11, [uv](https://docs.astral.sh/uv/), Node.js, and Docker.

Create a `.env` with `ANTHROPIC_API_KEY`, `ELEVENLABS_API_KEY`, `DATABASE_URL`, and `POSTGRES_USER` /
`POSTGRES_PASSWORD` / `POSTGRES_DB`.

```bash
docker compose up -d                  # Postgres
uv sync
uv run fastapi dev backend/main.py    # API on :8000

cd frontend && npm install && npm run dev   # UI on :5173
```
