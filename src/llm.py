from pathlib import Path
import os

from dotenv import load_dotenv
from langchain_aws import ChatBedrockConverse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

loaded = load_dotenv(dotenv_path=ENV_PATH, override=True)

AWS_REGION = os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "ap-southeast-1"))
BEDROCK_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID",
    "global.anthropic.claude-sonnet-4-6",
)
BEDROCK_MAX_TOKENS = int(os.getenv("BEDROCK_MAX_TOKENS", "4096"))

BEDROCK_API_KEY = os.getenv("AWS_BEARER_TOKEN")

if BEDROCK_API_KEY:
    os.environ["AWS_BEARER_TOKEN_BEDROCK"] = BEDROCK_API_KEY

if not loaded:
    raise RuntimeError(f".env file was not loaded. Expected path: {ENV_PATH}")

if not BEDROCK_API_KEY:
    raise RuntimeError(
        "Missing AWS_BEARER_TOKEN in .env. "
        f"Checked .env path: {ENV_PATH}"
    )

llm = ChatBedrockConverse(
    model=BEDROCK_MODEL_ID,
    region_name=AWS_REGION,
    bedrock_api_key=BEDROCK_API_KEY,
    max_tokens=BEDROCK_MAX_TOKENS,
)