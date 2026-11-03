from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles
from app.config import get_settings
from app.db.session import get_db
from app.operational_intelligence.service import OperationalIntelligenceService
from app.schemas import OperationalAnalysisRead, OperationalRecommendationRead

router = APIRouter(prefix="/organizations/{organization_id}/operational-intelligence", tags=["operational-intelligence"])
READ_ROLES = tuple(CommercialRole)


def get_service() -> OperationalIntelligenceService:
    return OperationalIntelligenceService(get_settings())


def serialize(item) -> OperationalAnalysisRead:
    data = item.__dict__.copy()
    data["evidence"] = list(item.evidence)
    data["limitations"] = list(item.limitations)
    return OperationalAnalysisRead(**data)


def safe_analysis(session: Session, organization_id, service: OperationalIntelligenceService) -> dict[str, object]:
    try:
        return service.summary(session, organization_id)
    except SQLAlchemyError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Operational intelligence data is temporarily unavailable.") from error


@router.get("/anomalies", response_model=list[OperationalAnalysisRead])
def anomalies(context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> list[OperationalAnalysisRead]:
    return [serialize(item) for item in safe_analysis(session, context.organization.id, service)["anomalies"]]


@router.get("/trends", response_model=list[OperationalAnalysisRead])
def trends(context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> list[OperationalAnalysisRead]:
    return [serialize(item) for item in safe_analysis(session, context.organization.id, service)["trends"]]


@router.get("/findings", response_model=list[OperationalAnalysisRead])
def findings(context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> list[OperationalAnalysisRead]:
    return [serialize(item) for item in safe_analysis(session, context.organization.id, service)["findings"]]


@router.get("/recommendations", response_model=list[OperationalRecommendationRead])
def recommendations(context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> list[OperationalRecommendationRead]:
    return [OperationalRecommendationRead(**item) for item in safe_analysis(session, context.organization.id, service)["recommendations"]]


@router.get("/summary")
def summary(context: OrgContext = Depends(require_org_roles(*READ_ROLES)), session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> dict[str, object]:
    result = safe_analysis(session, context.organization.id, service)
    return {**result, "anomalies": [serialize(item).model_dump(mode="json") for item in result["anomalies"]], "trends": [serialize(item).model_dump(mode="json") for item in result["trends"]], "findings": [serialize(item).model_dump(mode="json") for item in result["findings"]], "data_limitations": [serialize(item).model_dump(mode="json") for item in result["data_limitations"]]}
