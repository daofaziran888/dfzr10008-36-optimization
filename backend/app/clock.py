"""时间口径：认证是否过期统一以参考日期（含边界）判断。

业务验收以固定日期 2026-11-13 为「当前日期」，同时允许用环境变量
APP_REFERENCE_DATE 覆盖，方便测试与部署环境切换口径。
"""
from __future__ import annotations

from datetime import date, datetime

DEFAULT_REFERENCE_DATE = "2026-11-13"
DATE_FMT = "%Y-%m-%d"


def reference_date() -> date:
    """返回业务当前日期；解析失败时回退到默认参考日期而不是让接口 500。"""
    from app.config import settings

    raw = (getattr(settings, "reference_date", None) or DEFAULT_REFERENCE_DATE).strip()
    try:
        return datetime.strptime(raw, DATE_FMT).date()
    except ValueError:
        return datetime.strptime(DEFAULT_REFERENCE_DATE, DATE_FMT).date()


def parse_date(value: object) -> date | None:
    """把 'YYYY-MM-DD' 或带时间的字符串解析成日期；非法输入返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in (DATE_FMT, "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_datetime(value: object) -> datetime | None:
    """解析审批时间；只给日期时补零时刻，保证两次并发延期可比较先后。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", DATE_FMT):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def is_expired(valid_until: object, *, today: date | None = None) -> bool:
    """过期边界：当前日期严格晚于有效期限才算过期，到期当日仍有效。"""
    end = parse_date(valid_until)
    if end is None:
        return False
    return (today or reference_date()) > end
