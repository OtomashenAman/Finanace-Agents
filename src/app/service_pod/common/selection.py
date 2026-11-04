"""Reading a case's selection with the workflow's own schema."""

from typing import Any

from pydantic import BaseModel, ValidationError

from src.app.service_pod.core.cases.exceptions import CaseSelectionError


def parse_selection[T: BaseModel](model: type[T], selection: dict[str, Any]) -> T:
    try:
        return model.model_validate(selection)
    except ValidationError as exc:
        first = exc.errors()[0]
        where = ".".join(str(p) for p in first["loc"])
        raise CaseSelectionError(f"Selection {where}: {first['msg']}") from exc
