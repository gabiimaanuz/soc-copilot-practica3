import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.db import DbSession
from app.middleware.auth import CurrentUser
from app.middleware.ratelimit import rate_limit
from app.schemas.alerts import ChatRequest, ChatResponse
from app.services.audit import log_audit
from app.services.chat import chat as chat_service
from app.services.language import resolve_language
from app.services.llm import LLMProviderError, LLMResponseError

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/chat", tags=["chat-ia"], dependencies=[Depends(rate_limit)]
)


@router.post("", response_model=ChatResponse)
def chat(
    payload: ChatRequest, user: CurrentUser, db: DbSession, request: Request
) -> ChatResponse:
    last_question = next(
        (m.content for m in reversed(payload.messages) if m.role == "user"), None
    )
    # Auto-detect from the analyst's question; fall back to body/UI language.
    language = resolve_language(payload.language, request, text=last_question)
    try:
        response = chat_service(
            payload.messages,
            payload.log_context,
            model=payload.model,
            user=user,
            db=db,
            language=language,
        )
        log_audit(
            db,
            actor=user,
            action="chat.message",
            details={"model": payload.model, "language": language},
        )
        db.commit()
        return response
    except LLMProviderError:
        logger.exception("LLM provider error in /chat")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="AI provider error"
        ) from None
    except LLMResponseError:
        logger.exception("LLM response could not be processed in /chat")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="AI response could not be processed",
        ) from None
