from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from ..auth import COOKIE, ROLES, SAME_SITE
from ..config import ROOT
from ..proxy import is_https
from ..services import call_service


class Credentials(BaseModel):
    username: str = Field(max_length=64)
    password: str = Field(max_length=128)
    remember: bool = False


class PasswordChange(BaseModel):
    current: str = Field(max_length=128)
    new: str = Field(max_length=128)


class NewUser(BaseModel):
    username: str = Field(max_length=32)
    name: str = Field(default='', max_length=60)
    password: str = Field(max_length=128)
    role: Literal[ROLES] = 'family'


class UserChanges(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    role: Literal[ROLES] | None = None
    password: str | None = Field(default=None, max_length=128)


def build(auth):
    """Login page, sessions and user management."""
    router = APIRouter()

    @router.get('/login')
    def login_page(request: Request):
        if not auth.enabled() or request.state.user:
            return RedirectResponse('/', status_code=303)
        return FileResponse(ROOT / 'static/login.html')

    @router.get('/api/auth/me')
    def auth_me(request: Request):
        return {'enabled': auth.enabled(), 'user': request.state.user}

    @router.post('/api/auth/login')
    async def auth_login(body: Credentials, request: Request):
        client = request.client.host if request.client else ''
        wait = auth.blocked_for(client)
        if wait:
            raise HTTPException(429, f'Muitas tentativas. Tente novamente em {max(1, wait // 60)} minuto(s).')
        token, lifetime = await run_in_threadpool(auth.login, client, body.username, body.password, body.remember)
        if not token:
            raise HTTPException(401, 'Usuário ou senha incorretos.')
        response = JSONResponse({'ok': True})
        response.set_cookie(COOKIE, token, max_age=lifetime if body.remember else None, httponly=True,
                            samesite=SAME_SITE, secure=is_https(request), path='/')
        return response

    @router.post('/api/auth/logout')
    def auth_logout(request: Request):
        auth.logout(request.cookies.get(COOKIE))
        response = JSONResponse({'ok': True})
        response.delete_cookie(COOKIE, path='/')
        return response

    @router.post('/api/auth/password')
    async def change_password(body: PasswordChange, request: Request):
        if not request.state.user:
            raise HTTPException(409, 'Crie um usuário antes de definir senhas.')
        await run_in_threadpool(call_service, auth.change_own_password, request.state.user['id'], body.current, body.new, request.cookies.get(COOKIE))
        return {'ok': True}

    @router.get('/api/users')
    def list_users():
        return auth.users()

    @router.post('/api/users', status_code=201)
    async def create_user(body: NewUser, request: Request):
        first = not auth.enabled()
        if first and body.role != 'admin':
            raise HTTPException(422, 'O primeiro usuário precisa ser administrador.')
        user_id = await run_in_threadpool(call_service, auth.create_user, body.username, body.name, body.password, body.role)
        return {'id': user_id, 'login_required': first}

    @router.patch('/api/users/{user_id}')
    async def update_user(user_id: str, body: UserChanges, request: Request):
        me = request.state.user
        await run_in_threadpool(call_service, auth.update_user, user_id, body.name, body.role, body.password,
                                request.cookies.get(COOKIE) if me and me['id'] == user_id else None)
        return {'ok': True}

    @router.delete('/api/users/{user_id}')
    def delete_user(user_id: str, request: Request):
        if request.state.user and request.state.user['id'] == user_id:
            raise HTTPException(409, 'Você não pode excluir o próprio usuário.')
        call_service(auth.delete_user, user_id)
        return {'ok': True}

    return router
