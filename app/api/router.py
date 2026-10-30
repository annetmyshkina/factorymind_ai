from fastapi import APIRouter

from app.api.health import router as health_router
from app.equipment.router import router as equipment_router
from app.incidents.router import router as incidents_router
from app.monitoring.router import router as monitoring_router
from app.telemetry.router import router as telemetry_router

api_router = APIRouter()

api_router.include_router(health_router)
api_router.include_router(equipment_router)
api_router.include_router(telemetry_router)
api_router.include_router(monitoring_router)
api_router.include_router(incidents_router)
