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
    "qwen/qwen3-coder:free (OpenRouter)": ("openrouter", "qwen/qwen3-coder:free"),
}


@st.cache_resource
def load_pipeline(provider: str, model: str) -> TextToSQLPipeline:
    settings = Settings(default_provider=provider, default_model=model)
    return TextToSQLPipeline(settings)


def _try_chart(df: pd.DataFrame | None) -> bool:
    if df is None or df.empty or len(df.columns) < 2:
        return False
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    if not numeric_cols:
        return False
    label_col = df.columns[0]
    value_col = numeric_cols[0]
    if df[label_col].nunique() > 30:
        return False
    st.bar_chart(df.set_index(label_col)[value_col])
    return True


def _render_response(payload: dict, show_sql_first: bool) -> None:
    if not payload["success"]:
        st.error(f"Failed after {payload['attempts']} attempt(s): {payload['error']}")
        if payload["sql"]:
            with st.expander("Last generated SQL"):
                st.code(payload["sql"], language="sql")
        return

    if show_sql_first:
        tab_sql, tab_results, tab_chart = st.tabs(["SQL", "Results", "Chart"])
    else:
        tab_results, tab_sql, tab_chart = st.tabs(["Results", "SQL", "Chart"])

    with tab_results:
        df = payload["data"]
        if df is not None and not df.empty:
            st.dataframe(df, use_container_width=True)
        else:
            st.info("Query returned no rows.")

    with tab_sql:
        st.code(payload["sql"], language="sql")

    with tab_chart:
        if not _try_chart(payload["data"]):
            st.info("No chart available for this result shape.")

    st.caption(
        f"Execution: {payload['execution_time_ms']:.0f} ms • "
        f"Attempts: {payload['attempts']}"
    )


def main() -> None:
    st.set_page_config(
        page_title="GST Text-to-SQL Assistant",
        layout="wide",
    )
    st.title("GST Text-to-SQL Assistant")

    with st.sidebar:
        st.header("Settings")
        selected_label = st.selectbox("Model", list(MODEL_OPTIONS.keys()))
        provider, model = MODEL_OPTIONS[selected_label]
        temperature = st.slider("Temperature", 0.0, 1.0, 0.0, step=0.05)
        show_sql_first = st.toggle("Show SQL first", value=True)

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
                _render_response(msg["payload"], show_sql_first)

    question: str | None = None
    if prompt := st.chat_input("Ask a question about GST data..."):
        question = prompt
    elif "pending_question" in st.session_state:
        question = st.session_state.pop("pending_question")

    if question:
        st.session_state.messages.append({"role": "user", "content": question})
        with st.chat_message("user"):
            st.write(question)

        pipeline = load_pipeline(provider, model)
        pipeline._settings.temperature = temperature

        with st.chat_message("assistant"):
            with st.spinner("Generating SQL and executing..."):
                result = pipeline.ask(question)
            payload: dict = {
                "success": result.success,
                "sql": result.sql,
                "data": result.data,
                "error": result.error,
                "attempts": result.attempts,
                "execution_time_ms": result.execution_time_ms,
            }
            _render_response(payload, show_sql_first)
            st.session_state.messages.append({"role": "assistant", "payload": payload})


if __name__ == "__main__":
    main()
