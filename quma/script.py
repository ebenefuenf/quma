from __future__ import annotations

import os
import sys
from collections.abc import (
    Callable,
    Sequence,
)
from typing import (
    TYPE_CHECKING,
    Any,
)

from .conn import Params
from .query import Query

if TYPE_CHECKING:
    from .cursor import Cursor

try:
    from mako.lookup import TemplateLookup
    from mako.template import Template
except ImportError:
    TemplateLookup = Template = None

StrPath = str | os.PathLike[str]
SqlDirs = StrPath | Sequence[StrPath]
# Called with the carrier (or None) and empty params, returns the params.
PrepareParams = Callable[[Any, Params], Params]


class Script:
    def __init__(
        self,
        content: str,
        echo: bool,
        is_template: bool,
        sqldirs: SqlDirs,
        prepare_params: PrepareParams | None = None,
    ) -> None:
        self.echo = echo
        self.content = content
        self.prepare_params = prepare_params
        self.is_template = is_template
        self.sqldirs = sqldirs
        self.params = None

    def __call__(
        self,
        cursor: Cursor,
        *args: Any,
        prepare_params: PrepareParams | None = None,
        **kwargs: Any,
    ) -> Query:
        return Query(self, cursor, args, kwargs, prepare_params)

    def __str__(self) -> str:
        return self.content

    def mogrify(self, cursor, content, params):
        if content:
            sys.stdout.write("-" * 50)
            sys.stdout.write("\n")
            sys.stdout.write(cursor.mogrify(content, params))

    def _prepare(self, cursor, payload, prepare_params):
        # create an empty list if payload == args
        # create an empty dict if payload == kwargs
        params = type(payload)()

        init = prepare_params or self.prepare_params
        if init:
            params = init(cursor.carrier, params)

        if isinstance(params, list):
            params.extend(payload)
        else:
            params.update(payload)

        if self.is_template:
            if Template is None or TemplateLookup is None:
                raise ImportError("To use templates you need to install Mako")
            if isinstance(params, list):
                raise TypeError("Templates need keyword parameters")
            lookup = TemplateLookup(directories=self.sqldirs)
            return (
                Template(self.content, lookup=lookup).render(**params),
                params,
            )
        return self.content, params

    def execute(self, cursor, args, kwargs, prepare_params=None):
        if args:
            content, params = self._prepare(cursor, args, prepare_params)
        else:
            content, params = self._prepare(cursor, kwargs, prepare_params)
        try:
            cursor.execute(content, params)
        finally:
            self.echo and self.mogrify(cursor, content, params)


class CursorScript:
    def __init__(self, script: Script, cursor: Cursor) -> None:
        self.script = script
        self.cursor = cursor

    def __call__(self, *args: Any, **kwargs: Any) -> Query:
        return self.script(self.cursor, *args, **kwargs)

    def __str__(self) -> str:
        return self.script.content
