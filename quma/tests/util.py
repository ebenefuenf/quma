import os

DB_USER = 'quma_test_user'
DB_PASS = 'quma_test_password'
DB_NAME = 'quma_test_db'

SQLITE_FILE = '/tmp/quma_test.sqlite'
SQLITE_URI = 'sqlite:///{}'.format(SQLITE_FILE)
SQLITE_MEMORY = 'sqlite:///:memory:'

try:
    PGSQL_USER = os.environ['QUMA_PGSQL_USER']
except KeyError:
    PGSQL_USER = DB_USER
try:
    PGSQL_PASS = os.environ['QUMA_PGSQL_PASS']
except KeyError:
    PGSQL_PASS = DB_PASS
try:
    PGSQL_DB = os.environ['QUMA_PGSQL_DB']
except KeyError:
    PGSQL_DB = DB_NAME
PGSQL_URI = 'postgresql://{}:{}@/{}'.format(PGSQL_USER, PGSQL_PASS, PGSQL_DB)
PGSQL_POOL_URI = 'postgresql+pool://{}:{}@/{}'.format(
    PGSQL_USER, PGSQL_PASS, PGSQL_DB)

try:
    MYSQL_USER = os.environ['QUMA_MYSQL_USER']
except KeyError:
    MYSQL_USER = DB_USER
try:
    MYSQL_PASS = os.environ['QUMA_MYSQL_PASS']
except KeyError:
    MYSQL_PASS = DB_PASS
try:
    MYSQL_DB = os.environ['QUMA_MYSQL_DB']
except KeyError:
    MYSQL_DB = DB_NAME
MYSQL_URI = 'mysql://{}:{}@/{}'.format(MYSQL_USER, MYSQL_PASS, MYSQL_DB)
MYSQL_POOL_URI = 'mysql+pool://{}:{}@/{}'.format(
    MYSQL_USER, MYSQL_PASS, MYSQL_DB)

DROP_USERS = 'DROP TABLE IF EXISTS users;'
CREATE_USERS = ("""
CREATE TABLE users (
    id INT PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    email VARCHAR(128) NOT NULL,
    city VARCHAR(128) NOT NULL);
""")
INSERT_USERS = ("""
INSERT INTO
    users (id, name, email, city)
VALUES
    (1, 'User 1', 'user.1@example.com', 'City A'),
    (2, 'User 2', 'user.2@example.com', 'City A'),
    (3, 'User 3', 'user.3@example.com', 'City B'),
    (4, 'User 4', 'user.4@example.com', 'City B'),
    (5, 'User 5', 'user.5@example.com', 'City C'),
    (6, 'User 6', 'user.6@example.com', 'City C'),
    (7, 'User 7', 'user.7@example.com', 'City C');
""")


def setup_pg_db():
    import psycopg2
    conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS)
    cur = conn.cursor()
    cur.execute(DROP_USERS)
    cur.execute(CREATE_USERS)
    cur.execute(INSERT_USERS)
    cur.execute('DROP TABLE IF EXISTS test;')
    conn.commit()
    cur.close()
    conn.close()


def setup_mysql_db():
    import MySQLdb
    conn = MySQLdb.connect(db=DB_NAME, user=DB_USER, passwd=DB_PASS)
    cur = conn.cursor()
    cur.execute(DROP_USERS)
    cur.execute(CREATE_USERS)
    cur.execute(INSERT_USERS)
    # To suppress warning 1051 "Unknown table"
    cur.execute("SHOW TABLES LIKE 'test';")
    if len(cur.fetchall()) > 0:
        cur.execute('DROP TABLE test;')
    conn.commit()
    cur.close()
    conn.close()


def remove_db(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass
