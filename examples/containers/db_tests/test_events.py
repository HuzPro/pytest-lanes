from db_tests._shared import SinglePostgres


def _cursor():
    conn = SinglePostgres.connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS events "
        "(id SERIAL PRIMARY KEY, kind TEXT NOT NULL, at TIMESTAMP DEFAULT NOW())"
    )
    return conn.cursor()


def test_events_filter_by_kind() -> None:
    cursor = _cursor()
    cursor.execute("INSERT INTO events (kind) VALUES ('login'), ('logout'), ('login')")

    cursor.execute("SELECT count(*) FROM events WHERE kind = 'login'")

    assert cursor.fetchone()[0] >= 2


def test_events_order_by_recency() -> None:
    cursor = _cursor()
    cursor.execute("INSERT INTO events (kind) VALUES ('newest')")

    cursor.execute("SELECT kind FROM events ORDER BY at DESC, id DESC LIMIT 1")

    assert cursor.fetchone()[0] == "newest"
