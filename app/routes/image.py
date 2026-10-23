import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import image_controls
from ..services import call_service


PROFILE = '^(keep|auto|balanced|low_light|motion|bright_day|close_faces|custom)$'
HOLD_SECONDS = 120   # After a manual test the automatic modes leave the picture alone for this long.


class Rule(BaseModel):
    start: int = Field(ge=0, le=23)
    end: int = Field(ge=0, le=23)
    profile: str = Field(pattern=PROFILE)


class ImageProfile(BaseModel):
    profile: str = Field(pattern=PROFILE)
    custom: dict[str, int] = Field(default_factory=dict)
    save: bool = False
    mode: str | None = Field(default=None, pattern='^(fixed|schedule|adaptive)$')
    schedule: list[Rule] | None = Field(default=None, max_length=8)
    ladder: list[str] | None = Field(default=None, min_length=2, max_length=5)


def build(config, cameras):
    """Picture profiles of a USB camera: list and read the current values, try a profile, or keep it."""
    router = APIRouter()

    def describe(camera_id):
        settings = call_service(config.for_camera, camera_id)
        device = image_controls.device_of(settings.camera_source)
        worker = cameras.get(camera_id)
        return {'supported': bool(device) and image_controls.available(), 'profile': settings.image_profile, 'custom': settings.image_custom,
                'mode': settings.image_mode, 'schedule': [r.model_dump() for r in settings.image_schedule], 'ladder': settings.image_ladder,
                'active': worker.image_active, 'luma': worker.image_luma and round(worker.image_luma),
                'profiles': [{'id': key, **{k: v for k, v in value.items() if k != 'controls'}} for key, value in image_controls.PROFILES.items()],
                'custom_keys': {key: image_controls.RANGES[key] for key in image_controls.CUSTOM_KEYS},
                'current': image_controls.read(settings.camera_source) if device else None}

    @router.get('/api/camera/image')
    async def image_state(camera_id: str = 'main'):
        return await run_in_threadpool(describe, camera_id)

    @router.post('/api/camera/image')
    async def image_apply(body: ImageProfile, camera_id: str = 'main'):
        """Apply a profile right now; with save=true it is also kept and reapplied whenever the camera opens."""
        settings = call_service(config.for_camera, camera_id)
        if not image_controls.device_of(settings.camera_source):
            raise HTTPException(409, 'Os ajustes de imagem só funcionam com uma câmera USB deste computador.')
        if not image_controls.available():
            raise HTTPException(503, 'O programa v4l2-ctl não está instalado neste computador.')
        controls = image_controls.controls_for(body.profile, body.custom)
        worker = cameras.get(camera_id)
        applied = await run_in_threadpool(image_controls.apply, settings.camera_source, controls)
        if body.save:
            changes = {'image_profile': body.profile, 'image_custom': image_controls.clean(body.custom)}
            if body.mode is not None:
                changes['image_mode'] = body.mode
            if body.schedule is not None:
                changes['image_schedule'] = [r.model_dump() for r in body.schedule]
            if body.ladder is not None:
                changes['image_ladder'] = body.ladder
            call_service(lambda: config.update_camera(camera_id, **changes))
            worker.image_hold, worker.image_active, worker.image_checked = 0.0, None, None   # The saved rule takes over at once.
        else:
            worker.image_hold = time.time() + HOLD_SECONDS
        return {'applied': applied, **await run_in_threadpool(describe, camera_id)}

    return router
