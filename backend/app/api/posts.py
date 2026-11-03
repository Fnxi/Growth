from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict
from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles
from app.api.scoped_loaders import get_post_for_org
from app.db.models import Post
from app.db.session import get_db
from app.schemas import PostCreate, PostRead, PostUpdate

router = APIRouter(prefix="/organizations/{organization_id}/posts", tags=["posts"])

READ_ROLES = tuple(CommercialRole)
WRITE_ROLES = (CommercialRole.OWNER, CommercialRole.ADMIN, CommercialRole.EDITOR)
DELETE_ROLES = (CommercialRole.OWNER, CommercialRole.ADMIN)


# Temporary stage-2 compatibility debt: snapshots.py still uses this global helper until stage 3 scopes snapshots.
def get_post_or_404(post_id: UUID, session: Session) -> Post:
    post = session.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Post not found.")
    return post


@router.post("", response_model=PostRead, status_code=status.HTTP_201_CREATED)
def create_post(
    payload: PostCreate,
    context: OrgContext = Depends(require_org_roles(*WRITE_ROLES)),
    session: Session = Depends(get_db),
) -> Post:
    data = payload.model_dump()
    data["canonical_url"] = str(data["canonical_url"])
    post = Post(**data, organization_id=context.organization.id)
    session.add(post)
    commit_or_conflict(session.commit)
    session.refresh(post)
    return post


@router.get("", response_model=list[PostRead])
def list_posts(
    context: OrgContext = Depends(require_org_roles(*READ_ROLES)),
    session: Session = Depends(get_db),
) -> list[Post]:
    return list(
        session.scalars(
            select(Post)
            .where(Post.organization_id == context.organization.id)
            .order_by(Post.created_at.desc())
        )
    )


@router.get("/{post_id}", response_model=PostRead)
def get_post(
    post_id: UUID,
    context: OrgContext = Depends(require_org_roles(*READ_ROLES)),
    session: Session = Depends(get_db),
) -> Post:
    return get_post_for_org(session, context.organization.id, post_id)


@router.patch("/{post_id}", response_model=PostRead)
def update_post(
    post_id: UUID,
    payload: PostUpdate,
    context: OrgContext = Depends(require_org_roles(*WRITE_ROLES)),
    session: Session = Depends(get_db),
) -> Post:
    post = get_post_for_org(session, context.organization.id, post_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(post, field, str(value) if field == "canonical_url" else value)
    commit_or_conflict(session.commit)
    session.refresh(post)
    return post


@router.delete("/{post_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_post(
    post_id: UUID,
    context: OrgContext = Depends(require_org_roles(*DELETE_ROLES)),
    session: Session = Depends(get_db),
) -> Response:
    session.delete(get_post_for_org(session, context.organization.id, post_id))
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
