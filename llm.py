from langchain_ollama import ChatOllama

llm = ChatOllama(
    model="qwen3:8b",
    temperature=0,
    format="json",  # Force JSON output for structured tool calls
)