from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import auth, children, contributions, families, feed, goals, invites, vault

app = FastAPI(title="FutureRoots API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.web_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(families.router)
app.include_router(children.router)
app.include_router(invites.router)
app.include_router(vault.router)
app.include_router(feed.router)
app.include_router(goals.router)
app.include_router(contributions.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
