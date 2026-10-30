from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import (
    Annotated,
    Any,
)

import pytest

from .. import (
    AsyncCursor,
    AsyncDatabase,
    DoesNotExistError,
)
from . import util

pytest.importorskip("psycopg")

pytestmark = pytest.mark.postgres

POOL_URI = util.pg_uri("psycopg+pool")


def setup_function(function):
    util.setup_pg_db()


def database(sqldirs):
    return AsyncDatabase(
        POOL_URI, sqldirs, size=2, timeout=10, cache=True, contextcommit=True
    )


def check_app(client):
    response = client.get("/users/User 1")
    assert response.status_code == 200
    assert response.json()["email"] == "user.1@example.com"
    assert client.get("/users/Nobody").status_code == 404
    # The handler raises after the delete, so the block rolls back.
    assert client.post("/users/User 1/remove?fail=1").status_code == 409
    assert client.get("/users/User 1").status_code == 200
    assert client.post("/users/User 1/remove").status_code in (200, 201)
    assert client.get("/users/User 1").status_code == 404


def test_starlette(named_sqldirs):
    pytest.importorskip("starlette")
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from starlette.testclient import TestClient

    class Conflict(Exception):
        pass

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[dict[str, Any], None]:
        async with database(named_sqldirs) as db:
            yield {"db": db}

    async def get_user(request: Request) -> JSONResponse:
        async with request.state.db.cursor as cur:
            name = request.path_params["name"]
            user = await cur.users.by_name(name=name).one(dict)
        return JSONResponse(user)

    async def remove_user(request: Request) -> JSONResponse:
        async with request.state.db.cursor as cur:
            await cur.users.remove(name=request.path_params["name"]).run()
            if request.query_params.get("fail"):
                raise Conflict
        return JSONResponse({})

    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({}, status_code=404)

    async def conflict(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({}, status_code=409)

    app = Starlette(
        routes=[
            Route("/users/{name}", get_user),
            Route("/users/{name}/remove", remove_user, methods=["POST"]),
        ],
        lifespan=lifespan,
        exception_handlers={DoesNotExistError: not_found, Conflict: conflict},
    )
    with TestClient(app) as client:
        check_app(client)


def test_fastapi(named_sqldirs):
    pytest.importorskip("fastapi")
    from fastapi import (
        Depends,
        FastAPI,
        HTTPException,
        Request,
    )
    from fastapi.responses import JSONResponse
    from fastapi.testclient import TestClient

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        async with database(named_sqldirs) as db:
            app.state.db = db
            yield

    app = FastAPI(lifespan=lifespan)

    async def cursor(request: Request) -> AsyncGenerator[AsyncCursor, None]:
        async with request.app.state.db.cursor as cur:
            yield cur

    CursorDep = Annotated[AsyncCursor, Depends(cursor, scope="function")]

    @app.exception_handler(DoesNotExistError)
    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({}, status_code=404)

    @app.get("/users/{name}")
    async def get_user(name: str, cur: CursorDep) -> dict[str, Any]:
        return await cur.users.by_name(name=name).one(dict)

    @app.post("/users/{name}/remove")
    async def remove_user(
        name: str, cur: CursorDep, fail: bool = False
    ) -> dict[str, Any]:
        await cur.users.remove(name=name).run()
        if fail:
            raise HTTPException(status_code=409)
        return {}

    with TestClient(app) as client:
        check_app(client)


def test_litestar(named_sqldirs):
    pytest.importorskip("litestar")
    from litestar import (
        Litestar,
        Request,
        Response,
        get,
        post,
    )
    from litestar.datastructures import State
    from litestar.di import (
        NamedDependency,
        Provide,
    )
    from litestar.exceptions import HTTPException
    from litestar.params import (
        FromPath,
        FromQuery,
    )
    from litestar.testing import TestClient

    @asynccontextmanager
    async def db_lifespan(app: Litestar) -> AsyncGenerator[None, None]:
        async with database(named_sqldirs) as db:
            app.state.db = db
            yield

    async def provide_cursor(
        state: State,
    ) -> AsyncGenerator[AsyncCursor, None]:
        async with state.db.cursor as cur:
            yield cur

    def not_found(request: Request, exc: Exception) -> Response[Any]:
        return Response({}, status_code=404)

    @get("/users/{name:str}")
    async def get_user(
        name: FromPath[str], cur: NamedDependency[AsyncCursor]
    ) -> dict[str, Any]:
        return await cur.users.by_name(name=name).one(dict)

    @post("/users/{name:str}/remove")
    async def remove_user(
        name: FromPath[str],
        cur: NamedDependency[AsyncCursor],
        fail: FromQuery[bool] = False,
    ) -> dict[str, Any]:
        await cur.users.remove(name=name).run()
        if fail:
            raise HTTPException(status_code=409)
        return {}

    app = Litestar(
        [get_user, remove_user],
        lifespan=[db_lifespan],
        dependencies={"cur": Provide(provide_cursor)},
        exception_handlers={DoesNotExistError: not_found},
    )
    with TestClient(app) as client:
        check_app(client)
