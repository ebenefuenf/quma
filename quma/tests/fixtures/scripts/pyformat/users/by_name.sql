SELECT
    email,
    city,
    13 AS count,
    13 AS count2
FROM
    users
WHERE
    name = %(name)s;
