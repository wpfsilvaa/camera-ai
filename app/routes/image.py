from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import image_controls
from ..services import call_service


class ImageProfile(BaseModel):
    profile: str = Field(pattern='^(keep|auto|balanced|low_light|motion|bright_day|close_faces|custom)$')
    custom: dict[str, int] = Field(default_factory=dict)
    save: bool = False


def build(config):
    """Picture profiles of a USB camera: list and read the current values, try a profile, or keep it."""
    router = APIRouter()

    def describe(camera_id):
        settings = call_service(config.for_camera, camera_id)
        device = image_controls.device_of(settings.camera_source)
        return {'supported': bool(device) and image_controls.available(), 'profile': settings.image_profile, 'custom': settings.image_custom,
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
        applied = await run_in_threadpool(image_controls.apply, settings.camera_source, controls)
        if body.save:
            call_service(lambda: config.update_camera(camera_id, image_profile=body.profile, image_custom=image_controls.clean(body.custom)))
        return {'applied': applied, **await run_in_threadpool(describe, camera_id)}

    return router
