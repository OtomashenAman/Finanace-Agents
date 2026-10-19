from src.app.core.errors import AppError


class AgentNotFoundError(AppError):
    # Also used when the agent exists but the user has no access: don't reveal it
    status_code = 404
    code = "agent_not_found"
    message = "Agent not found."
