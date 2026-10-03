from fastapi import APIRouter
from starlette.concurrency import run_in_threadpool

from ..services import call_service


def build(backups):
    """Backup status and the "back up now" button."""
    router = APIRouter()

    @router.get('/api/backup')
    def backup_status():
        return backups.summary()

    @router.post('/api/backup/run', status_code=201)
    async def backup_now():
        path = await run_in_threadpool(call_service, backups.run)
        return {'file': path.name}

    return router
