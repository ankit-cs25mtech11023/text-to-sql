"""
Interactive test for the full pipeline (Phase 3).
Run: python test_llm.py
"""
from config.settings import get_settings
from core.pipeline import TextToSQLPipeline

pipeline = TextToSQLPipeline(get_settings())

print("Pipeline ready. Type 'quit' to exit.\n")

while True:
    try:
        question = input("Your question: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not question or question.lower() in ("quit", "q", "exit"):
        break

    result = pipeline.ask(question)

    print(f"\nSQL:      {result.sql}")
    print(f"Attempts: {result.attempts}  |  Time: {result.execution_time_ms}ms")

    if result.success:
        print(f"Rows:     {result.row_count if hasattr(result, 'row_count') else len(result.data)}")
        print(result.data.to_string(index=False))
    else:
        print(f"ERROR:    {result.error}")

    print()
