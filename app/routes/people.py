import io
import re
from typing import Literal

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from PIL import Image
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..config import PEOPLE
from ..services import call_service

MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_PHOTO_PIXELS = 16_000_000


class PersonName(BaseModel):
    name: str = Field(min_length=1, max_length=60)


class PersonBirthday(BaseModel):
    birthday: str | None = Field(default=None, max_length=10)


class PersonConfirmation(BaseModel):
    person_id: str | None = None
    sample_id: str | None = None


def decode_photo(content):
    """Validate an uploaded JPEG/PNG before handing it to OpenCV."""
    with Image.open(io.BytesIO(content)) as photo:
        if photo.width * photo.height > MAX_PHOTO_PIXELS:
            raise ValueError('Imagem muito grande.')
        photo.verify()
    image = cv2.imdecode(np.frombuffer(content, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError('Imagem inválida.')
    return image


def build(recognition, learning):
    """People profiles, face enrollment, identity confirmation and suggested examples."""
    router = APIRouter()

    @router.get('/api/learning')
    def learning_suggestions():
        return learning.pending()

    @router.post('/api/learning/{sample_id}/{decision}')
    def decide_suggestion(sample_id: str, decision: Literal['approve', 'reject', 'discard']):
        if decision == 'discard':
            call_service(learning.discard, sample_id)   # Deletes the photo: it was too poor to learn from.
        else:
            call_service(learning.decide, sample_id, decision == 'approve')
        return {'ok': True}

    @router.get('/api/people')
    def people():
        return recognition.status()

    @router.post('/api/people')
    def create_person(body: PersonName):
        name = body.name.strip()
        if not name:
            raise HTTPException(422, 'Informe um nome.')
        return {'id': call_service(recognition.create_person, name)}

    @router.patch('/api/people/{person_id}')
    def rename_person(person_id: str, body: PersonName):
        if not body.name.strip():
            raise HTTPException(422, 'Informe um nome.')
        call_service(recognition.rename_person, person_id, body.name.strip())
        return {'ok': True}

    @router.put('/api/people/{person_id}/birthday')
    def set_birthday(person_id: str, body: PersonBirthday):
        call_service(recognition.set_birthday, person_id, body.birthday or None)
        return {'ok': True}

    @router.delete('/api/people/{person_id}')
    def delete_person(person_id: str):
        call_service(recognition.forget, person_id, True)
        return {'ok': True}

    @router.post('/api/people/{person_id}/forget')
    def forget_person(person_id: str):
        call_service(recognition.forget, person_id)
        return {'ok': True}

    @router.get('/api/people/{person_id}/examples')
    def person_examples(person_id: str):
        return call_service(recognition.examples, person_id)

    @router.delete('/api/people/{person_id}/examples/{source}/{sample_id}')
    def remove_person_example(person_id: str, source: Literal['history', 'upload'], sample_id: str):
        call_service(recognition.remove_example, person_id, source, sample_id)
        return {'ok': True}

    @router.post('/api/people/{person_id}/faces')
    async def enroll_face(person_id: str, request: Request):
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_PHOTO_BYTES:
                raise HTTPException(413, 'A foto deve ter até 8 MB.')
        try:
            image = decode_photo(bytes(content))
        except Exception:
            raise HTTPException(422, 'Envie uma foto JPEG ou PNG válida, com até 16 megapixels.')
        sample_id = await run_in_threadpool(call_service, recognition.enroll, person_id, image)
        return {'id': sample_id}

    @router.delete('/api/people/{person_id}/faces/{sample_id}')
    def delete_face(person_id: str, sample_id: str):
        call_service(recognition.remove_enrollment, person_id, sample_id)
        return {'ok': True}

    @router.patch('/api/person-tracks/{track_id}')
    def confirm_person(track_id: int, body: PersonConfirmation):
        call_service(recognition.confirm, track_id, body.person_id, body.sample_id)
        return {'ok': True}

    @router.get('/people-media/{filename}')
    def person_media(filename: str):
        if not re.fullmatch(r'[a-f0-9]{32}\.jpg', filename) or not (PEOPLE / filename).is_file():
            raise HTTPException(404)
        return FileResponse(PEOPLE / filename, media_type='image/jpeg')

    return router
