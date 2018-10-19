UPDATE users SET
    email = %(email)s
WHERE
    city =  %(city)s;
