from __future__ import annotations

import importlib.util
import os
import pkgutil
import threading
from collections.abc import (
    Callable,
    Sequence,
)
from importlib import import_module
from pathlib import Path
from types import ModuleType
from typing import (
    Any,
    Generic,
)
from urllib.parse import (
    ParseResult,
    urlparse,
)

from . import (
    exc,
    pool,
    provider,
)
from .conn import (
    ConnectionLike,
    ConnT,
    Row,
)
from .cursor import (
    CarriedConnection,
    Cursor,
)
from .namespace import (
    Namespace,
    get_namespace,
)
from .script import (
    PrepareParams,
    Script,
    SqlDirs,
    StrPath,
)


class Carrier:
    def __init__(self, heap: CarrierHeap, obj: object) -> None:
        self.obj = obj
        self.heap = heap
        self.oid = id(obj)
        self.conn: CarriedConnection[Any] | None = None

    def add_conn(self, conn: CarriedConnection[Any]) -> None:
        self.conn = conn

    def detach(self) -> CarriedConnection[Any] | None:
        return self.heap.pop(self.oid)

    def __getattr__(self, attr: str) -> Any:
        return getattr(self.obj, attr)


class CarrierHeap:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.heap: dict[int, Carrier] = {}

    def add(self, obj: object) -> Carrier:
        carrier = self.heap[id(obj)] = Carrier(self, obj)
        return carrier

    def get(self, obj: object) -> Carrier:
        with self.lock:
            try:
                carrier = self.heap[id(obj)]
            except KeyError:
                carrier = self.add(obj)
            return carrier

    def pop(self, oid: int) -> CarriedConnection[Any] | None:
        with self.lock:
            carrier = self.heap.pop(oid, None)
        return None if carrier is None else carrier.conn


class BaseCallWrapper:
    def __init__(
        self,
        database: BaseDatabase[Any],
        carrier: object | None,
        autocommit: bool,
    ) -> None:
        self.database = database
        if carrier is None:
            self.carrier = None
        else:
            self.carrier = database.heap.get(carrier)
        self.autocommit = autocommit


class DatabaseCallWrapper(BaseCallWrapper):
    @property
    def cursor(self) -> Cursor:
        return Cursor(
            self.database,
            self.database.namespaces,
            self.database.contextcommit,
            carrier=self.carrier,
            autocommit=self.autocommit,
        )


class BaseDatabase(Generic[ConnT]):
    conn: ConnT | None

    DoesNotExistError = exc.DoesNotExistError
    MultipleRowsError = exc.MultipleRowsError

    def __init__(
        self,
        sqldirs: SqlDirs,
        *,
        file_ext: str,
        tmpl_ext: str,
        script_factory: Callable[..., Script],
        prepare_params: PrepareParams | None,
        contextcommit: bool,
        echo: bool,
        cache: bool,
    ) -> None:
        if isinstance(sqldirs, os.PathLike):
            sqldirs = os.fspath(sqldirs)
        self.sqldirs = sqldirs
        self.file_ext = file_ext
        self.tmpl_ext = tmpl_ext
        self.script_factory = script_factory
        self.prepare_params = prepare_params
        self.contextcommit = contextcommit
        self.echo = echo
        self.cache = cache

        self.heap = CarrierHeap()
        self.namespaces: dict[str, Namespace] = {}

        if isinstance(sqldirs, str):
            self.register_namespace(sqldirs)
        else:
            for sqldir in sqldirs:
                self.register_namespace(sqldir)

    def register_namespace(self, sqldir: StrPath) -> None:
        def instantiate(ns, ns_class, path):
            if ns in self.namespaces:
                # pass the old namespace to the new instance
                shadow = self.namespaces[ns]
                self.namespaces[ns] = ns_class(self, path, shadow=shadow)
            else:
                self.namespaces[ns] = ns_class(self, path)

        def register(path, ns):
            ns_class = Namespace
            mod_path = path / "__init__.py"
            if mod_path.is_file():
                spec = importlib.util.spec_from_file_location(
                    f"quma.mapping.{ns}", mod_path
                )
                assert spec is not None and spec.loader is not None
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                if ns == "__root__":
                    class_name = "Root"
                else:
                    # snake_case to CamelCase
                    class_name = "".join([s.title() for s in ns.split("_")])
                ns_class = self._namespace_class(module, class_name)
                if hasattr(ns_class, "alias"):
                    instantiate(ns_class.alias, ns_class, path)
            instantiate(ns, ns_class, path)

        register(Path(sqldir), "__root__")
        for path in Path(sqldir).iterdir():
            if path.is_dir() and path.name != "__pycache__":
                register(path, path.name)

    def _namespace_class(
        self, module: ModuleType, class_name: str
    ) -> type[Namespace]:
        return getattr(module, class_name, Namespace)

    def __getattr__(self, attr: str) -> Any:
        try:
            return get_namespace(self, attr)
        except AttributeError as e:
            msg = f'Namespace or Root method "{attr}" not found.'
            raise AttributeError(msg) from e


class Database(BaseDatabase[ConnectionLike]):
    """
    The database object acts as the central object of the
    library.

    :param dburi: The connection string. See section "Connection Examples"
    :param sqldirs: One or more filesystem paths pointing to the sql scripts.
                    ``str`` or ``pathlib.Path``.
    :param persist: If ``True`` quma immediately opens a
        connection and keeps it open throughout the complete application
        runtime. Setting it to ``True`` will raise an error if you try to
        initialize a connection pool. Defaults to ``False``.
    :param pessimistic: If ``True`` quma emits a test statement on
        a persistent SQL connection every time it is accessed or at the start
        of each connection pool checkout (see section "Connection Pool"), to
        test that the database connection is still viable. Defaults to
        ``False``.
    :param contextcommit: If ``True`` and a context manager is used quma will
        automatically commit all changes when the context manager exits,
        or roll them back if it exits with an exception. Defaults to
        ``False``.
    :param prepare_params: A callback function which will be called before
        every query to prepare the params which will be passed to the query.
        Defaults to None.
    :param file_ext: The file extension of sql files. Defaults to '``sql'``.
    :param tmpl_ext: The file extension of template files (see
        :doc:`Templates <templates>`). Defaults to ``'msql'``.
    :param echo: Print the executed query to stdout if ``True``. Defaults to
        ``False``. *PostgreSQL* and *MySQL/MariaDB* connections will print the
        query after argument binding. This means placeholders will be
        substituted with the parameter values. *SQLite* will always print the
        query without substitutions.
    :param cache: cache the scripts in memory if ``True``,
        otherwise re-read each script when the query is executed.
        Defaults to ``False``.

    Additional connection pool parameters (see :doc:`Connection pool <pool>`):

    :param size: The size of the pool to be maintained. This is the
        largest number of connections that will be kept persistently in the
        pool. The pool begins with no connections. Defaults to 5.
    :param overflow: The maximum overflow size of the pool. When
        the number of checked-out connections reaches the size set in `size`,
        additional connections will be returned up to this limit. Set to -1
        to indicate no overflow limit. Defaults to 10.
    :param timeout: The number of seconds to wait before giving
        up on returning a connection. Defaults to None.
    """

    def __init__(
        self,
        dburi: str,
        sqldirs: SqlDirs = (),
        *args: Any,
        file_ext: str = "sql",
        tmpl_ext: str = "msql",
        script_factory: Callable[..., Script] = Script,
        prepare_params: PrepareParams | None = None,
        contextcommit: bool = False,
        echo: bool = False,
        cache: bool = False,
        **kwargs: Any,
    ) -> None:
        if args:
            raise ValueError("Max number of arguments is two")
        # The remaining kwargs are passed to the DBAPI connect call
        self.conn = connect(dburi, **kwargs)
        super().__init__(
            sqldirs,
            file_ext=file_ext,
            tmpl_ext=tmpl_ext,
            script_factory=script_factory,
            prepare_params=prepare_params,
            contextcommit=contextcommit,
            echo=echo,
            cache=cache,
        )

    def __call__(
        self, carrier: object | None = None, autocommit: bool = False
    ) -> DatabaseCallWrapper:
        return DatabaseCallWrapper(
            self, carrier=carrier, autocommit=autocommit
        )

    def execute(self, query: str, **kwargs: Any) -> Sequence[Row] | None:
        """Execute the statements in ``query`` and commit
        immediately.

        :param query: The sql query to execute.
        """
        result = None
        cur = self.cursor()
        try:
            cur.execute(query, **kwargs)
            cur.commit()
            if cur.description:
                result = cur.fetchall()
        except Exception as e:
            cur.rollback()
            raise e
        finally:
            cur.close()
        return result

    def close(self) -> None:
        """Close (all) open connections. If you want to reconnect you
        need to create a new :class:`quma.Database` instance.

        Calling it again, or on a database without persistent or pooled
        connections, does nothing.
        """
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def release(self, carrier: object) -> None:
        """If the ``carrier`` holds a connection close it or return
        it to the pool.

        :param carrier: An object holding a quma connection. See
            :doc:`Reusing connections <carrier>`
        """
        carried = self.heap.pop(id(carrier))
        if carried is not None:
            carried.conn.put(carried.raw_conn)

    @property
    def cursor(self) -> Cursor:
        """Open a connection and return a cursor."""
        return Cursor(self, self.namespaces, self.contextcommit)


def connect(dburi: str, **kwargs: Any) -> ConnectionLike:
    """
    Create and return a Connection or Pool object specified
    via ``dburi`` (a string in the form of an URL)
    """
    module, url, pooled = resolve(dburi)
    if pooled:
        return pool.Pool(module.Connection, url, **kwargs)
    return module.Connection(url, **kwargs)


def resolve(dburi: str) -> tuple[ModuleType, ParseResult, bool]:
    """Return the provider module for ``dburi``, the parsed URL and
    whether the URL asks for a pool."""
    url = urlparse(dburi)
    module_name, *options = url.scheme.split("+")
    drivers = sorted(m.name for m in pkgutil.iter_modules(provider.__path__))
    if module_name not in drivers:
        schemes = ", ".join(f"{driver}://" for driver in drivers)
        raise ValueError(
            f'Unknown driver "{module_name}". Use one of: {schemes}'
        )
    module = import_module(f"quma.provider.{module_name}")
    if options and options[0].lower() != "pool":
        raise ValueError(
            'Wrong scheme. Only "provider://" or '
            '"provider+pool://" are allowed'
        )
    return module, url, bool(options)
