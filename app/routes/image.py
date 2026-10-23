import threading
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .. import focus, image_controls
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
    values: dict[str, int] | None = None   # The sliders of the profile being edited.
    save: bool = False
    mode: str | None = Field(default=None, pattern='^(fixed|schedule|adaptive)$')
    schedule: list[Rule] | None = Field(default=None, max_length=8)
    ladder: list[str] | None = Field(default=None, min_length=2, max_length=5)


def build(config, cameras):
    """Picture profiles of a USB camera: list and read the current values, try a profile, or keep it."""
    router = APIRouter()
    runs = {}   # camera id -> state of the focus sweep (running, progress, result)

    def describe(camera_id):
        settings = call_service(config.for_camera, camera_id)
        device = image_controls.device_of(settings.camera_source)
        worker = cameras.get(camera_id)
        return {'supported': bool(device) and image_controls.available(), 'profile': settings.image_profile, 'custom': settings.image_custom,
                'presets': settings.image_presets, 'base': {key: image_controls.PROFILES[key]['controls'] for key in image_controls.EDITABLE if key != 'custom'},
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
        custom, presets = dict(body.custom), dict(settings.image_presets)
        if body.values is not None:
            if body.profile == 'custom':
                custom = body.values
            elif body.profile in image_controls.EDITABLE:
                tuned = image_controls.fine_tuning(body.profile, body.values)
                presets = {**{k: v for k, v in presets.items() if k != body.profile}, **({body.profile: tuned} if tuned else {})}
        controls = image_controls.controls_for(body.profile, custom, presets)
        worker = cameras.get(camera_id)
        applied = await run_in_threadpool(image_controls.apply, settings.camera_source, controls)
        if body.save:
            changes = {'image_profile': body.profile, 'image_custom': image_controls.clean(custom), 'image_presets': presets}
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

    def sweep(camera_id, source, worker):
        run = runs[camera_id]
        try:
            before = (image_controls.read(source) or {}).get('focus_absolute')
            image_controls.apply(source, {'focus_automatic_continuous': 0})
            worker.image_hold = time.time() + 300

            def set_focus(position):
                image_controls.apply(source, {'focus_absolute': position})

            def read(window):
                worker.focus_probe_until = time.time() + window + 3
                begin = time.time()
                time.sleep(window)
                return [score for stamp, score in list(worker.focus_scores or []) if stamp >= begin]

            def progress(done, total):
                run['done'], run['total'] = done, total
            result = focus.Sweep(set_focus, read, progress=progress).run()
            keep = result['best'] if result['clear'] else before   # No clear peak: put the focus back where it was.
            if keep is not None:
                set_focus(keep)
            run['result'] = {**result, 'applied': keep, 'before': before, 'region': worker.focus_region}
        except Exception as exc:   # The camera or v4l2-ctl failed: report it, do not leave the sweep hanging.
            run['result'] = {'error': str(exc) or type(exc).__name__}
        finally:
            run['running'] = False
            worker.image_hold = time.time() + 120

    @router.get('/api/camera/focus')
    def focus_state(camera_id: str = 'main'):
        """Live sharpness of the picture (asking for it switches the measurement on for a few seconds) and the state of the sweep."""
        settings = call_service(config.for_camera, camera_id)
        worker = cameras.get(camera_id)
        worker.focus_probe_until = time.time() + 4
        recent = [score for stamp, score in list(worker.focus_scores or []) if stamp >= time.time() - .8]
        run = runs.get(camera_id) or {}
        return {'supported': bool(image_controls.device_of(settings.camera_source)) and image_controls.available(),
                'score': round(sorted(recent)[len(recent) // 2]) if recent else None, 'region': worker.focus_region,
                'calibrating': bool(run.get('running')), 'progress': [run.get('done', 0), run.get('total', 1)], 'result': run.get('result')}

    @router.post('/api/camera/focus/calibrate', status_code=202)
    def focus_calibrate(camera_id: str = 'main'):
        settings = call_service(config.for_camera, camera_id)
        if not image_controls.device_of(settings.camera_source) or not image_controls.available():
            raise HTTPException(409, 'A calibração de foco só funciona com uma câmera USB deste computador.')
        worker = cameras.get(camera_id)
        if worker.snapshot()['state'] != 'online':
            raise HTTPException(409, 'Inicie a câmera antes de calibrar o foco.')
        if runs.get(camera_id, {}).get('running'):
            raise HTTPException(409, 'A calibração já está em andamento.')
        runs[camera_id] = {'running': True, 'done': 0, 'total': 1, 'result': None}
        threading.Thread(target=sweep, args=(camera_id, settings.camera_source, worker), daemon=True, name='focus-sweep').start()
        return {'started': True}

    return router
