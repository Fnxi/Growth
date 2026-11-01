from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.operational_intelligence.service import OperationalIntelligenceService
from app.schemas import OperationalAnalysisRead, OperationalRecommendationRead

router = APIRouter(prefix="/operational-intelligence", tags=["operational-intelligence"])


def get_service() -> OperationalIntelligenceService:
    return OperationalIntelligenceService(get_settings())


def serialize(item) -> OperationalAnalysisRead:
    data = item.__dict__.copy()
    data["evidence"] = list(item.evidence)
    data["limitations"] = list(item.limitations)
    return OperationalAnalysisRead(**data)


def safe_analysis(session: Session, service: OperationalIntelligenceService) -> dict[str, object]:
    try:
        return service.summary(session)
    except SQLAlchemyError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Operational intelligence data is temporarily unavailable.") from error


@router.get("/anomalies", response_model=list[OperationalAnalysisRead])
def anomalies(session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> list[OperationalAnalysisRead]:
    return [serialize(item) for item in safe_analysis(session, service)["anomalies"]]


@router.get("/trends", response_model=list[OperationalAnalysisRead])
def trends(session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> list[OperationalAnalysisRead]:
    return [serialize(item) for item in safe_analysis(session, service)["trends"]]


@router.get("/findings", response_model=list[OperationalAnalysisRead])
def findings(session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> list[OperationalAnalysisRead]:
    return [serialize(item) for item in safe_analysis(session, service)["findings"]]


@router.get("/recommendations", response_model=list[OperationalRecommendationRead])
def recommendations(session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> list[OperationalRecommendationRead]:
    return [OperationalRecommendationRead(**item) for item in safe_analysis(session, service)["recommendations"]]


@router.get("/summary")
def summary(session: Session = Depends(get_db), service: OperationalIntelligenceService = Depends(get_service)) -> dict[str, object]:
    result = safe_analysis(session, service)
    return {**result, "anomalies": [serialize(item).model_dump(mode="json") for item in result["anomalies"]], "trends": [serialize(item).model_dump(mode="json") for item in result["trends"]], "findings": [serialize(item).model_dump(mode="json") for item in result["findings"]], "data_limitations": [serialize(item).model_dump(mode="json") for item in result["data_limitations"]]}
