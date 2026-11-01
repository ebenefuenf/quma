from __future__ import annotations

import inspect
import logging
from collections.abc import (
    Awaitable,
    Callable,
    Mapping,
    Sequence,
)
from dataclasses import dataclass
from time import perf_counter
from typing import Any

logger = logging.getLogger("quma")

# What drivers call these arguments of execute(), executemany() and callproc().
SQL_KEYWORDS = ("query", "procname")
PARAMS_KEYWORDS = (
    "params",
    "vars",
    "args",
    "parameters",
    "params_seq",
    "vars_list",
)


@dataclass(frozen=True, slots=True)
class Execution:
    """A statement that quma sent to the driver, as passed to
    ``on_execute``. See :doc:`Logging and hooks <logging>`.

    :param name: The script's path in its SQL directory without the file
        extension, like ``users/by_name``. ``None`` if the statement doesn't
        come from a script file.
    :param sql: The statement as the driver received it: after rendering
        templates and converting placeholders, before binding parameters.
    :param params: The parameters as the driver received them.
    :param duration: The seconds the driver took to run the statement.
    :param rowcount: The driver's row count, or ``None`` if it has none, the
        statement failed or it opened a stream.
    :param error: The exception the statement raised, or ``None``.
    """

    name: str | None
    sql: Any
    params: Any
    duration: float
    rowcount: int | None
    error: BaseException | None


OnExecute = Callable[[Execution], None]


def observed(
    on_execute: OnExecute | None,
    name: str | None,
    call: Callable[..., Any],
    args: Sequence[Any],
    kwargs: Mapping[str, Any],
    rowcount: Callable[[], int | None] | None = None,
) -> Any:
    """Run ``call``, which sends one statement to the driver, and report it.
    If ``call`` returns an awaitable, the result reports it once awaited."""
    if on_execute is None and not logger.isEnabledFor(logging.DEBUG):
        return call(*args, **kwargs)
    observation = Observation(on_execute, name, args, kwargs, rowcount)
    return observation.run(call)


def _keyword(kwargs: Mapping[str, Any], keywords: Sequence[str]) -> Any:
    return next((kwargs[key] for key in keywords if key in kwargs), None)


class Observation:
    def __init__(
        self,
        on_execute: OnExecute | None,
        name: str | None,
        args: Sequence[Any],
        kwargs: Mapping[str, Any],
        rowcount: Callable[[], int | None] | None,
    ) -> None:
        self.on_execute = on_execute
        self.name = name
        self.args = args
        self.kwargs = kwargs
        self.rowcount = rowcount
        self.start = 0.0

    def run(self, call: Callable[..., Any]) -> Any:
        self.start = perf_counter()
        try:
            result = call(*self.args, **self.kwargs)
        except BaseException as e:
            self.report(e)
            raise
        if inspect.isawaitable(result):
            return self.wait(result)
        self.report()
        return result

    async def wait(self, result: Awaitable[Any]) -> Any:
        # The caller may have waited for its turn on the cursor since then.
        self.start = perf_counter()
        try:
            value = await result
        except BaseException as e:
            self.report(e)
            raise
        self.report()
        return value

    def report(self, error: BaseException | None = None) -> None:
        duration = perf_counter() - self.start
        # The statement has run, so its result must reach the caller.
        try:
            execution = self.execution(duration, error)
            log(execution)
            if self.on_execute is not None:
                self.on_execute(execution)
        except Exception:
            logger.exception(
                "Reporting a statement failed: %s", self.name or "query"
            )

    def execution(
        self, duration: float, error: BaseException | None
    ) -> Execution:
        args, kwargs = self.args, self.kwargs
        return Execution(
            self.name,
            args[0] if args else _keyword(kwargs, SQL_KEYWORDS),
            args[1] if len(args) > 1 else _keyword(kwargs, PARAMS_KEYWORDS),
            duration,
            self.rowcount() if self.rowcount and error is None else None,
            error,
        )


def log(execution: Execution) -> None:
    if not logger.isEnabledFor(logging.DEBUG):
        return
    error = execution.error
    # Driver messages can quote values, so only the type of the error.
    outcome = (
        f"rowcount {execution.rowcount}"
        if error is None
        else f"failed with {type(error).__name__}"
    )
    logger.debug(
        "%s: %.1f ms, %s\n%s",
        execution.name or "query",
        execution.duration * 1000,
        outcome,
        execution.sql,
    )
