from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware current time. Use this instead of datetime.now() everywhere."""
    return datetime.now(UTC)
