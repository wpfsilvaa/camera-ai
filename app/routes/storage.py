from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..services import call_service


class Cleanup(BaseModel):
    what: Literal['videos', 'history']
    older_than_days: int = Field(ge=0, le=3650)


def build(storage):
    """Disk usage and the "free space" buttons."""
    router = APIRouter()

    @router.get('/api/storage')
    async def usage(older_than_days: int = Query(7, ge=0, le=3650)):
        return {**await run_in_threadpool(storage.usage),
                'preview': await run_in_threadpool(call_service, storage.preview, older_than_days)}

    @router.post('/api/storage/clean')
    async def clean(body: Cleanup):
        action = storage.delete_videos if body.what == 'videos' else storage.delete_history
        return await run_in_threadpool(call_service, action, body.older_than_days)

    return router
