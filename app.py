import secrets
import string
import time

import streamlit as st
import streamlit.components.v1 as components

from sarathi.rag import (
    BGEEmbedder,
    CitizenProfile,
    GeminiExplainer,
    HybridRetriever,
    SchemeStore,
    load_json_schemes,
)


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


def make_password(length: int = 10) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def create_credentials() -> dict[str, str]:
    name = st.session_state.user_info.get("name", "user")
    prefix = "".join(ch for ch in name.lower() if ch.isalnum())[:8] or "citizen"
    return {"username": f"{prefix}{secrets.randbelow(9000) + 1000}", "password": make_password()}


def logout() -> None:
    reset_all()
    st.rerun()


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


@st.cache_resource(show_spinner=False)
def get_retriever() -> HybridRetriever:
    return HybridRetriever()


@st.cache_resource(show_spinner=False)
def get_explainer() -> GeminiExplainer:
    return GeminiExplainer()


def seed_vector_database() -> tuple[bool, str]:
    store = SchemeStore()
    if not store.enabled:
        return False, "DATABASE_URL is not configured, so the app is using schemes.json fallback data."
    try:
        schemes = load_json_schemes("schemes.json")
        store.upsert_many(schemes, BGEEmbedder())
        count = store.count_schemes()
        return True, f"Vector database seeded. Current scheme count: {count}."
    except Exception as exc:
        return False, f"Could not seed vector database: {exc}"


def render_sidebar() -> None:
    with st.sidebar:
        st.title("Sarathi")
        if st.session_state.logged_in:
            st.success(f"Signed in as {st.session_state.credentials['username']}")
            if st.button("Logout", use_container_width=True):
                logout()

            st.divider()
            st.caption("Data operations")
            if st.button("Seed pgvector from schemes.json", use_container_width=True):
                ok, message = seed_vector_database()
                if ok:
                    st.success(message)
                else:
                    st.warning(message)

            store = SchemeStore()
            if store.enabled:
                try:
                    st.info(f"Vector DB schemes: {store.count_schemes()}")
                except Exception as exc:
                    st.warning(f"Vector DB not reachable: {exc}")
            else:
                st.info("Vector DB not configured. Using local JSON fallback.")
        else:
            st.caption("Session data is temporary and is cleared when this browser session ends.")


def render_landing() -> None:
    st.title("Semicolon-Sarathi")
    st.caption("Personalized government scheme discovery with hybrid retrieval")

    login_col, create_col = st.columns(2)
    with login_col:
        st.subheader("Login")
        st.write("Use the temporary credentials created during profile setup.")
        if st.button("Login with temporary credentials", use_container_width=True):
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
    credentials = st.session_state.credentials
    if not credentials:
        st.warning("No temporary profile exists in this session yet. Create a profile first.")
        if st.button("Create profile", type="primary"):
            st.session_state.stage = "create_profile"
            st.rerun()
        return

    with st.form("login_form"):
        username = st.text_input("Temporary username")
        password = st.text_input("Temporary password", type="password")
        submitted = st.form_submit_button("Login", type="primary")

    if submitted:
        if username == credentials["username"] and password == credentials["password"]:
            st.session_state.logged_in = True
            st.session_state.stage = "dashboard"
            st.rerun()
        else:
            st.error("Invalid temporary username or password.")


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
            st.session_state.credentials = create_credentials()
            st.session_state.stage = "profile_created"
        st.rerun()


def render_profile_created() -> None:
    st.title("Profile Created")
    credentials = st.session_state.credentials
    credential_text = f"Username: {credentials['username']}\nPassword: {credentials['password']}"

    st.success("Your temporary profile is ready. These credentials live only in this browser session.")
    st.code(credential_text)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Go to dashboard", type="primary", use_container_width=True):
            st.session_state.logged_in = True
            st.session_state.stage = "dashboard"
            st.rerun()
    with col2:
        clipboard_button(credential_text)


def get_dashboard_matches() -> tuple[list[dict], str]:
    if st.session_state.matches is None:
        profile = CitizenProfile.from_session(st.session_state.user_info)
        with st.status("Finding eligible schemes...", expanded=True) as status:
            time.sleep(0.2)
            matches, retrieval_mode = get_retriever().search(profile)
            status.write(f"Retriever: {retrieval_mode}")
            status.update(label="Eligible schemes loaded", state="complete", expanded=False)
        st.session_state.matches = matches
        st.session_state.retrieval_mode = retrieval_mode
    return st.session_state.matches, st.session_state.retrieval_mode


def render_scheme_card(scheme: dict) -> None:
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


def render_ai_chat(matches: list[dict]) -> None:
    st.subheader("AI Chat")
    st.caption("Ask follow-up questions. Answers are grounded in the eligible schemes shown on this dashboard.")

    if not st.session_state.ai_messages:
        st.session_state.ai_messages = [
            {"role": "assistant", "content": "Ask me about benefits, eligibility, documents, or which option may fit you best."}
        ]

    for message in st.session_state.ai_messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    prompt = st.chat_input("Ask about your eligible schemes...")
    if prompt:
        st.session_state.ai_messages.append({"role": "user", "content": prompt})
        profile_data = dict(st.session_state.user_info)
        profile_data["need"] = prompt
        profile = CitizenProfile.from_session(profile_data)
        answer = get_explainer().explain(profile, matches)
        st.session_state.ai_messages.append({"role": "assistant", "content": answer})
        st.rerun()


def render_dashboard() -> None:
    if not st.session_state.logged_in:
        st.session_state.stage = "landing"
        st.rerun()

    st.title("Dashboard")
    profile = CitizenProfile.from_session(st.session_state.user_info)
    st.caption(
        f"{st.session_state.user_info.get('name', 'Citizen')} | {profile.age} years | "
        f"{profile.state} | {profile.category} | income INR {profile.income:,}"
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
