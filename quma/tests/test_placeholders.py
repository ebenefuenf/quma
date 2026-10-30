import pytest

from .. import PlaceholderError
from ..placeholders import convert

DIALECTS = ["postgresql", "mysql", "sqlite"]
SERVERS = ["postgresql", "mysql"]


def test_named_placeholders():
    sql = "SELECT * FROM users WHERE name = :name AND city = :city_2"
    for dialect in SERVERS:
        assert convert(sql, dialect) == (
            "SELECT * FROM users WHERE name = %(name)s AND city = %(city_2)s"
        )
    assert convert(sql, "sqlite") == sql


def test_unicode_names():
    assert convert("SELECT :städte", "postgresql") == "SELECT %(städte)s"


def test_literal_percent():
    sql = "SELECT 5 % 2, name FROM users WHERE name LIKE 'User%' -- 100%"
    for dialect in SERVERS:
        assert convert(sql, dialect) == (
            "SELECT 5 %% 2, name FROM users WHERE name LIKE 'User%%' -- 100%%"
        )
    assert convert(sql, "sqlite") == sql


def test_casts_and_assignments():
    sql = "SELECT x::text, :id::int, @a := 1, arr[1:2]"
    assert convert(sql, "postgresql") == (
        "SELECT x::text, %(id)s::int, @a := 1, arr[1:2]"
    )


def test_escaped_colon():
    sql = r"SELECT a\:b, ':x\:'"
    for dialect in DIALECTS:
        assert convert(sql, dialect) == r"SELECT a:b, ':x\:'"
    assert convert(r"SELECT arr[lo\:hi]", "postgresql") == (
        "SELECT arr[lo:hi]"
    )


def test_strings_and_identifiers():
    sql = """SELECT ':a', 'it''s :b', "c:d" FROM t WHERE x = :x"""
    for dialect in SERVERS:
        assert convert(sql, dialect) == sql.replace(":x", "%(x)s")
    assert convert(sql, "sqlite") == sql


def test_postgresql_strings():
    # Backslashes escape in E'...' only.
    sql = r"SELECT E'it\'s :a', e'\\', '\' :b"
    assert convert(sql, "postgresql") == (
        r"SELECT E'it\'s :a', e'\\', '\' %(b)s"
    )
    # A name ending in "e" doesn't start an E'...' string, also with a
    # non-ASCII character, which PostgreSQL counts as part of a name.
    assert convert(r"SELECT name'\' :b", "postgresql") == (
        r"SELECT name'\' %(b)s"
    )
    assert convert(r"SELECT €E'\' :b", "postgresql") == (r"SELECT €E'\' %(b)s")


def test_postgresql_continued_strings():
    # An E'...' string continued after a newline keeps its escapes.
    for gap in ("\n", "\r", " -- c\n  -- d\n ", "\v\n\v"):
        sql = f"SELECT :x, E'a'{gap}'it\\'s :x', :y"
        assert convert(sql, "postgresql") == (
            f"SELECT %(x)s, E'a'{gap}'it\\'s :x', %(y)s"
        )
    # Without a newline, or with a /* */ comment, it doesn't continue.
    for gap in (" ", " /* c */\n"):
        sql = f"SELECT E'a'{gap}'b\\' :x"
        assert convert(sql, "postgresql") == f"SELECT E'a'{gap}'b\\' %(x)s"
    # A continued standard string keeps its rules too.
    assert convert("SELECT 'a'\n'b\\' :x", "postgresql") == (
        "SELECT 'a'\n'b\\' %(x)s"
    )


def test_postgresql_comment_ends():
    assert convert("SELECT 1 -- c\r:x", "postgresql") == "SELECT 1 -- c\r%(x)s"


def test_postgresql_dollar_quotes():
    sql = "SELECT $$ :a ' $$, $fn$ :b $$ :c $fn$, $1, :d"
    assert convert(sql, "postgresql") == (
        "SELECT $$ :a ' $$, $fn$ :b $$ :c $fn$, $1, %(d)s"
    )
    # Tags may hold non-ASCII characters, quotes may follow each other,
    # and a name may contain dollar signs.
    sql = "SELECT $€$ :a $€$, $$b$$$$ :c $$, ab$d$ :e"
    assert convert(sql, "postgresql") == (
        "SELECT $€$ :a $€$, $$b$$$$ :c $$, ab$d$ %(e)s"
    )


def test_postgresql_nested_comments():
    sql = "/* outer /* inner :a */ :b */ :c -- :d"
    assert convert(sql, "postgresql") == (
        "/* outer /* inner :a */ :b */ %(c)s -- :d"
    )


def test_mysql_strings_and_comments():
    sql = r"""SELECT 'it\'s :a', "say \":b\"", `c:d` # :e"""
    assert convert(sql, "mysql") == sql
    # MySQL's block comments don't nest, and "--" needs a space.
    assert convert("/* /* :a */ :b */", "mysql") == "/* /* :a */ %(b)s */"
    assert convert("SELECT 1--:a\n-- :b", "mysql") == (
        "SELECT 1--%(a)s\n-- :b"
    )


def test_sqlite_identifiers():
    sql = "SELECT [a:b], `c:d` FROM t WHERE x = :x"
    assert convert(sql, "sqlite") == sql


def test_unterminated():
    for dialect in DIALECTS:
        assert convert("SELECT ':a", dialect) == "SELECT ':a"
        assert convert("SELECT 1 /* :a", dialect) == "SELECT 1 /* :a"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM users WHERE name = %(name)s",
        "SELECT * FROM users WHERE name LIKE 'User%%'",
        "SELECT '%(name)s'",
    ],
)
def test_driver_placeholders(sql, dialect):
    with pytest.raises(PlaceholderError, match='placeholders="native"'):
        convert(sql, dialect)


def test_driver_placeholders_line():
    sql = "SELECT name\nFROM users\nWHERE name = %(name)s\nORDER BY 1"
    with pytest.raises(
        PlaceholderError,
        match=r'"%\(name\)s" in line 3: WHERE name = %\(name\)s\n',
    ):
        convert(sql, "postgresql")
