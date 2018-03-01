import psycopg2

DB_NAME = 'quma_test_db'
DB_USER = 'quma_test_user'
DB_PASS = 'quma_test_password'
DSN = f'dbname={DB_NAME} user={DB_USER} password={DB_PASS}'

DROP_USERS = 'DROP TABLE IF EXISTS users;'
CREATE_USERS = ('CREATE TABLE users (           '
                '   id SERIAL PRIMARY KEY,      '
                '   name VARCHAR(128) NOT NULL, '
                '   email VARCHAR(128) NOT NULL '
                ');                             ')
INSERT_USERS = ("INSERT INTO                                        "
                "   users (name, email)                             "
                "VALUES                                             "
                "   ('Hans Karl', 'hans.karl@example.com'),         "
                "   ('Robert Fößel', 'robert.foessel@example.com'), "
                "   ('Franz Görtler', 'franz.goertler@example.com'),"
                "   ('Emil Jäger', 'emil.jaeger@example.com');      ")


def setup_pg_db():
    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute(DROP_USERS)
    cur.execute(CREATE_USERS)
    cur.execute(INSERT_USERS)
    conn.commit()
    cur.close()
    conn.close()
