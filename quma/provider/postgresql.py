"""Alias of the psycopg2 provider for ``postgresql://`` URLs."""

from .psycopg2 import (  # noqa: F401
    Connection,
    PostgresChangelingCursor,
    PostgresChangelingRow,
)
