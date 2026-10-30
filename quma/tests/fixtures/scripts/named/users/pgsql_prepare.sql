PREPARE prep (varchar(128), int) AS
SELECT name, city FROM users WHERE email = $1 AND 1 = $2;
