# Tenancy And Authorization Primitives

Business routers will use explicit organization paths. The organization is resolved from the active membership on every request; it is never read from a JWT claim.

```python
from fastapi import APIRouter, Depends

from app.api.organization_dependencies import CommercialRole, OrgContext, require_org_roles

router = APIRouter(prefix="/organizations/{organization_id}/campaigns")

@router.get("")
def list_campaigns(context: OrgContext = Depends(require_org_roles(
    CommercialRole.OWNER,
    CommercialRole.ADMIN,
    CommercialRole.EDITOR,
    CommercialRole.READER,
)):
    # Future tenant-owned queries must filter by context.organization.id.
    ...
```

Use `OWNER`, `ADMIN`, or `EDITOR` for create and update operations. Use `OWNER` or `ADMIN` for deletion. A resource lookup outside the selected organization must return `404`; missing, suspended, or inactive memberships return `403`.

The persisted `analyst` and `viewer` membership roles are compatibility roles. `commercial_role()` maps them to effective `EDITOR` and `READER` permissions without changing schema or data. A future migration may add persisted `editor` and `reader` values; until then, new memberships must use the existing database enum values.

Do not use `session.get()` by resource ID for tenant-owned data. Load every resource through the active organization scope, including lists, aggregates, child resources, dashboard queries, evaluation, tracking, and assistant context.

## Stage 2 Temporary Compatibility Debt

Campaign and Post CRUD routes are tenant-scoped under `/organizations/{organization_id}`. Until stage 3 scopes their dependent routers, two pre-existing global accesses remain intentionally unchanged: `snapshots.py` imports `posts.get_post_or_404`, and `experiments.py` validates `campaign_id` with `session.get(Campaign, ...)`. These are not authorized patterns for new code and do not make the backend fully tenant-isolated or production-ready.
