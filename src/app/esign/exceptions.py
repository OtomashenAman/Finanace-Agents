from src.app.core.errors import AppError


class PandaDocNotConfiguredError(AppError):
    status_code = 503
    code = "esign_not_configured"
    message = "E-signature isn't set up yet: PANDADOC_API_KEY is missing on the server."


class PandaDocError(AppError):
    status_code = 502
    code = "esign_provider_error"
    message = "PandaDoc refused the request."

    def __init__(self, message: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.provider_status = status


class TemplateNotFoundError(AppError):
    # Someone else's template is "not found" too: don't reveal it exists
    status_code = 404
    code = "esign_template_not_found"
    message = "Template not found."


class DocumentNotFoundError(AppError):
    status_code = 404
    code = "esign_document_not_found"
    message = "Document not found."


class TemplateRejectedError(AppError):
    status_code = 422
    code = "esign_template_rejected"
    message = "Upload a PDF, Word (.docx) or RTF file."


class TemplateTooLargeError(AppError):
    status_code = 413
    code = "esign_template_too_large"
    message = "The file is too large."


class DocumentNotSendableError(AppError):
    status_code = 409
    code = "esign_not_sendable"
    message = "This document can't be sent now."


class WebhookRejectedError(AppError):
    status_code = 401
    code = "esign_webhook_rejected"
    message = "Webhook signature missing or wrong."


class WebhookNotConfiguredError(AppError):
    status_code = 503
    code = "esign_webhook_not_configured"
    message = "Webhooks aren't set up: PANDADOC_WEBHOOK_KEY is missing on the server."


class SendRejectedError(AppError):
    status_code = 422
    code = "esign_send_rejected"
    message = "This document can't be sent like this."
