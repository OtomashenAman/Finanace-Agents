import re
from typing import Any, ClassVar

_KEY = re.compile(r"[a-z][a-z0-9_]*")
_CODE = re.compile(r"\d{2}")


class BaseAgent:
    """Code definition of one finance agent.

    Subclass it in its own module under agents/ and add the class to registry.AGENTS.
    Later each agent also gets its input schema, rules engine and prompt here.
    """

    key: ClassVar[str]  # stable id used in URLs and the DB, e.g. "ap_invoice"
    code: ClassVar[str]  # display number, e.g. "01"
    name: ClassVar[str]
    short_name: ClassVar[str]  # used in worklists, e.g. "AP Invoice"
    description: ClassVar[str]
    primary_user: ClassVar[str]  # preparer role label, e.g. "AP Analyst"
    reviewer: ClassVar[str]  # reviewer role label, e.g. "AP Approver"

    _required: ClassVar[tuple[str, ...]] = (
        "key",
        "code",
        "name",
        "short_name",
        "description",
        "primary_user",
        "reviewer",
    )

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        missing = [attr for attr in cls._required if not getattr(cls, attr, None)]
        if missing:
            raise TypeError(f"{cls.__name__} is missing: {', '.join(missing)}")
        if not _KEY.fullmatch(cls.key):
            raise TypeError(f"{cls.__name__}.key must be snake_case, got {cls.key!r}")
        if not _CODE.fullmatch(cls.code):
            raise TypeError(f"{cls.__name__}.code must be two digits, got {cls.code!r}")

    @classmethod
    def sort_order(cls) -> int:
        return int(cls.code)
