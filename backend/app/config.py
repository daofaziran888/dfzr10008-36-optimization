"""运行配置：端口、跨域、运行环境。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Settings:
    app_name: str = "数据产品与API工厂"
    env: str = "local"
    port: int = 8000
    # 认证有效期判定的业务当前日期，可用环境变量 APP_REFERENCE_DATE 覆盖
    reference_date: str = os.getenv("APP_REFERENCE_DATE", "2026-11-13")
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            "http://127.0.0.1:5173",
            "http://localhost:5173",
        ]
    )
    page_size_default: int = 20
    page_size_max: int = 200


settings = Settings()
