from src.app.core.errors import AppError


class EntityNotFoundError(AppError):
    status_code = 404
    code = "entity_not_found"
    message = "Legal entity not found."


class EntityCodeTakenError(AppError):
    status_code = 409
    code = "entity_code_taken"
    message = "A legal entity with this code already exists."


class EntityRequiredError(AppError):
    status_code = 422
    code = "entity_required"
    message = "Choose the legal entity this run is for."


class EntityNotAllowedError(AppError):
    # Same for unknown, inactive and not-assigned: don't reveal which
    status_code = 403
    code = "entity_not_allowed"
    message = "You can't file runs for this legal entity."


class NoEntitiesAssignedError(AppError):
    status_code = 403
    code = "no_entities_assigned"
    message = "You aren't assigned to any legal entity yet. Ask your Finance Admin for access."
