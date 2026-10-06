"""All routes live under `/api` (ITERATION_1_PHASES.md Section 4.3)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import gpu, health, jobs, projects, scenes, settings, transcription

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(projects.router, tags=["projects"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(gpu.router, tags=["gpu"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(transcription.router, tags=["transcription"])
api_router.include_router(scenes.router, tags=["scenes"])
