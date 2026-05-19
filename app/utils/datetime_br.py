"""Datas e fuso horário do Brasil (America/Sao_Paulo)."""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

BRAZIL_TZ = ZoneInfo("America/Sao_Paulo")


def to_brazil_time(dt: datetime | None) -> datetime | None:
    """Converte datetime (UTC ou naive do SQLite) para horário de Brasília."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BRAZIL_TZ)


def format_brazil_datetime(dt: datetime | None, fmt: str = "%d/%m/%Y %H:%M") -> str:
    local = to_brazil_time(dt)
    return local.strftime(fmt) if local else "—"


def brazil_today() -> date:
    return datetime.now(BRAZIL_TZ).date()
