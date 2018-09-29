import os


SQLITE_FILE = '/tmp/quma_test.sqlite'
DB_NAME = 'quma_test_db'
DB_USER = 'quma_test_user'
DB_PASS = 'quma_test_password'
DSN = f'dbname={DB_NAME} user={DB_USER} password={DB_PASS}'
SQLITE_URI = f'sqlite:///{SQLITE_FILE}'
SQLITE_MEMORY = 'sqlite:///:memory:'
PGSQL_URI = f'postgresql://{DB_USER}:{DB_PASS}@/{DB_NAME}'
PGSQL_POOL_URI = f'postgresql+pool://{DB_USER}:{DB_PASS}@/{DB_NAME}'
MYSQL_URI = f'mysql://{DB_USER}:{DB_PASS}@/{DB_NAME}'
MYSQL_POOL_URI = f'mysql+pool://{DB_USER}:{DB_PASS}@/{DB_NAME}'

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
    (4, 'User 4', 'user.4@example.com', 'City B');
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
