from __future__ import annotations

from datetime import datetime, timezone


def parse_svn_datetime(raw: str) -> datetime:
    """
    把 svn 返回的 ISO8601 UTC 字符串解析成 datetime(aware, tz=UTC)
    示例: "2025-10-24T11:15:32.123456Z"
    """

    # 去掉末尾的Z并加入+00:00
    # "YYYY-mm-ddTHH:MM:SS(.microsec)?Z"
    if raw.endswith("Z"):
        raw_no_z = raw[:-1]
        # Python 3.9 的 fromisoformat 不能直接吃 '...Z'
        # 但能吃 '...+00:00'
        raw_adj = raw_no_z + "+00:00"
        dt = datetime.fromisoformat(raw_adj)
        return dt.astimezone(timezone.utc)

    # 理论上 svn 都给Z；fallback:
    dt = datetime.fromisoformat(raw)
    # 如果这个没有tzinfo，给它补上UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt
