from db_tests._shared import SinglePostgres


def _cursor():
    conn = SinglePostgres.connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, email TEXT UNIQUE NOT NULL)"
    )
    return conn.cursor()


def test_inserted_user_is_readable_by_email() -> None:
    cursor = _cursor()
    cursor.execute("INSERT INTO users (email) VALUES ('a@example.com') ON CONFLICT DO NOTHING")

    cursor.execute("SELECT email FROM users WHERE email = 'a@example.com'")

    assert cursor.fetchone()[0] == "a@example.com"


def test_duplicate_email_is_rejected_by_unique_constraint() -> None:
    cursor = _cursor()
    cursor.execute("INSERT INTO users (email) VALUES ('b@example.com') ON CONFLICT DO NOTHING")

    cursor.execute("INSERT INTO users (email) VALUES ('b@example.com') ON CONFLICT DO NOTHING")
    cursor.execute("SELECT count(*) FROM users WHERE email = 'b@example.com'")

    assert cursor.fetchone()[0] == 1


def test_deleted_user_is_gone() -> None:
    cursor = _cursor()
    cursor.execute("INSERT INTO users (email) VALUES ('c@example.com') ON CONFLICT DO NOTHING")
    cursor.execute("DELETE FROM users WHERE email = 'c@example.com'")

    cursor.execute("SELECT count(*) FROM users WHERE email = 'c@example.com'")

    assert cursor.fetchone()[0] == 0
