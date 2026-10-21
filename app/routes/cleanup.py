from fastapi import APIRouter
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..services import call_service


class Samples(BaseModel):
    sample_ids: list[str] = Field(min_length=1, max_length=300)


def build(cleanup):
    """Smart clean-up of the taught faces: analysis only when asked, quarantine instead of deletion."""
    router = APIRouter()

    @router.get('/api/cleanup/analyze')
    async def analyze():
        return await run_in_threadpool(cleanup.analyze)

    @router.post('/api/cleanup/apply')
    def apply(body: Samples):
        return {'moved': call_service(cleanup.apply, body.sample_ids)}

    @router.get('/api/cleanup/quarantine')
    def quarantine():
        return cleanup.quarantined()

    @router.post('/api/cleanup/restore')
    def restore(body: Samples):
        return {'restored': call_service(cleanup.restore, body.sample_ids)}

    return router
