import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from ..photos import MAX_BYTES
from ..services import call_service


def build(photos):
    """Upload, list and remove the photos of the kitchen screen's photo frame."""
    router = APIRouter()

    def view(row, user):
        return {'id': row['id'], 'author': row['author'], 'created': row['created'],
                'mine': bool(user) and (user['role'] == 'admin' or user['id'] == row['user_id'])}

    @router.get('/api/photos')
    def list_photos(request: Request):
        return {'photos': [view(r, request.state.user) for r in photos.list()]}

    @router.post('/api/photos')
    async def upload(request: Request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_BYTES:
                raise HTTPException(413, 'A foto deve ter até 12 MB.')
        user = request.state.user
        try:
            await run_in_threadpool(call_service, photos.add, user['name'] if user else 'Casa', user['id'] if user else None, bytes(content))
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(422, 'Envie uma foto JPEG ou PNG válida.')
        return {'photos': [view(r, user) for r in photos.list()]}

    @router.delete('/api/photos/{photo_id}')
    def remove(photo_id: str, request: Request):
        user = request.state.user
        try:
            photos.delete(photo_id, user['id'] if user else None, not user or user['role'] == 'admin')
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except KeyError as exc:
            raise HTTPException(404, str(exc))
        return {'ok': True}

    @router.get('/photos-media/{filename}')
    def media(filename: str):
        match = re.fullmatch(r'([a-f0-9]{32})(\.thumb)?\.jpg', filename)
        if not match or not photos.path(match[1], bool(match[2])).is_file():
            raise HTTPException(404)
        return FileResponse(photos.path(match[1], bool(match[2])), media_type='image/jpeg', headers={'Cache-Control': 'private, max-age=86400'})

    return router
