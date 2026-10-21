"""All routes live under `/api` (ITERATION_1_PHASES.md Section 4.3)."""

from __future__ import annotations

from fastapi import APIRouter

from app.api import (
    character_definitions,
    character_images,
    character_lab,
    character_links,
    character_relations,
    discovery,
    environment_definitions,
    environment_lab,
    environment_links,
    gpu,
    health,
    image_lab,
    jobs,
    projects,
    scene_definitions,
    scenes,
    settings,
    story_bible,
    story_voices,
    video_lab,
    voice_lab,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(projects.router, tags=["projects"])
api_router.include_router(story_bible.router, tags=["story-bible"])
api_router.include_router(discovery.router, tags=["discovery"])
api_router.include_router(scenes.router, tags=["scenes"])
api_router.include_router(character_links.router, tags=["character-links"])
api_router.include_router(character_relations.router, tags=["character-relations"])
api_router.include_router(character_definitions.router, tags=["character-definitions"])
api_router.include_router(character_images.router, tags=["character-images"])
api_router.include_router(story_voices.router, tags=["story-voices"])
api_router.include_router(settings.router, tags=["settings"])
api_router.include_router(gpu.router, tags=["gpu"])
api_router.include_router(jobs.router, tags=["jobs"])
api_router.include_router(image_lab.router, tags=["image-lab"])
api_router.include_router(video_lab.router, tags=["video-lab"])
api_router.include_router(voice_lab.router, tags=["voice-lab"])
api_router.include_router(character_lab.router, tags=["character-lab"])
api_router.include_router(environment_lab.router, tags=["environment-lab"])
api_router.include_router(environment_links.router, tags=["environment-links"])
api_router.include_router(environment_definitions.router, tags=["environment-definitions"])
api_router.include_router(scene_definitions.router, tags=["scene-definitions"])
