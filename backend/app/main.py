import logging

from fastapi import FastAPI
from pydantic import BaseModel

from app.api import assistant, campaigns, dashboard, distribution_events, experiment_results, experiments, metric_definitions, operational_intelligence, posts, snapshots, system, tracking

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class HealthResponse(BaseModel):
    status: str


app = FastAPI(
    title="Growth Hacking Lab API",
    version="0.1.0",
    description="MVP de medicion externa para El Hilo MX.",
)

app.include_router(posts.router)
app.include_router(campaigns.router)
app.include_router(experiments.router)
app.include_router(metric_definitions.router)
app.include_router(snapshots.router)
app.include_router(distribution_events.router)
app.include_router(tracking.router)
app.include_router(dashboard.router)
app.include_router(experiment_results.router)
app.include_router(system.router)
app.include_router(assistant.router)
app.include_router(operational_intelligence.router)


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health_check() -> HealthResponse:
    """Liveness probe; database readiness is not part of phase 1."""
    return HealthResponse(status="ok")
