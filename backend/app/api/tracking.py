from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from hashlib import blake2b
from secrets import token_bytes, token_urlsafe
from threading import Lock
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.api.experiments import get_experiment_or_404
from app.config import get_settings
from app.db.models import Experiment, TrackingEvent, TrackingLink
from app.db.session import get_db
from app.schemas import TrackingLinkCreate, TrackingLinkRead, TrackingLinkUpdate

router = APIRouter(tags=["tracking"])
_requests: dict[str, deque[datetime]] = defaultdict(deque)
_rate_lock = Lock()
_rate_salt = token_bytes(32)


def is_allowed_destination(url: str) -> bool:
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    try:
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and not parsed.username
        and not parsed.password
        and port in (None, 443)
        and host in get_settings().allowed_destination_hosts
    )


def tracking_url(code: str) -> str:
    return f"{get_settings().tracking_base_url.rstrip('/')}/r/{code}"


def serialize_link(link: TrackingLink) -> TrackingLinkRead:
    return TrackingLinkRead(
        id=link.id,
        experiment_id=link.experiment_id,
        campaign_id=link.experiment.campaign_id,
        code=link.code,
        destination_url=link.destination_url,
        tracking_url=tracking_url(link.code),
        utm_source=link.utm_source,
        utm_medium=link.utm_medium,
        utm_campaign=link.utm_campaign,
        utm_content=link.utm_content,
        is_active=link.is_active,
        created_at=link.created_at,
    )


def destination_with_utm(link: TrackingLink) -> str:
    parsed = urlsplit(link.destination_url)
    query = parse_qsl(parsed.query, keep_blank_values=True)
    query.extend([("utm_source", link.utm_source), ("utm_medium", link.utm_medium), ("utm_campaign", link.utm_campaign)])
    if link.utm_content:
        query.append(("utm_content", link.utm_content))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query, doseq=True), parsed.fragment))


def request_allowed(request: Request) -> bool:
    client = request.client.host if request.client else "unknown"
    key = blake2b(client.encode(), key=_rate_salt, digest_size=16).hexdigest()
    now = datetime.now(timezone.utc)
    settings = get_settings()
    with _rate_lock:
        bucket = _requests[key]
        cutoff = now - timedelta(seconds=settings.tracking_rate_window_seconds)
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= settings.tracking_rate_limit:
            return False
        bucket.append(now)
    return True


@router.post("/tracking-links", response_model=TrackingLinkRead, status_code=201)
def create_tracking_link(payload: TrackingLinkCreate, session: Session = Depends(get_db)) -> TrackingLinkRead:
    get_experiment_or_404(payload.experiment_id, session)
    destination = str(payload.destination_url)
    if not is_allowed_destination(destination):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Destination host is not allowed.")
    for _ in range(3):
        link = TrackingLink(code=token_urlsafe(12), destination_url=destination, **payload.model_dump(exclude={"destination_url"}))
        session.add(link)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            continue
        session.refresh(link)
        return serialize_link(link)
    raise HTTPException(status_code=503, detail="Could not allocate a unique tracking code.")


@router.get("/tracking-links", response_model=list[TrackingLinkRead])
def list_tracking_links(experiment_id: UUID | None = None, session: Session = Depends(get_db)) -> list[TrackingLinkRead]:
    query = select(TrackingLink).options(selectinload(TrackingLink.experiment)).order_by(TrackingLink.created_at.desc())
    if experiment_id:
        query = query.where(TrackingLink.experiment_id == experiment_id)
    return [serialize_link(link) for link in session.scalars(query)]


@router.patch("/tracking-links/{link_id}", response_model=TrackingLinkRead)
def update_tracking_link(link_id: UUID, payload: TrackingLinkUpdate, session: Session = Depends(get_db)) -> TrackingLinkRead:
    link = session.scalar(select(TrackingLink).options(selectinload(TrackingLink.experiment)).where(TrackingLink.id == link_id))
    if link is None:
        raise HTTPException(status_code=404, detail="Tracking link not found.")
    link.is_active = payload.is_active
    session.commit()
    session.refresh(link)
    return serialize_link(link)


@router.get("/tracking-links/{link_id}/clicks")
def link_clicks(link_id: UUID, session: Session = Depends(get_db)) -> dict[str, object]:
    link = session.get(TrackingLink, link_id)
    if link is None:
        raise HTTPException(status_code=404, detail="Tracking link not found.")
    clicks = session.scalar(select(func.count()).select_from(TrackingEvent).where(TrackingEvent.tracking_link_id == link_id, TrackingEvent.event_type == "click"))
    return {"tracking_link_id": str(link_id), "clicks_registered": clicks or 0, "limitations": ["Clicks are not unique people, reach, or Instagram impressions."]}


@router.get("/tracking/attribution")
def tracking_attribution(group_by: str = "utm_source", experiment_id: UUID | None = None, occurred_from: datetime | None = None, occurred_to: datetime | None = None, session: Session = Depends(get_db)) -> dict[str, object]:
    columns = {"utm_source": TrackingLink.utm_source, "utm_medium": TrackingLink.utm_medium, "experiment": TrackingLink.experiment_id}
    column = columns.get(group_by)
    if column is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Unsupported group_by.")
    if occurred_from and occurred_to and occurred_to < occurred_from:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid activity period.")
    query = select(column.label("dimension"), func.count(TrackingEvent.id).label("clicks")).join(TrackingEvent).where(TrackingEvent.event_type == "click")
    if experiment_id:
        query = query.where(TrackingLink.experiment_id == experiment_id)
    if occurred_from:
        query = query.where(TrackingEvent.occurred_at >= occurred_from)
    if occurred_to:
        query = query.where(TrackingEvent.occurred_at <= occurred_to)
    rows = session.execute(query.group_by(column).order_by(column)).all()
    return {"group_by": group_by, "results": [{"dimension": str(row.dimension), "clicks_registered": row.clicks} for row in rows], "limitations": ["Clicks are first-party event counts, not unique people, reach, or causal impact."]}


@router.get("/r/{code}", include_in_schema=False)
def redirect_tracking_link(code: str, request: Request, session: Session = Depends(get_db)) -> RedirectResponse:
    if not request_allowed(request):
        raise HTTPException(status_code=429, detail="Too many requests.")
    link = session.scalar(select(TrackingLink).where(TrackingLink.code == code, TrackingLink.is_active.is_(True)))
    if link is None or not is_allowed_destination(link.destination_url):
        raise HTTPException(status_code=404, detail="Tracking link not found.")
    referrer = request.headers.get("referer")
    referrer_domain = urlsplit(referrer).hostname if referrer else None
    session.add(TrackingEvent(tracking_link_id=link.id, event_type="click", referrer_domain=referrer_domain))
    session.commit()
    return RedirectResponse(destination_with_utm(link), status_code=status.HTTP_307_TEMPORARY_REDIRECT)
