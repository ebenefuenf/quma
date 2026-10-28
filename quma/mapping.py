from __future__ import annotations

import inspect
from collections.abc import (
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from functools import lru_cache
from typing import (
    Any,
    Protocol,
    Self,
    TypeVar,
)

from . import exc
from .conn import Row

T = TypeVar("T")
RowMapping = Mapping[str, Any]
Target = type[T] | Callable[[RowMapping], type[T]]
Build = Callable[[Sequence[Any]], Any]


class FromRow(Protocol):
    """A mapping target that builds its instances from rows itself."""

    @classmethod
    def from_row(cls, row: RowMapping) -> Self: ...


def map_rows(
    target: Target[Any],
    description: Iterable[Sequence[Any]] | None,
    rows: Sequence[Row],
) -> list[Any]:
    """Map the ``rows`` of a cursor with the given ``description``."""
    if not rows:
        return []
    names = tuple(column[0] for column in description or ())
    if isinstance(target, type):
        build = _plan(target, names)
    elif callable(target):
        build = _resolver_plan(target, names)
    else:
        raise exc.MappingError(f"Cannot map rows to {target!r}")
    if isinstance(rows[0], dict):
        # mysqlclient's DictCursor
        return [build([row[name] for name in names]) for row in rows]
    return [build(row) for row in rows]


@lru_cache(maxsize=256)
def _plan(cls: type, names: tuple[str, ...]) -> Build:
    from_row = getattr(cls, "from_row", None)
    if callable(from_row):
        _check_duplicates(cls, names, names)
        return lambda values: from_row(dict(zip(names, values, strict=True)))
    if cls is dict:
        _check_duplicates(cls, names, names)
        return lambda values: dict(zip(names, values, strict=True))
    if issubclass(cls, dict) and hasattr(cls, "__required_keys__"):
        return _typeddict_plan(cls, names)
    return _constructor_plan(cls, names)


def _typeddict_plan(cls: Any, names: tuple[str, ...]) -> Build:
    index = _index(names)
    required = cls.__required_keys__
    missing = [key for key in sorted(required) if key not in index]
    if missing:
        raise exc.MissingColumnError(missing, cls)
    keys = required | cls.__optional_keys__
    used = [name for name in index if name in keys]
    _check_duplicates(cls, names, used)
    pairs = [(name, index[name]) for name in used]
    return lambda values: {name: values[i] for name, i in pairs}


def _constructor_plan(cls: type, names: tuple[str, ...]) -> Build:
    index = _index(names)
    used: list[str] = []
    missing: list[str] = []
    takes_rest = False
    for param in _signature(cls).parameters.values():
        if param.kind is param.VAR_KEYWORD:
            takes_rest = True
        elif param.kind is param.POSITIONAL_ONLY:
            if param.default is param.empty:
                raise exc.MappingError(
                    f'The parameter "{param.name}" of {cls.__qualname__} '
                    "is positional-only and has no default"
                )
        elif param.kind is not param.VAR_POSITIONAL:
            if param.name in index:
                used.append(param.name)
            elif param.default is param.empty:
                missing.append(param.name)
    if missing:
        raise exc.MissingColumnError(missing, cls)
    if takes_rest:
        used += [name for name in index if name not in used]
    _check_duplicates(cls, names, used)
    pairs = [(name, index[name]) for name in used]
    return lambda values: cls(**{name: values[i] for name, i in pairs})


def _signature(cls: type) -> inspect.Signature:
    if (
        cls.__init__ is object.__init__
        and cls.__new__ is object.__new__
        and type(cls).__call__ is type.__call__
    ):
        raise exc.MappingError(f"{cls.__qualname__} has no constructor")
    try:
        return inspect.signature(cls)
    except (TypeError, ValueError) as e:
        raise exc.MappingError(
            f"The constructor of {cls.__qualname__} cannot be inspected"
        ) from e


def _resolver_plan(
    resolver: Callable[[RowMapping], Any], names: tuple[str, ...]
) -> Build:
    _check_duplicates(resolver, names, names)
    plans: dict[type, Build] = {}

    def build(values: Sequence[Any]) -> Any:
        cls = resolver(dict(zip(names, values, strict=True)))
        if not isinstance(cls, type):
            raise exc.MappingError(
                f"The resolver {resolver!r} returned {cls!r}, not a class"
            )
        if cls not in plans:
            plans[cls] = _plan(cls, names)
        return plans[cls](values)

    return build


def _index(names: tuple[str, ...]) -> dict[str, int]:
    index: dict[str, int] = {}
    for i, name in enumerate(names):
        index.setdefault(name, i)
    return index


def _check_duplicates(
    target: Any, names: tuple[str, ...], used: Iterable[str]
) -> None:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        (duplicates if name in seen else seen).add(name)
    clashes = sorted(duplicates.intersection(used))
    if clashes:
        target_name = getattr(target, "__qualname__", repr(target))
        raise exc.MappingError(
            f'The column "{clashes[0]}" appears more than once in the '
            f"result, so it cannot be mapped to {target_name}"
        )
