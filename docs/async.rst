=====
Async
=====

quma has an async API for asyncio applications, for example with
`Starlette <https://www.starlette.io>`_, `FastAPI <https://fastapi.tiangolo.com>`_
or `Litestar <https://litestar.dev>`_. It works with psycopg 3
(``psycopg://`` and ``psycopg+pool://``); psycopg2, mysqlclient and
sqlite3 have no asyncio support.

Every call that talks to the database is awaited. Everything else works
as in sync code: SQL directories, namespaces, templates, parameters,
changeling rows, :doc:`mapping <mapping>` and :doc:`carriers <carrier>`.

.. code-block:: python

    from quma import AsyncDatabase

    db = AsyncDatabase('psycopg+pool://user:secret@localhost/app', sqldir,
                       size=10, timeout=10, cache=True)

    async def rename_user(user_id, name):
        async with db.cursor as cur:
            await cur.users.rename(id=user_id, name=name).run()
            user = await cur.users.by_id(id=user_id).one()
            await cur.commit()
        return user


Sync and async side by side
---------------------------

.. list-table::
   :header-rows: 1

   * - Sync
     - Async
   * - ``db = Database(url, sqldir)``
     - ``db = AsyncDatabase(url, sqldir)``, no I/O yet
   * - ``with db.cursor as cur:``
     - ``async with db.cursor as cur:``
   * - ``with db.cursor(autocommit=True) as cur:``
     - ``async with db.cursor(autocommit=True) as cur:``
   * - ``cur = db.cursor()`` … ``cur.close()``
     - ``cur = await db.cursor()`` … ``await cur.close()``
   * - ``with db(request).cursor as cur:``
     - ``async with db(request).cursor as cur:``
   * - ``cur.users.by_id(id=1).one(User)``
     - ``await cur.users.by_id(id=1).one(User)``
   * - ``db.users.by_id(cur, id=1).one()``
     - ``await db.users.by_id(cur, id=1).one()``
   * - ``for row in cur.users.all():``
     - ``async for row in cur.users.all():``
   * - ``len(q)``, ``bool(q)``, ``q[0]``
     - ``await q.count()``, ``await q.exists()``, ``await q.first()``
   * - ``cur.users.rename(id=1, name=n).run()``
     - ``await cur.users.rename(id=1, name=n).run()``
   * - ``cur.commit()``, ``cur.rollback()``
     - ``await cur.commit()``, ``await cur.rollback()``
   * - ``db.execute(sql)``, ``db.release(request)``
     - ``await db.execute(sql)``, ``await db.release(request)``
   * - ``db.close()``
     - ``await db.close()``, or ``async with AsyncDatabase(...) as db:``


Opening and closing
-------------------

Creating an :class:`AsyncDatabase` does no I/O, a constructor can't
await. Connections open on first use, even with ``persist=True``.

* ``await db.open()`` connects right away: it opens the persistent
  connection, or opens one connection and returns it to the pool. Wrong
  credentials then fail at startup instead of on the first request.
* ``await db.close()`` closes the persistent connection or the idle
  pooled ones. Calling it again does nothing.
* ``async with AsyncDatabase(...) as db:`` opens and closes.

Create the database in your application's lifespan, see below. asyncio
locks and connections belong to the event loop that first uses them, so
a database shared by several event loops (as in test suites that run each
test in a new loop) fails with "attached to a different loop".

The pool takes the options of the sync :doc:`pool <pool>`: ``size``,
``overflow``, ``timeout`` and ``pessimistic``. A task waiting for a free
connection awaits instead of blocking a thread. Set ``timeout`` in web
applications, so an exhausted pool fails requests with
:class:`quma.TimeoutError` instead of letting them wait forever.

With ``persist=True`` all tasks share one connection and their
transactions interleave. Use it for scripts and workers, not for web
applications.

Set ``cache=True`` in production: without it, quma reads each SQL file
from disk when it's used, which blocks the event loop briefly.


Cursors and transactions
------------------------

``db.cursor`` returns a new cursor and ``async with`` opens it. Calling
``db.cursor(autocommit=True)`` only records the flag, because a call
can't await; the ``async with`` or an ``await`` opens the cursor. To use
a cursor without a block, await it and close it yourself:

.. code-block:: python

    cur = await db.cursor()
    try:
        await cur.users.remove(id=13).run()
        await cur.commit()
    finally:
        await cur.close()

With ``contextcommit=True`` the cursor commits when the ``async with``
block ends, and rolls back if the block raises.

**One task per cursor.** A cursor holds one DB-API cursor, and two tasks
using it at the same time would read each other's results. quma raises
:class:`quma.APIError` instead ("cursor is busy"). Run queries in
parallel with one cursor per task; each gets its own connection:

.. code-block:: python

    async def count(city):
        async with db.cursor as cur:
            return await cur.users.by_city(city=city).count()

    counts = await asyncio.gather(count('Berlin'), count('Hamburg'))


Queries
-------

:class:`AsyncQuery` has the methods of :doc:`Query <query>` with the same
arguments and errors, awaited: ``all()``, ``one()``, ``first()``,
``value()``, ``exists()``, ``count()``, ``run()`` and ``many().get()``.
Iterate with ``async for``:

.. code-block:: python

    async for user in cur.users.all():
        print(user.name)

    async for user in cur.users.all().unbunch(100, User):
        print(user.name)

Python can't await inside ``len()``, ``bool()``, indexing or a ``for``
loop, so an async query raises :class:`TypeError` there and names the
method to use instead. Without that, ``if query:`` would always be true.


Custom namespaces
-----------------

Methods of :doc:`custom namespaces <namespaces>` that query the database
are ``async def`` and await the queries:

.. code-block:: python

    from quma import AsyncCursor, Namespace

    class Users(Namespace):
        async def by_username(self, cur: AsyncCursor, username):
            return await cur.users.by_name(name=username).one()

A SQL directory used by both a :class:`Database` and an
:class:`AsyncDatabase` can hold a sync and an async class:
:class:`AsyncDatabase` uses ``AsyncUsers`` if the module has one, and
``Users`` otherwise (``AsyncRoot`` and ``Root`` for the root directory).


Cancellation
------------

A task can be cancelled at any ``await``, for example by
``asyncio.timeout()`` or when a server shuts down. psycopg then cancels
the running query on the server. quma returns the connection to the
pool, or discards it if its state is unknown, so a cancelled task never
loses a pool slot.


Frameworks
----------

Open the database in the application's lifespan and open one cursor per
request, in the handler or in a dependency.

Starlette
~~~~~~~~~

The lifespan yields its state, which handlers read from
``request.state``.

.. code-block:: python

    from collections.abc import AsyncGenerator
    from contextlib import asynccontextmanager

    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    from quma import AsyncDatabase, DoesNotExistError


    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncGenerator[dict, None]:
        async with AsyncDatabase(DB_URL, 'sql', size=10, timeout=10,
                                 cache=True) as db:
            yield {'db': db}


    async def get_user(request: Request) -> JSONResponse:
        async with request.state.db.cursor as cur:
            user = await cur.users.by_id(
                id=request.path_params['user_id']).one(dict)
        return JSONResponse(user)


    async def not_found(request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse({}, status_code=404)


    app = Starlette(
        routes=[Route('/users/{user_id:int}', get_user)],
        lifespan=lifespan,
        exception_handlers={DoesNotExistError: not_found},
    )

FastAPI
~~~~~~~

Give the dependency ``scope="function"`` (FastAPI 0.121 and later). Then
the cursor closes, and commits with ``contextcommit``, before the response
is sent. With the default ``"request"`` scope that happens after the
response was sent: a failed commit can no longer change it, and the
connection stays checked out while the response is sent.

.. code-block:: python

    from collections.abc import AsyncGenerator
    from contextlib import asynccontextmanager
    from typing import Annotated

    from fastapi import Depends, FastAPI, Request

    from quma import AsyncCursor, AsyncDatabase


    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        async with AsyncDatabase(DB_URL, 'sql', size=10, timeout=10,
                                 cache=True) as db:
            app.state.db = db
            yield


    app = FastAPI(lifespan=lifespan)


    async def cursor(request: Request) -> AsyncGenerator[AsyncCursor, None]:
        async with request.app.state.db.cursor as cur:
            yield cur


    CursorDep = Annotated[AsyncCursor, Depends(cursor, scope='function')]


    @app.get('/users/{user_id}')
    async def get_user(user_id: int, cur: CursorDep) -> User:
        return await cur.users.by_id(id=user_id).one(User)

Litestar
~~~~~~~~

Litestar runs the cleanup of a generator dependency after the handler
returns and before the response is sent, and throws the handler's
exception into it.

.. code-block:: python

    from collections.abc import AsyncGenerator
    from contextlib import asynccontextmanager

    from litestar import Litestar, get
    from litestar.datastructures import State
    from litestar.di import NamedDependency, Provide
    from litestar.params import FromPath

    from quma import AsyncCursor, AsyncDatabase


    @asynccontextmanager
    async def db_lifespan(app: Litestar) -> AsyncGenerator[None, None]:
        async with AsyncDatabase(DB_URL, 'sql', size=10, timeout=10,
                                 cache=True) as db:
            app.state.db = db
            yield


    async def provide_cursor(state: State) -> AsyncGenerator[AsyncCursor, None]:
        async with state.db.cursor as cur:
            yield cur


    @get('/users/{user_id:int}')
    async def get_user(user_id: FromPath[int],
                       cur: NamedDependency[AsyncCursor]) -> User:
        return await cur.users.by_id(id=user_id).one(User)


    app = Litestar(
        [get_user],
        lifespan=[db_lifespan],
        dependencies={'cur': Provide(provide_cursor)},
    )

In every framework, an exception handler that maps
:class:`quma.DoesNotExistError` to a 404 response saves a ``try`` in each
handler.


Sync and async in one application
---------------------------------

An application that needs both creates a :class:`Database` and an
:class:`AsyncDatabase` from the same URL and SQL directories. psycopg 3
serves both.

* Each database has its own pool, and their sizes add up against
  PostgreSQL's ``max_connections``.
* A sync and an async cursor never share a connection or a transaction.
* Use the sync database only where code runs in a thread: ``def``
  endpoints in Starlette and FastAPI run in a thread pool, Litestar runs
  sync handlers in one with ``sync_to_thread=True``. Calling it from
  ``async def`` blocks the event loop and every request on it.
  Async code that must call sync code uses
  ``await anyio.to_thread.run_sync(...)``.
* Request handlers should use the async database. The sync one fits CLI
  commands, migrations and sync workers.


API
---

.. autoclass:: quma.AsyncDatabase
    :members:

.. autoclass:: quma.aio.AsyncQuery
    :members:

.. autoclass:: quma.aio.AsyncManyResult
    :members:
