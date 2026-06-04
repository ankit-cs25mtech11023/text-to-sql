import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import streamlit as st

from config.settings import Settings
from core.pipeline import TextToSQLPipeline

EXAMPLE_QUESTIONS = [
    "What is the total tax collected by each state?",
    "Show the top 10 suppliers by taxable value",
    "Monthly trend of B2B invoice count?",
    "Which HSN codes have the highest IGST collection?",
    "How many export invoices were filed in Q1 2026?",
    "Average invoice value for 18% tax rate items?",
    "List suppliers who filed more than 100 invoices",
    "Compare CGST vs IGST collection across all months",
]

MODEL_OPTIONS: dict[str, tuple[str, str]] = {
    "llama-3.1-8b-instant (Groq)": ("groq", "llama-3.1-8b-instant"),
    "llama-3.3-70b-versatile (Groq)": ("groq", "llama-3.3-70b-versatile"),
    "qwen3-coder:free (OpenRouter)": ("openrouter", "qwen/qwen3-coder:free"),
    "qwen3-next-80b:free (OpenRouter)": ("openrouter", "qwen/qwen3-next-80b-a3b-instruct:free"),
}


@st.cache_resource
def get_available_providers() -> set[str]:
    s = Settings()
    available = set()
    if s.groq_api_key:
        available.add("groq")
    if s.openrouter_api_key:
        available.add("openrouter")
    return available


@st.cache_resource
def load_pipeline(provider: str, model: str) -> TextToSQLPipeline:
    settings = Settings(default_provider=provider, default_model=model)
    return TextToSQLPipeline(settings)


def _render_response(payload: dict, show_sql_first: bool) -> None:
    if not payload["success"]:
        st.error(f"Failed after {payload['attempts']} attempt(s): {payload['error']}")
        if payload["sql"]:
            with st.expander("Last generated SQL"):
                st.code(payload["sql"], language="sql")
        return

    if show_sql_first:
        tab_sql, tab_results = st.tabs(["SQL", "Results"])
    else:
        tab_results, tab_sql = st.tabs(["Results", "SQL"])

    with tab_results:
        df = payload["data"]
        if df is not None and not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Query returned no rows.")

    with tab_sql:
        st.code(payload["sql"], language="sql")

    st.caption(
        f"Execution: {payload['execution_time_ms']:.0f} ms • "
        f"Attempts: {payload['attempts']}"
    )


def _make_error_payload(error: str, show_sql_first: bool) -> dict:
    return {
        "success": False,
        "sql": "",
        "data": None,
        "error": error,
        "attempts": 0,
        "execution_time_ms": 0.0,
        "show_sql_first": show_sql_first,
    }


def main() -> None:
    st.set_page_config(
        page_title="GST Text-to-SQL Assistant",
        layout="wide",
    )
    st.title("GST Text-to-SQL Assistant")

    with st.sidebar:
        st.header("Settings")
        available = get_available_providers()
        usable = {
            label: (prov, mdl)
            for label, (prov, mdl) in MODEL_OPTIONS.items()
            if prov in available
        }
        if not usable:
            st.error("No API keys found. Add GROQ_API_KEY or OPENROUTER_API_KEY to .env")
            st.stop()
        selected_label = st.selectbox("Model", list(usable.keys()))
        provider, model = usable[selected_label]
        show_sql_first = st.toggle("Show SQL first", value=True)
        temperature = 0.0

        st.divider()
        st.subheader("Example Questions")
        for q in EXAMPLE_QUESTIONS:
            if st.button(q, use_container_width=True):
                st.session_state.pending_question = q

    if "messages" not in st.session_state:
        st.session_state.messages = []

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            if msg["role"] == "user":
                st.write(msg["content"])
            else:
                _render_response(msg["payload"], msg["payload"]["show_sql_first"])

    # ── Active query polling loop ─────────────────────────────────────────────
    qs = st.session_state.get("_qs")
    if qs and qs["running"]:
        with st.chat_message("assistant"):
            st.write("⏳ Generating SQL and executing...")
            if st.button("⏹ Stop", type="secondary", key="stop_query"):
                qs["running"] = False
                payload = _make_error_payload(
                    "Query cancelled by user.", qs["show_sql_first"]
                )
                st.session_state.messages.append({"role": "assistant", "payload": payload})
                del st.session_state["_qs"]
                st.rerun()

        if not qs["thread"].is_alive():
            result_or_exc = qs["result_box"][0]
            if isinstance(result_or_exc, Exception):
                payload = _make_error_payload(str(result_or_exc), qs["show_sql_first"])
            elif result_or_exc is None:
                payload = _make_error_payload("No result returned.", qs["show_sql_first"])
            else:
                r = result_or_exc
                payload = {
                    "success": r.success,
                    "sql": r.sql,
                    "data": r.data,
                    "error": r.error or "Unknown error",
                    "attempts": r.attempts,
                    "execution_time_ms": r.execution_time_ms,
                    "show_sql_first": qs["show_sql_first"],
                }
            st.session_state.messages.append({"role": "assistant", "payload": payload})
            del st.session_state["_qs"]
            st.rerun()
        else:
            time.sleep(0.5)
            st.rerun()
        return

    # ── Normal chat input ─────────────────────────────────────────────────────
    question: str | None = None
    if prompt := st.chat_input("Ask a question about GST data..."):
        question = prompt
        st.session_state.pop("pending_question", None)
    elif "pending_question" in st.session_state:
        question = st.session_state.pop("pending_question")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})

        pipeline = load_pipeline(provider, model)
        pipeline._settings.temperature = temperature

        result_box: list = [None]

        def _run(q: str = question) -> None:
            try:
                result_box[0] = pipeline.ask(q)
            except Exception as exc:
                result_box[0] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()

        st.session_state["_qs"] = {
            "running": True,
            "thread": thread,
            "result_box": result_box,
            "show_sql_first": show_sql_first,
        }
        st.rerun()


if __name__ == "__main__":
    main()
