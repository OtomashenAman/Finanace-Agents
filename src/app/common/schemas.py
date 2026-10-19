from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    """Shape of every AppError response (used in OpenAPI `responses=`)."""

    detail: ErrorDetail
