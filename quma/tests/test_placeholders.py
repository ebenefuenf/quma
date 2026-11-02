import pytest

from .. import PlaceholderError
from ..placeholders import (
    convert,
    convert_lists,
    list_sizes,
    spread,
)

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
    # Backslashes escape in E'...' strings, whatever the settings.
    sql = r"SELECT E'it\'s :a', e'\\', '\\d+', :b"
    assert convert(sql, "postgresql") == (
        r"SELECT E'it\'s :a', e'\\', '\\d+', %(b)s"
    )


def test_postgresql_backslash_before_quote():
    # A standard string ends at its quote, unless
    # standard_conforming_strings is off.
    with pytest.raises(PlaceholderError, match="standard_conforming_strings"):
        convert(r"SELECT 'C:\' || :b", "postgresql")
    assert convert(r"SELECT E'C:\\' || :b", "postgresql") == (
        r"SELECT E'C:\\' || %(b)s"
    )
    # A name ending in "e" doesn't start an E'...' string, also with a
    # non-ASCII character, which PostgreSQL counts as part of a name.
    for prefix in ("name", "€E"):
        with pytest.raises(PlaceholderError):
            convert(f"SELECT {prefix}'a\\' :b '", "postgresql")
    assert convert("SELECT E'a\\' :b '", "postgresql") == "SELECT E'a\\' :b '"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT E:v",
        "SELECT e:v",
        "SELECT 1E:v",
        "SELECT E'a'\n:v",
        "SELECT E'a'\r:v",
        "SELECT E'a' -- c\n  -- d\n :v",
        "SELECT E'a'\n'b'\n:v",
    ],
)
def test_postgresql_value_in_an_escape_string(sql):
    with pytest.raises(PlaceholderError, match="E'...' string"):
        convert(sql, "postgresql")


@pytest.mark.parametrize(
    "sql, converted",
    [
        ("SELECT nameE:v", "SELECT nameE%(v)s"),
        ("SELECT €E:v", "SELECT €E%(v)s"),
        ("SELECT a[e :v]", "SELECT a[e %(v)s]"),
        ("SELECT e::text", "SELECT e::text"),
        ("SELECT E\\:v", "SELECT E:v"),
        ("SELECT E'a' :v", "SELECT E'a' %(v)s"),
        ("SELECT E'a'\n|| :v", "SELECT E'a'\n|| %(v)s"),
        ("SELECT 'a'\n:v", "SELECT 'a'\n%(v)s"),
    ],
)
def test_postgresql_value_outside_of_an_escape_string(sql, converted):
    assert convert(sql, "postgresql") == converted


def test_e_before_a_placeholder_stays_valid_elsewhere():
    assert convert("SELECT E:v", "mysql") == "SELECT E%(v)s"
    assert convert("SELECT E:v", "sqlite") == "SELECT E:v"


def test_postgresql_continued_strings():
    # An E'...' string continued after a newline keeps its escapes.
    for gap in ("\n", "\r", " -- c\n  -- d\n ", "\v\n\v"):
        sql = f"SELECT :x, E'a'{gap}'it\\'s :x', :y"
        assert convert(sql, "postgresql") == (
            f"SELECT %(x)s, E'a'{gap}'it\\'s :x', %(y)s"
        )
    # Without a newline, or with a /* */ comment, the next part is a
    # standard string, and so is a continued standard string.
    for sql in ("E'a' 'b", "E'a' /* c */\n'b", "'a'\n'b"):
        with pytest.raises(PlaceholderError, match="standard_conforming"):
            convert(f"SELECT {sql}\\' :x", "postgresql")


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
    sql = r"""SELECT 'it''s :a', "say "":b"" ", '\\', "\\", `c:d` # :e"""
    assert convert(sql, "mysql") == sql
    # MySQL's block comments don't nest, and "--" needs a space.
    assert convert("/* /* :a */ :b */", "mysql") == "/* /* :a */ %(b)s */"
    assert convert("SELECT 1--:a\n-- :b", "mysql") == (
        "SELECT 1--%(a)s\n-- :b"
    )


def test_mysql_backslash_before_quote():
    # Backslashes escape unless the sql_mode has NO_BACKSLASH_ESCAPES, and
    # with ANSI_QUOTES "..." is a name, where they never escape.
    with pytest.raises(PlaceholderError, match="NO_BACKSLASH_ESCAPES"):
        convert(r"SELECT 'it\'s :a', :b", "mysql")
    with pytest.raises(PlaceholderError, match="ANSI_QUOTES"):
        convert(r'SELECT "say \":a\"", :b', "mysql")
    # Without a placeholder it reads the same either way.
    assert convert(r"SELECT 'it\'s'", "mysql") == r"SELECT 'it\'s'"


def test_mysql_executable_comments():
    # The server runs /*! ... */ as SQL, with strings and comments.
    sql = "SELECT /*! :a + */ 1, /*! '*/' /* :b */ -- :c */\n + :d */ ':e'"
    assert convert(sql, "mysql") == (
        "SELECT /*! %(a)s + */ 1, /*! '*/' /* :b */ -- :c */\n + %(d)s */ ':e'"
    )
    # Hints are comments.
    assert convert("SELECT /*+ BKA(t) :a */ :b", "mysql") == (
        "SELECT /*+ BKA(t) :a */ %(b)s"
    )


def test_mysql_versioned_comments():
    # Whether the server runs them depends on its version and type, and
    # one server may run some and skip others.
    for sql in (
        "/*!80000 :a */",
        "/*M! :a */",
        "/*!80000 '*/' */ :a",
        "/*!99999 '/*' */ :a */",
        "/*!50700 1, */ :a",
        "/*!50700 1, */ a\\:b",
    ):
        with pytest.raises(PlaceholderError, match="versioned comment"):
            convert(f"SELECT {sql}", "mysql")
    sql = "SELECT /*!80000 1 + */ 2 % 3, /*M!100100 3 + */ ':a'"
    assert convert(sql, "mysql") == sql.replace("%", "%%")
    # Without five digits, /*! has no version, and /*m! is a comment.
    assert convert("SELECT /*!123 :a */, /*m! :b */ :c", "mysql") == (
        "SELECT /*!123 %(a)s */, /*m! :b */ %(c)s"
    )


def test_mysql_line_comments():
    # "--" needs ASCII whitespace or a control character after it.
    sql = "SELECT 1 --\x01 :a\n, 2 --\x7f :b\n, 3 --\u00a0:c"
    assert convert(sql, "mysql") == sql.replace(":c", "%(c)s")


def test_ambiguous_line():
    sql = "SELECT\n  'a\\',\n  ':b'"
    with pytest.raises(PlaceholderError, match=r"Line 3 .*: ':b'\n"):
        convert(sql, "mysql")


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


def plain(dialect):
    return ":ids" if dialect == "sqlite" else "%(ids)s"


def elements(dialect, size=2):
    names = [f"ids__{i}" for i in range(size)]
    if dialect == "sqlite":
        return "(" + ", ".join(f":{name}" for name in names) + ")"
    return "(" + ", ".join(f"%({name})s" for name in names) + ")"


@pytest.mark.parametrize("dialect", DIALECTS)
def test_list_after_in(dialect):
    converted = convert_lists("SELECT 1 WHERE 1 IN :ids", dialect, {"ids": 2})
    assert converted.sql == f"SELECT 1 WHERE 1 IN {elements(dialect)}"
    assert converted.expanded == {"ids"}
    assert converted.kept == frozenset()


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "before",
    [
        "x IN ",
        "x NOT IN ",
        "x in ",
        "x In\n\t",
        "x IN\r\n",
        "x IN",
        "'a'IN ",
        "(x)IN ",
        "1 IN ",
    ],
)
def test_list_after_in_spellings(dialect, before):
    converted = convert_lists(f"SELECT {before}:ids", dialect, {"ids": 2})
    assert converted.sql == f"SELECT {before}{elements(dialect)}"


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "sql",
    [
        "x = ANY({})",
        "x = {}",
        "x IN ({})",
        "x IN /* c */ {}",
        "x IN -- c\n {}",
        "x -- IN\n{}",
        "x /* IN */ {}",
        "'IN' {}",
        '"IN" {}',
        "margin {}",
        "x_in {}",
        "t.in {}",
        "x$in {}",
        "€in {}",
        "1in {}",
        "ıN {}",
        "IN\xa0{}",
    ],
)
def test_list_not_directly_after_in(dialect, sql):
    converted = convert_lists(sql.format(":ids"), dialect, {"ids": 2})
    assert converted.sql == sql.format(plain(dialect))
    assert converted.expanded == frozenset()
    assert converted.kept == {"ids"}


@pytest.mark.parametrize("dialect", DIALECTS)
@pytest.mark.parametrize(
    "text",
    ["'IN :ids'", "-- IN :ids", "/* IN :ids */", "'x' -- IN :ids\n"],
)
def test_text_that_looks_like_a_list(dialect, text):
    converted = convert_lists(f"SELECT {text}", dialect, {"ids": 2})
    assert converted.sql == f"SELECT {text}"
    assert converted.expanded == frozenset()


def test_text_that_looks_like_a_list_in_postgresql_strings():
    for text in ("$$IN :ids$$", "$a$IN :ids$a$", "E'IN :ids'", '"IN :ids"'):
        sql = f"SELECT {text}"
        assert convert_lists(sql, "postgresql", {"ids": 2}).sql == sql


@pytest.mark.parametrize("dialect", DIALECTS)
def test_list_used_twice(dialect):
    sql = "x IN :ids OR y NOT IN :ids"
    converted = convert_lists(sql, dialect, {"ids": 2})
    list_sql = elements(dialect)
    assert converted.sql == f"x IN {list_sql} OR y NOT IN {list_sql}"
    assert converted.kept == frozenset()


def test_list_after_in_and_elsewhere():
    converted = convert_lists(
        "x IN :ids OR y = ANY(:ids)", "postgresql", {"ids": 1}
    )
    assert converted.sql == ("x IN (%(ids__0)s) OR y = ANY(%(ids)s)")
    assert converted.expanded == {"ids"}
    assert converted.kept == {"ids"}


def test_list_keeps_the_rest_of_the_conversion():
    converted = convert_lists(
        "name LIKE 'a%' AND city = :city AND id IN :ids AND x::text = '1'",
        "postgresql",
        {"ids": 1},
    )
    assert converted.sql == (
        "name LIKE 'a%%' AND city = %(city)s AND id IN (%(ids__0)s) "
        "AND x::text = '1'"
    )
    assert converted.kept == {"city"}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_empty_list_after_in(dialect):
    with pytest.raises(ValueError, match='"ids" is empty'):
        convert_lists("SELECT 1 WHERE 1 NOT IN :ids", dialect, {"ids": 0})


def test_empty_list_elsewhere():
    sql = "SELECT 1 WHERE 1 = ANY(:ids) -- IN :ids"
    assert convert_lists(sql, "postgresql", {"ids": 0}).sql == (
        "SELECT 1 WHERE 1 = ANY(%(ids)s) -- IN :ids"
    )


def test_list_in_sql_the_readings_disagree_on():
    with pytest.raises(PlaceholderError, match="standard_conforming_strings"):
        convert_lists(r"SELECT 'C:\' IN :ids", "postgresql", {"ids": 2})
    with pytest.raises(PlaceholderError, match="NO_BACKSLASH_ESCAPES"):
        convert_lists(r"SELECT 'it\'s' IN :ids", "mysql", {"ids": 2})


def test_list_in_mysql_comments():
    assert convert_lists(
        "SELECT /*! 1 IN :ids */", "mysql", {"ids": 1}
    ).sql == ("SELECT /*! 1 IN (%(ids__0)s) */")
    with pytest.raises(PlaceholderError, match="versioned comment"):
        convert_lists("SELECT /*!80000 2, */ 1 IN :ids", "mysql", {"ids": 1})


@pytest.mark.parametrize("value", [[1, 2], (1, 2), {1, 2}, frozenset({1, 2})])
def test_list_sizes_of_lists(value):
    assert list_sizes("x IN :ids", {"ids": value, "other": 1}) == {"ids": 2}


@pytest.mark.parametrize(
    "value", ["ab", b"ab", {"a": 1}, None, 1, range(2), iter([1, 2])]
)
def test_list_sizes_of_other_values(value):
    assert list_sizes("x IN :ids", {"ids": value}) == {}


def test_list_sizes_without_in():
    assert list_sizes("x = :ids", {"ids": [1, 2]}) == {}
    assert list_sizes("x IN :other", {"ids": [1, 2]}) == {}


def test_spread():
    params = {"ids": [5, 6], "city": "Berlin"}
    converted = convert_lists("x IN :ids AND y = :city", "mysql", {"ids": 2})
    assert spread(params, converted) == {
        "ids__0": 5,
        "ids__1": 6,
        "city": "Berlin",
    }
    assert params == {"ids": [5, 6], "city": "Berlin"}


def test_spread_keeps_a_list_with_its_own_placeholder():
    converted = convert_lists(
        "x IN :ids OR y = ANY(:ids)", "postgresql", {"ids": 1}
    )
    assert spread({"ids": [5]}, converted) == {"ids": [5], "ids__0": 5}


def test_spread_refuses_a_name_in_use():
    converted = convert_lists("x IN :ids", "postgresql", {"ids": 1})
    with pytest.raises(ValueError, match='"ids__0"'):
        spread({"ids": [5], "ids__0": 7}, converted)
