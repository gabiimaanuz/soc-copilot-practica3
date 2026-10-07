from fastapi import APIRouter

from app.config import get_settings
from app.middleware.auth import CurrentUser

router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/models")
def list_models(_: CurrentUser) -> dict[str, str | list[str]]:
    """Available chat models for the frontend selector.

    Returned models are guaranteed to support JSON-mode structured output
    (response_schema) so any of them works for /explain, /recommend and
    /chat. Fixed allowlist on the server prevents users from picking
    expensive or unstable models.
    """
    s = get_settings()
    return {"default": s.gemini_chat_model, "available": s.chat_models_list}
