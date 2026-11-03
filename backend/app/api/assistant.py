import logging
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles
from app.assistant.limits import AssistantRequestLimiter
from app.assistant.providers import AssistantProviderError
from app.assistant.service import AssistantService, get_assistant_service
from app.config import get_settings
from app.db.session import get_db
from app.schemas import AssistantChatRequest, AssistantResponse, AssistantStatusRead

router = APIRouter(prefix="/organizations/{organization_id}/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)
READ_ROLES = tuple(CommercialRole)


@lru_cache
def get_assistant_limiter() -> AssistantRequestLimiter:
    settings = get_settings()
    return AssistantRequestLimiter(settings.ai_rate_limit, settings.ai_rate_window_seconds, settings.ai_max_concurrent_requests)


def enforce_assistant_limits(request: Request) -> object:
    result = get_assistant_limiter().acquire(request.client.host if request.client else "unknown")
    if not result.allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Assistant request limit reached.", headers={"Retry-After": str(result.retry_after or 1)})
    try:
        yield
    finally:
        get_assistant_limiter().release()


@router.get("/status", response_model=AssistantStatusRead)
def assistant_status(context: OrgContext = Depends(require_org_roles(*READ_ROLES)), service: AssistantService = Depends(get_assistant_service)) -> AssistantStatusRead:
    return service.status()


def _chat(payload: AssistantChatRequest, context: OrgContext, session: Session, service: AssistantService) -> AssistantResponse:
    try:
        return service.chat(session, context.organization.id, payload)
    except AssistantProviderError as error:
        detail = "The AI assistant is not available." if error.code == "not_available" else "The AI provider could not complete the request."
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from error
    except Exception:
        logger.error("assistant_request status=failed code=internal_error")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="The AI assistant encountered an internal error.")


@router.post("/chat", response_model=AssistantResponse, dependencies=[Depends(enforce_assistant_limits)])
def assistant_chat(payload: AssistantChatRequest, context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db), service: AssistantService = Depends(get_assistant_service)) -> AssistantResponse:
    return _chat(payload, context, session, service)


@router.post("/diagnosis", response_model=AssistantResponse, dependencies=[Depends(enforce_assistant_limits)])
def assistant_diagnosis(context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db), service: AssistantService = Depends(get_assistant_service)) -> AssistantResponse:
    return _chat(AssistantChatRequest(question="Provide a concise commercial diagnosis and recommendations."), context, session, service)
