from collections.abc import Iterator
from dataclasses import dataclass
from typing import (
    Any,
    NamedTuple,
    NotRequired,
    TypedDict,
    assert_type,
)

import pytest

from .. import (
    Database,
    MappingError,
    MissingColumnError,
)
from ..mapping import RowMapping

USER_3 = "SELECT id, name, email, city FROM users WHERE id = 3"
NO_USER = "SELECT id, name, email, city FROM users WHERE id = 0"


@dataclass
class User:
    id: int
    name: str
    email: str
    city: str | None = "Nowhere"


class UserTuple(NamedTuple):
    id: int
    name: str


class PlainUser:
    def __init__(self, id, name, *args, **extra):
        self.id = id
        self.name = name
        self.extra = extra


class RowUser:
    def __init__(self, label):
        self.label = label

    @classmethod
    def from_row(cls, row: RowMapping):
        return cls(f"{row['id']}: {row['name']}")


class UserDict(TypedDict):
    id: int
    name: str
    nickname: NotRequired[str]


def by_parity(row: RowMapping) -> type[User] | type[UserTuple]:
    return UserTuple if row["id"] % 2 else User


def map_targets(db):
    with db.cursor as cur:
        users = cur.users.all()
        assert users.all(User)[2] == User(
            3, "User 3", "user.3@example.com", "City B"
        )
        assert len(users.all(User)) == 7
        assert users.first(UserTuple) == UserTuple(1, "User 1")

        plain = cur.query(USER_3).one(PlainUser)
        assert (plain.id, plain.name) == (3, "User 3")
        assert plain.extra == {"email": "user.3@example.com", "city": "City B"}

        assert cur.query(USER_3).one(RowUser).label == "3: User 3"


def map_dicts(db):
    with db.cursor as cur:
        user = cur.query(USER_3).one(dict)
        assert type(user) is dict
        assert list(user.items()) == [
            ("id", 3),
            ("name", "User 3"),
            ("email", "user.3@example.com"),
            ("city", "City B"),
        ]
        assert cur.query(USER_3).one(UserDict) == {"id": 3, "name": "User 3"}
        nick = cur.query(
            "SELECT 'Nick' AS nickname, id, name FROM users WHERE id = 3"
        ).one(UserDict)
        assert list(nick.items()) == [
            ("nickname", "Nick"),
            ("id", 3),
            ("name", "User 3"),
        ]


def map_empty(db):
    with db.cursor as cur:
        assert cur.query(NO_USER).first(User) is None
        assert cur.query(NO_USER).all(User) == []
        with pytest.raises(db.DoesNotExistError):
            cur.query(NO_USER).one(User)


def map_defaults(db):
    with db.cursor as cur:
        user = cur.query("SELECT id, name, email FROM users WHERE id = 1").one(
            User
        )
        assert user.city == "Nowhere"
        user = cur.query(
            "SELECT id, name, email, NULL AS city FROM users WHERE id = 1"
        ).one(User)
        assert user.city is None


def map_missing(db):
    with db.cursor as cur:
        query = cur.query("SELECT id FROM users WHERE id = 1")
        with pytest.raises(MissingColumnError) as e:
            query.one(User)
        assert e.value.columns == ("name", "email")
        assert e.value.target is User
        with pytest.raises(MissingColumnError) as e:
            query.one(UserDict)
        assert e.value.columns == ("name",)


def map_duplicates(db):
    with db.cursor as cur:
        query = cur.query(
            "SELECT id, name, city, city FROM users WHERE id = 1"
        )
        assert query.one(UserTuple) == UserTuple(1, "User 1")
        assert query.one(UserDict) == {"id": 1, "name": "User 1"}
        for target in (PlainUser, RowUser, dict, by_parity):
            with pytest.raises(MappingError, match='"city"'):
                query.one(target)
        query = cur.query("SELECT id, name, id FROM users WHERE id = 1")
        for target in (UserTuple, UserDict):
            with pytest.raises(MappingError, match='"id"'):
                query.one(target)


def map_resolver(db):
    with db.cursor as cur:
        users = cur.users.all().all(by_parity)
        assert [type(user) for user in users[:3]] == [
            UserTuple,
            User,
            UserTuple,
        ]
        assert users[1] == User(2, "User 2", "user.2@example.com", "City A")
        with pytest.raises(MappingError, match="not a class"):
            cur.query(USER_3).one(lambda row: row["name"])


def map_chunks(db):
    with db.cursor as cur:
        users = list(cur.users.all().unbunch(3, User))
        assert len(users) == 7
        assert users[6] == User(7, "User 7", "user.7@example.com", "City C")
        tuples = cur.users.all().unbunch(target=UserTuple)
        assert next(tuples) == UserTuple(1, "User 1")

        many = cur.users.all().many()
        assert many.get(2, User)[1].name == "User 2"
        rest = many.get(size=10, target=dict)
        assert [user["id"] for user in rest] == [3, 4, 5, 6, 7]


def map_all(db):
    map_targets(db)
    map_dicts(db)
    map_empty(db)
    map_defaults(db)
    map_missing(db)
    map_duplicates(db)
    map_resolver(db)
    map_chunks(db)


def test_mapping(db, db_no_changeling):
    for database in (db, db_no_changeling):
        map_all(database)


def test_invalid_targets(db):
    class Empty:
        pass

    class PositionalOnly:
        def __init__(self, id, /):
            self.id = id

    class PositionalOnlyDefault:
        def __init__(self, id=0, /, name=""):
            self.id = id
            self.name = name

    class Uninspectable(dict):
        pass

    with db.cursor as cur:
        query = cur.query(USER_3)
        with pytest.raises(MappingError, match="has no constructor"):
            query.one(Empty)
        with pytest.raises(MappingError, match="positional-only"):
            query.one(PositionalOnly)
        user = query.one(PositionalOnlyDefault)
        assert (user.id, user.name) == (0, "User 3")
        with pytest.raises(MappingError, match="cannot be inspected"):
            query.one(Uninspectable)
        with pytest.raises(MappingError, match="Cannot map rows to 42"):
            query.one(42)


def test_metaclass_constructor(db):
    class Constructing(type):
        def __call__(cls, id, name):
            instance = super().__call__()
            instance.id = id
            instance.name = name
            return instance

    class Built(metaclass=Constructing):
        pass

    with db.cursor as cur:
        user = cur.query(USER_3).one(Built)
        assert (user.id, user.name) == (3, "User 3")


def test_mapped_types(db: Database):
    with db.cursor as cur:
        query = cur.query(USER_3)
        assert_type(query.one(), Any)
        assert_type(query.one(User), User)
        assert_type(query.one(UserDict), UserDict)
        assert_type(query.one(dict), dict[str, Any])
        assert_type(query.one(by_parity), User | UserTuple)
        assert_type(query.first(User), User | None)
        assert_type(query.first(dict), dict[str, Any] | None)
        assert_type(query.all(User), list[User])
        assert_type(query.all(dict), list[dict[str, Any]])
        assert_type(query.unbunch(10, User), Iterator[User])
        assert_type(query.unbunch(target=dict), Iterator[dict[str, Any]])
        assert_type(query.many().get(10, User), list[User])
        assert_type(query.many().get(target=UserDict), list[UserDict])
