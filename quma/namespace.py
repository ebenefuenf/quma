from __future__ import annotations

import types
from functools import partial
from itertools import chain
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
)

from .script import (
    CursorScript,
    Script,
)

if TYPE_CHECKING:
    from .cursor import BaseCursor
    from .database import BaseDatabase


def get_namespace(self, attr):
    if attr in self.namespaces:
        return self.namespaces[attr]

    root = self.namespaces.get("__root__")
    while root:
        try:
            return getattr(root, attr)
        except AttributeError:
            root = root.shadow
    raise AttributeError


class Namespace:
    def __init__(
        self,
        db: BaseDatabase[Any],
        sqldir: Path,
        shadow: Namespace | None = None,
    ) -> None:
        self.db = db
        self.sqldir = sqldir
        self.cache = db.cache
        self.echo = db.echo
        self.shadow = shadow
        self._scripts: dict[str, Script] = {}
        if db.cache:
            self._collect_scripts(sqldir)

    def _collect_scripts(self, sqldir: Path) -> None:
        sqlfiles = chain(
            sqldir.glob(f"*.{self.db.file_ext}"),
            sqldir.glob(f"*.{self.db.tmpl_ext}"),
        )

        for sqlfile in sqlfiles:
            filename = Path(sqlfile.name)
            attr = filename.stem
            ext = filename.suffix

            if hasattr(type(self), attr) or attr in vars(self):
                # A real namespace member shadows this file. Not
                # hasattr(self): it finds scripts of shadowed directories.
                attr = "_" + attr
            if attr in self._scripts:
                # A .sql file wins over a template, as without the cache.
                continue

            with open(str(sqlfile)) as f:
                self._scripts[attr] = self.db.script_factory(
                    f.read(),
                    self.echo,
                    ext.lower() == "." + self.db.tmpl_ext,
                    self.db.sqldirs,
                    prepare_params=self.db.prepare_params,
                )

    def __getattr__(self, attr: str) -> Any:
        if self.cache:
            try:
                return self._scripts[attr]
            except KeyError:
                return getattr(self.shadow, attr)

        try:
            sqlfile = self.sqldir / ".".join((attr, self.db.file_ext))
            if not sqlfile.is_file():
                sqlfile = self.sqldir / ".".join((attr, self.db.tmpl_ext))
            with open(str(sqlfile)) as f:
                return self.db.script_factory(
                    f.read(),
                    self.echo,
                    Path(sqlfile).suffix == "." + self.db.tmpl_ext,
                    self.db.sqldirs,
                    prepare_params=self.db.prepare_params,
                )
        except FileNotFoundError:
            return getattr(self.shadow, attr)


class CursorNamespace:
    def __init__(self, namespace: Any, cursor: BaseCursor[Any]) -> None:
        self.namespace = namespace
        self.cursor = cursor

    def __getattr__(self, attr: str) -> Any:
        attr_obj = getattr(self.namespace, attr)
        if isinstance(attr_obj, Script):
            return CursorScript(attr_obj, self.cursor)
        if isinstance(attr_obj, types.MethodType):
            return partial(attr_obj, self.cursor)
        return attr_obj

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        # This should be a custom root method or a root level script.
        return self.namespace(self.cursor, *args, **kwargs)
