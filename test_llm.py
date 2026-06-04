"""
Quick interactive test for the LLM pipeline.
Run: python test_llm.py
"""
from config.settings import get_settings
from database.connection import get_engine
from core.schema_extractor import SchemaExtractor
from core.prompt_builder import PromptBuilder
from core.sql_generator import SQLGenerator
from core.llm_client import make_client

s = get_settings()
engine = get_engine("database/gst_demo.db")
ctx = SchemaExtractor(engine, "database/descriptions.json").get_full_context()
gen = SQLGenerator(
    make_client(s.default_provider, s.groq_api_key, s.default_model),
    PromptBuilder(ctx),
)

print(f"Model: {s.default_model}  |  Type 'quit' to exit\n")

while True:
    try:
        question = input("Your question: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if not question or question.lower() in ("quit", "q", "exit"):
        break
    sql, _ = gen.generate(question)
    print(f"SQL: {sql}\n")
