from dotenv import load_dotenv
import os

load_dotenv()

SECRET_KEY: str = os.getenv("SECRET_KEY", "nsai-secret-key-change-in-production")
ALGORITHM: str = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./leadgen.db")
GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
OPENROUTER_API_KEY: str = os.getenv("OPENROUTER_API_KEY", "")
PRIMARY_MODEL: str = os.getenv("PRIMARY_MODEL", "anthropic/claude-sonnet-4-20250514")
FALLBACK_MODEL: str = os.getenv("FALLBACK_MODEL", "openai/gpt-4o-mini")
OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
PRIMARY_MODEL: str = os.getenv("PRIMARY_MODEL", "meta-llama/llama-3.3-70b-instruct")
FALLBACK_MODEL: str = os.getenv("FALLBACK_MODEL", "openai/gpt-4o-mini")
APOLLO_API_KEY: str = os.getenv("APOLLO_API_KEY", "")
REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SENDGRID_API_KEY: str = os.getenv("SENDGRID_API_KEY", "")
WEBHOOK_BASE_URL: str = os.getenv("WEBHOOK_BASE_URL", "http://localhost:8000")
ZEROBOUNCE_API_KEY: str = os.getenv("ZEROBOUNCE_API_KEY", "")
GUPSHUP_API_KEY: str = os.getenv("GUPSHUP_API_KEY", "")
GUPSHUP_APP_NAME: str = os.getenv("GUPSHUP_APP_NAME", "")
GUPSHUP_SOURCE_NUMBER: str = os.getenv("GUPSHUP_SOURCE_NUMBER", "")
GOOGLE_PLACES_API_KEY: str = os.getenv("GOOGLE_PLACES_API_KEY", "")
RAZORPAY_KEY_ID: str = os.getenv("RAZORPAY_KEY_ID", "")
RAZORPAY_KEY_SECRET: str = os.getenv("RAZORPAY_KEY_SECRET", "")
RAZORPAY_WEBHOOK_SECRET: str = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")
