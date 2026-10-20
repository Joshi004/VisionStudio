"""All routes live under `/api` (ITERATION_1_PHASES.md Section 4.3)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    character_lab,
    discovery,
    gpu,
    health,
    image_lab,
    jobs,
    projects,
    scenes,
    settings,
    story_bible,
    video_lab,
    voice_lab,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(projects.router, tags=["projects"])
api_router.include_router(story_bible.router, tags=["story-bible"])
api_router.include_router(discovery.router, tags=["discovery"])
api_router.include_router(scenes.router, tags=["scenes"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(gpu.router, tags=["gpu"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(image_lab.router, tags=["image-lab"])
api_router.include_router(video_lab.router, tags=["video-lab"])
api_router.include_router(voice_lab.router, tags=["voice-lab"])
api_router.include_router(character_lab.router, tags=["character-lab"])
