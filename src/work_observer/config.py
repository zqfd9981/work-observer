"""M0 配置；不读取桌面登录令牌，密钥仅从环境或被忽略的 .env 加载。"""

import os
import tomllib
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


def validate_url(value: str) -> str:
    url = urlsplit(value)
    if url.username or url.password or url.query or url.fragment:
        raise ValueError("URL 不允许包含凭据、查询参数或片段")
    if not url.hostname or url.scheme not in {"http", "https"}:
        raise ValueError("需要 HTTP(S) 地址")
    if url.scheme != "https" and url.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("非本地连接需要 HTTPS")
    return value.rstrip("/")


class MCPConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    transport: Literal["stdio", "streamable-http", "sse"] = "stdio"
    command: str | None = None
    args: list[str] = Field(default_factory=list)
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict, repr=False)
    url: str | None = None
    bearer_token_env: str | None = None
    timeout_seconds: int = Field(default=90, ge=1, le=300)

    @model_validator(mode="after")
    def validate_transport(self):
        if self.transport == "stdio" and not self.command:
            raise ValueError("stdio 缺少 command")
        if self.transport != "stdio":
            if not self.url:
                raise ValueError("远程 MCP 缺少 url")
            self.url = validate_url(self.url)
        return self


class Settings(BaseModel):
    database_path: Path = Path("data/app.db")
    raw_directory: Path = Path("data/raw/m1")
    mcp_config: Path = Path("configs/mcp.local.toml")
    model_base_url: str = ""
    model_name: str = ""
    model_api: Literal["responses", "chat-completions"] = "responses"
    model_api_key: SecretStr = SecretStr("")
    search_provider: Literal["openai", "tavily"] = "openai"
    tavily_api_key: SecretStr = SecretStr("")
    access_token: SecretStr = SecretStr("")
    public_origin: str = ""

    @classmethod
    def load(cls, env_file: Path = Path(".env")):
        load_dotenv(env_file, override=False)
        return cls(
            database_path=Path(os.getenv("WO_DATABASE_PATH", "data/app.db")),
            raw_directory=Path(os.getenv("WO_RAW_DIRECTORY", "data/raw/m1")),
            mcp_config=Path(os.getenv("WO_MCP_CONFIG", "configs/mcp.local.toml")),
            model_base_url=os.getenv("WO_MODEL_BASE_URL", "").strip(),
            model_name=os.getenv("WO_MODEL_NAME", "").strip(),
            model_api=os.getenv("WO_MODEL_API", "responses").strip(),
            model_api_key=os.getenv("WO_MODEL_API_KEY", ""),
            search_provider=os.getenv("WO_SEARCH_PROVIDER", "openai").strip(),
            tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
            access_token=os.getenv("WO_ACCESS_TOKEN", ""),
            public_origin=os.getenv("WO_PUBLIC_ORIGIN", "").strip().rstrip("/"),
        )

    def load_mcp(self) -> MCPConfig:
        with self.mcp_config.open("rb") as f:
            return MCPConfig.model_validate(tomllib.load(f))
