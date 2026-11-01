"""Step 7 (upgraded): the API. Run from the project root:  uvicorn backend.main:app --reload
Docs/test page: http://127.0.0.1:8000/docs"""
import asyncio, os, time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from .schema import ValidationError
from .service import Copilot

ROOT = os.path.join(os.path.dirname(__file__), "..")
copilot = Copilot()


@asynccontextmanager
async def lifespan(app):
    async def janitor():                       # delete expired consent every minute
        while True:
            await asyncio.sleep(60)
            copilot.store.purge_expired()
    task = asyncio.create_task(janitor())
    yield
    task.cancel()


app = FastAPI(title="LendWise - Borrower Lending Copilot", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.environ.get("CORS_ORIGINS", "*").split(","),
                   allow_methods=["*"], allow_headers=["*"])

_hits = defaultdict(deque)


def _limit(request: Request, per_minute=10):
    """Tiny per-IP limiter for the endpoints that cost money (LLM)."""
    ip, now = request.client.host if request.client else "?", time.time()
    q = _hits[ip]
    while q and q[0] < now - 60:
        q.popleft()
    if len(q) >= per_minute:
        raise HTTPException(429, "Too many requests, try again in a minute")
    q.append(now)


def run(fn, *args):
    try:
        return fn(*args)
    except ValidationError as e:
        raise HTTPException(422, str(e))
    except KeyError:
        raise HTTPException(404, "No active consent for this session (it may have expired or been deleted)")
    except PermissionError as e:
        raise HTTPException(403, str(e))


@app.get("/health")
def health():
    return {"ok": True}

@app.get("/api/assumptions")
def assumptions():
    return copilot.assumptions()

@app.get("/lenders")
def lenders_reference():
    return copilot.lenders()

@app.post("/consent")                          # the browser sends ONLY the 15 summary numbers
def consent(body: dict = Body(...)):
    return run(copilot.consent, body)

@app.post("/consent/extend")
def consent_extend(body: dict = Body(...)):
    return run(copilot.extend, body)

@app.post("/affordability")
def afford(body: dict = Body(...)):
    return run(copilot.affordability, body)

@app.post("/compare")
def compare(body: dict = Body(...)):
    return run(copilot.compare, body)

@app.post("/stress")
def stress(body: dict = Body(...)):
    return run(copilot.stress, body)

@app.post("/plan")
def plan(body: dict = Body(...)):
    return run(copilot.plan, body)

@app.post("/schedule")
def schedule(body: dict = Body(...)):
    return run(copilot.schedule, body)

@app.post("/extract-offer")
def extract_offer(request: Request, body: dict = Body(...)):
    _limit(request)
    return run(copilot.extract_offer, body)

@app.get("/ledger/{session}")
def ledger(session: str):
    return run(copilot.ledger, session)

@app.delete("/me/{session}")
def delete_me(session: str):
    return run(copilot.delete, session)

app.mount("/data", StaticFiles(directory=os.path.join(ROOT, "data"), check_dir=False), name="data")
app.mount("/static", StaticFiles(directory=os.path.join(ROOT, "frontend"), check_dir=False), name="static")

@app.get("/")
def home():
    return FileResponse(os.path.join(ROOT, "frontend", "index.html"))
