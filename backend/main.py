from __future__ import annotations

import secrets
import string
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from sarathi.rag import (
    BGEEmbedder,
    CitizenProfile,
    GeminiExplainer,
    HybridRetriever,
    SchemeStore,
    load_json_schemes,
)


app = FastAPI(title="Sarathi Backend", version="1.0.0")
retriever = HybridRetriever()
explainer = GeminiExplainer()


class ProfilePayload(BaseModel):
    name: str = ""
    age: int = 0
    gender: str = "All"
    state: str = "All"
    category: str = "General"
    income: int = 9999999
    need: str = ""


class CreateUserRequest(BaseModel):
    profile: ProfilePayload


class LoginRequest(BaseModel):
    username: str
    password: str


class RecommendRequest(BaseModel):
    profile: ProfilePayload
    limit: int = Field(default=8, ge=1, le=25)


class ExplainRequest(BaseModel):
    profile: ProfilePayload
    schemes: list[dict[str, Any]] = Field(default_factory=list)
    question: str = ""


def make_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def make_credentials(profile: dict[str, Any]) -> dict[str, str]:
    name = str(profile.get("name") or "user")
    prefix = "".join(ch for ch in name.lower() if ch.isalnum())[:8] or "citizen"
    return {"username": f"{prefix}{secrets.randbelow(9000) + 1000}", "password": make_password()}


def profile_dict(profile: ProfilePayload) -> dict[str, Any]:
    return profile.dict()


def citizen_profile(profile: ProfilePayload) -> CitizenProfile:
    return CitizenProfile.from_session(profile_dict(profile))


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/db/count")
def db_count() -> dict[str, int]:
    try:
        return {"count": SchemeStore().count_schemes()}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database not reachable: {exc}") from exc


@app.post("/db/seed")
def seed_database() -> dict[str, Any]:
    try:
        store = SchemeStore()
        schemes = load_json_schemes("schemes.json")
        try:
            store.upsert_many(schemes, BGEEmbedder())
            embedded = True
        except Exception:
            store.upsert_many(schemes, embedder=None)
            embedded = False
        return {"ok": True, "count": store.count_schemes(), "embedded": embedded}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Could not seed vector database: {exc}") from exc


@app.post("/auth/create")
def create_user(request: CreateUserRequest) -> dict[str, Any]:
    store = SchemeStore()
    profile = profile_dict(request.profile)
    for _ in range(20):
        credentials = make_credentials(profile)
        try:
            if store.user_exists(credentials["username"]):
                continue
            store.create_user(credentials["username"], credentials["password"], profile)
            return {"credentials": credentials, "profile": profile}
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Could not save user in database: {exc}") from exc
    raise HTTPException(status_code=409, detail="Could not generate a unique username. Please try again.")


@app.post("/auth/login")
def login(request: LoginRequest) -> dict[str, Any]:
    try:
        profile = SchemeStore().authenticate_user(request.username.strip(), request.password)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not check user database: {exc}") from exc
    if not profile:
        raise HTTPException(status_code=401, detail="User does not exist or the password is incorrect.")
    return {"profile": profile, "credentials": {"username": request.username.strip(), "password": request.password}}


@app.post("/recommend")
def recommend(request: RecommendRequest) -> dict[str, Any]:
    profile = citizen_profile(request.profile)
    matches, mode = retriever.search(profile, limit=request.limit)
    return {"matches": matches, "retrieval_mode": mode}


@app.post("/explain")
def explain(request: ExplainRequest) -> dict[str, str]:
    payload = profile_dict(request.profile)
    if request.question:
        payload["need"] = request.question
    answer = explainer.explain(CitizenProfile.from_session(payload), request.schemes)
    return {"answer": answer}
