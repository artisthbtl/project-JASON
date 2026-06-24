from pathlib import Path
import os
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"

loaded = load_dotenv(dotenv_path=ENV_PATH, override=True)

key = os.getenv("AWS_BEARER_TOKEN")
bedrock_key = os.getenv("AWS_BEARER_TOKEN_BEDROCK")

print("Project root:", PROJECT_ROOT)
print(".env path:", ENV_PATH)
print(".env exists:", ENV_PATH.exists())
print(".env loaded:", loaded)
print("AWS_REGION:", os.getenv("AWS_REGION"))
print("BEDROCK_MODEL_ID:", os.getenv("BEDROCK_MODEL_ID"))
print("AWS_BEARER_TOKEN loaded:", bool(key))
print("AWS_BEARER_TOKEN prefix:", key[:8] if key else None)
print("AWS_BEARER_TOKEN_BEDROCK loaded before bridge:", bool(bedrock_key))