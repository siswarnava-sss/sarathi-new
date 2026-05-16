from __future__ import annotations

import os
import time
from typing import Any

import requests
import streamlit as st
import streamlit.components.v1 as components


API_BASE_URL = os.getenv("SARATHI_API_URL", "http://localhost:8000").rstrip("/")

QUESTIONS = [
    ("name", "What is your full name?"),
    ("age", "What is your age?"),
    ("gender", "What is your gender? (Male/Female/Other)"),
    ("state", "Which state do you live in?"),
    ("category", "What is your category? (General/OBC/SC/ST/Minority)"),
    ("income", "What is your annual family income? (Numbers only)"),
    ("need", "What kind of help are you looking for? (education, health, farming, housing, jobs, business, etc.)"),
]


def initialize_session() -> None:
    defaults = {
        "stage": "landing",
        "logged_in": False,
        "profile_step": 0,
        "user_info": {},
        "credentials": None,
        "ai_messages": [],
        "matches": None,
        "retrieval_mode": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def reset_all() -> None:
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    initialize_session()


def api_request(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = requests.request(method, f"{API_BASE_URL}{path}", timeout=90, **kwargs)
        response.raise_for_status()
        return response.json()
    except requests.HTTPError as exc:
        try:
            detail = response.json().get("detail", str(exc))
        except ValueError:
            detail = str(exc)
        raise RuntimeError(detail) from exc
    except requests.RequestException as exc:
        raise RuntimeError(f"Could not reach Sarathi backend at {API_BASE_URL}: {exc}") from exc


def clipboard_button(text: str) -> None:
    escaped = text.replace("\\", "\\\\").replace("`", "\\`")
    components.html(
        f"""
        <button
          style="width:100%;padding:0.7rem;border:1px solid #d1d5db;border-radius:0.4rem;background:#ffffff;cursor:pointer;"
          onclick="navigator.clipboard.writeText(`{escaped}`); this.innerText='Copied';">
          Copy to clipboard
        </button>
        """,
        height=55,
    )


def logout() -> None:
    reset_all()
    st.rerun()


def render_sidebar() -> None:
    with st.sidebar:
        st.title("Sarathi")
        st.caption(f"Backend: {API_BASE_URL}")
        if st.session_state.logged_in:
            st.success(f"Signed in as {st.session_state.credentials['username']}")
            if st.button("Logout", use_container_width=True):
                logout()

            st.divider()
            st.caption("Data operations")
            if st.button("Seed pgvector from schemes.json", use_container_width=True):
                try:
                    result = api_request("POST", "/db/seed")
                    mode = "with embeddings" if result.get("embedded") else "without embeddings"
                    st.success(f"Database seeded {mode}. Current scheme count: {result['count']}.")
                except RuntimeError as exc:
                    st.warning(str(exc))

            try:
                result = api_request("GET", "/db/count")
                st.info(f"Vector DB schemes: {result['count']}")
            except RuntimeError as exc:
                st.warning(f"Vector DB not reachable: {exc}")
        else:
            st.caption("Create a profile or log in with saved credentials.")


def render_landing() -> None:
    st.title("Semicolon-Sarathi")
    st.caption("Personalized government scheme discovery with hybrid retrieval")

    login_col, create_col = st.columns(2)
    with login_col:
        st.subheader("Login")
        st.write("Use the credentials created during profile setup.")
        if st.button("Login with credentials", use_container_width=True):
            st.session_state.stage = "login"
            st.rerun()

    with create_col:
        st.subheader("Create profile")
        st.write("Answer one question at a time and get temporary credentials.")
        if st.button("Create new profile", type="primary", use_container_width=True):
            st.session_state.stage = "create_profile"
            st.rerun()


def render_login() -> None:
    st.title("Login")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", type="primary")

    if submitted:
        try:
            result = api_request("POST", "/auth/login", json={"username": username.strip(), "password": password})
        except RuntimeError as exc:
            st.error(str(exc))
            return
        st.session_state.credentials = result["credentials"]
        st.session_state.user_info = result["profile"]
        st.session_state.matches = None
        st.session_state.ai_messages = []
        st.session_state.logged_in = True
        st.session_state.stage = "dashboard"
        st.rerun()


def render_profile_wizard() -> None:
    step = st.session_state.profile_step
    key, question = QUESTIONS[step]

    st.title("Create Profile")
    st.progress(step / len(QUESTIONS), text=f"Step {step + 1} of {len(QUESTIONS)}")
    st.subheader(question)

    with st.form(f"profile_step_{step}"):
        answer = st.text_input("Your answer", key=f"answer_{key}")
        submitted = st.form_submit_button("Next", type="primary")

    if submitted:
        if not answer.strip():
            st.warning("Please enter a value to continue.")
            return
        st.session_state.user_info[key] = answer.strip()
        st.session_state.profile_step += 1

        if st.session_state.profile_step >= len(QUESTIONS):
            try:
                result = api_request("POST", "/auth/create", json={"profile": st.session_state.user_info})
            except RuntimeError as exc:
                st.error(str(exc))
                st.session_state.profile_step -= 1
                return
            st.session_state.credentials = result["credentials"]
            st.session_state.user_info = result["profile"]
            st.session_state.stage = "profile_created"
        st.rerun()


def render_profile_created() -> None:
    st.title("Profile Created")
    credentials = st.session_state.credentials
    credential_text = f"Username: {credentials['username']}\nPassword: {credentials['password']}"

    st.success("Your profile is saved. Use these credentials to log in later.")
    st.code(credential_text)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Go to dashboard", type="primary", use_container_width=True):
            st.session_state.logged_in = True
            st.session_state.stage = "dashboard"
            st.rerun()
    with col2:
        clipboard_button(credential_text)


def get_dashboard_matches() -> tuple[list[dict[str, Any]], str]:
    if st.session_state.matches is None:
        with st.status("Finding eligible schemes...", expanded=True) as status:
            time.sleep(0.2)
            result = api_request("POST", "/recommend", json={"profile": st.session_state.user_info, "limit": 8})
            status.write(f"Retriever: {result['retrieval_mode']}")
            status.update(label="Eligible schemes loaded", state="complete", expanded=False)
        st.session_state.matches = result["matches"]
        st.session_state.retrieval_mode = result["retrieval_mode"]
    return st.session_state.matches, st.session_state.retrieval_mode


def render_scheme_card(scheme: dict[str, Any]) -> None:
    with st.container(border=True):
        st.markdown(f"### {scheme['name']}")
        st.write(scheme["description"])
        col1, col2 = st.columns(2)
        col1.info(f"State: {scheme['state']}")
        income_val = int(scheme["income_limit_inr"])
        display_income = "No income limit" if income_val >= 9999999 else f"INR {income_val:,}"
        col2.success(f"Income cap: {display_income}")
        categories = scheme.get("category", [])
        if isinstance(categories, str):
            categories = [categories]
        st.caption(
            f"Eligibility: age {scheme['age_min']}-{scheme['age_max']} | "
            f"{scheme['gender']} | {', '.join(categories)}"
        )
        if scheme.get("apply_url") and scheme["apply_url"] != "#":
            st.link_button("Apply on official portal", scheme["apply_url"], use_container_width=True)


def render_ai_chat(matches: list[dict[str, Any]]) -> None:
    st.subheader("AI Chat")
    if matches:
        st.caption("Ask follow-up questions. Answers are grounded in the eligible schemes shown on this dashboard.")
    else:
        st.caption("No grounded scheme rows matched yet. Answers will provide general directions to verify on official portals.")

    if not st.session_state.ai_messages:
        intro = "Ask me about benefits, eligibility, documents, or which option may fit you best."
        if not matches:
            intro = "Ask me for general scheme directions to verify on official portals."
        st.session_state.ai_messages = [{"role": "assistant", "content": intro}]

    for message in st.session_state.ai_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask about your eligible schemes...")
    if prompt:
        st.session_state.ai_messages.append({"role": "user", "content": prompt})
        result = api_request(
            "POST",
            "/explain",
            json={"profile": st.session_state.user_info, "schemes": matches, "question": prompt},
        )
        st.session_state.ai_messages.append({"role": "assistant", "content": result["answer"]})
        st.rerun()


def render_dashboard() -> None:
    if not st.session_state.logged_in:
        st.session_state.stage = "landing"
        st.rerun()

    st.title("Dashboard")
    profile = st.session_state.user_info
    income = int(float(str(profile.get("income", 0)).replace(",", "") or 0))
    st.caption(
        f"{profile.get('name', 'Citizen')} | {profile.get('age')} years | "
        f"{profile.get('state')} | {profile.get('category')} | income INR {income:,}"
    )

    matches, retrieval_mode = get_dashboard_matches()
    st.info(f"Retrieval mode: {retrieval_mode}")

    tab_schemes, tab_chat = st.tabs(["Eligible schemes", "AI chat"])
    with tab_schemes:
        if matches:
            for scheme in matches:
                render_scheme_card(scheme)
        else:
            st.warning("No eligible schemes found for this profile yet.")
    with tab_chat:
        render_ai_chat(matches)


st.set_page_config(page_title="Semicolon-Sarathi", page_icon="IN", layout="centered")
initialize_session()
render_sidebar()

if st.session_state.stage == "landing":
    render_landing()
elif st.session_state.stage == "login":
    render_login()
elif st.session_state.stage == "create_profile":
    render_profile_wizard()
elif st.session_state.stage == "profile_created":
    render_profile_created()
elif st.session_state.stage == "dashboard":
    render_dashboard()
