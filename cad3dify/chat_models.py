import os
from typing import Literal

try:
    import vertexai
    vertexai.init(project=os.environ["VERTEXAI_PROJECT"], location=os.environ["VERTEXAI_LOCATION"])
except KeyError:
    print("VertexAI is not initialized. Please set VERTEXAI_PROJECT and VERTEXAI_LOCATION environment variables.")
except Exception as e:
    pass
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

MODEL_TYPE = Literal["gpt", "claude", "gemini", "llama", "custom"]
PROVIDER_TYPE = Literal["openai", "anthropic", "google", "vertex_ai", "openai_compatible"]


class ChatModelParameters(BaseModel):
    provider: PROVIDER_TYPE
    model_name: str
    temperature: float
    max_tokens: int | None = None
    base_url: str | None = None
    api_key: str | None = None
    request_timeout: float | None = None
    max_retries: int = 2

    @staticmethod
    def _normalize_openai_base_url(base_url: str) -> str:
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            normalized = normalized[: -len("/chat/completions")]
        if not normalized.endswith("/v1"):
            normalized = f"{normalized}/v1"
        return normalized

    @classmethod
    def default(cls) -> "ChatModelParameters":
        return cls(
            provider="openai",
            model_name="gpt-5-2025-08-07",
            temperature=1.0,
            max_tokens=128000,
            request_timeout=float(os.getenv("OPENAI_REQUEST_TIMEOUT", "180")),
            max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "3")),
        )

    @classmethod
    def from_model_name(
        cls,
        model_type: MODEL_TYPE,
        temperature: float = 1.0,
    ) -> "ChatModelParameters":
        model_type_to_parameters = {
            "gpt": cls(
                provider="openai",
                model_name="gpt-5-2025-08-07",
                temperature=temperature,
                max_tokens=128000,
                request_timeout=float(os.getenv("OPENAI_REQUEST_TIMEOUT", "180")),
                max_retries=int(os.getenv("OPENAI_MAX_RETRIES", "3")),
            ),
            "claude": cls(
                provider="anthropic",
                model_name="claude-opus-4-5-20251101",
                temperature=temperature,
                max_tokens=32000,
            ),
            "gemini": cls(
                provider="google",
                model_name="gemini-3-pro-preview",
                temperature=temperature,
                max_tokens=6400,
            ),
            "llama": cls(
                provider="vertex_ai",
                model_name="meta/llama-3.2-90b-vision-instruct-maas",
                temperature=temperature,
            ),
            "custom": cls(
                provider="openai_compatible",
                model_name=os.getenv("CUSTOM_OPENAI_MODEL", ""),
                temperature=temperature,
                max_tokens=int(os.getenv("CUSTOM_OPENAI_MAX_TOKENS", "4096")),
                base_url=os.getenv("CUSTOM_OPENAI_BASE_URL"),
                api_key=os.getenv("CUSTOM_OPENAI_API_KEY"),
                request_timeout=float(os.getenv("CUSTOM_OPENAI_REQUEST_TIMEOUT", "180")),
                max_retries=int(os.getenv("CUSTOM_OPENAI_MAX_RETRIES", "4")),
            ),
        }
        return model_type_to_parameters.get(model_type, cls.default())

    def create_chat_model(self) -> BaseChatModel:
        if self.provider == "openai":
            return ChatOpenAI(
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                timeout=self.request_timeout,
                max_retries=self.max_retries,
            )
        elif self.provider == "openai_compatible":
            import httpx

            base_url = self.base_url or os.getenv("CUSTOM_OPENAI_BASE_URL")
            api_key = self.api_key or os.getenv("CUSTOM_OPENAI_API_KEY")
            if not self.model_name:
                raise ValueError("CUSTOM_OPENAI_MODEL is not set.")
            if not base_url:
                raise ValueError("CUSTOM_OPENAI_BASE_URL is not set.")
            if not api_key:
                raise ValueError("CUSTOM_OPENAI_API_KEY is not set.")
            if api_key in {"你的key", "your_key", "<YOUR_API_KEY>"}:
                raise ValueError("CUSTOM_OPENAI_API_KEY is a placeholder. Please replace it with your real API key.")
            try:
                api_key.encode("ascii")
            except UnicodeEncodeError as exc:
                raise ValueError("CUSTOM_OPENAI_API_KEY must contain ASCII characters only.") from exc
            normalized_base_url = self._normalize_openai_base_url(base_url)
            return ChatOpenAI(
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                base_url=normalized_base_url,
                api_key=api_key,
                timeout=self.request_timeout,
                max_retries=self.max_retries,
                http_client=httpx.Client(timeout=self.request_timeout or 180.0, trust_env=False),
            )
        elif self.provider == "anthropic":
            return ChatAnthropic(
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        elif self.provider == "google":
            return ChatGoogleGenerativeAI(
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
        elif self.provider == "vertex_ai":
            from google.auth import default
            from langchain_google_vertexai.model_garden_maas.llama import (
                VertexModelGardenLlama,
            )

            credentials, _ = default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
            return VertexModelGardenLlama(
                model_name=self.model_name,
                temperature=self.temperature,
                credentials=credentials,
            )
        else:
            raise ValueError(f"provider {self.provider} is not supported.")
