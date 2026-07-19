from db_tests._shared import SinglePostgres


def _cursor():
    conn = SinglePostgres.connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS orders (id SERIAL PRIMARY KEY, total NUMERIC NOT NULL)"
    )
    return conn.cursor()


def test_inserted_order_is_readable() -> None:
    cursor = _cursor()
    cursor.execute("INSERT INTO orders (total) VALUES (49.99) RETURNING id")
    order_id = cursor.fetchone()[0]

    cursor.execute("SELECT total FROM orders WHERE id = %s", (order_id,))

    assert float(cursor.fetchone()[0]) == 49.99


def test_order_count_grows_by_one_per_insert() -> None:
    cursor = _cursor()
    cursor.execute("SELECT count(*) FROM orders")
    before = cursor.fetchone()[0]

    cursor.execute("INSERT INTO orders (total) VALUES (10.00)")
    cursor.execute("SELECT count(*) FROM orders")

    assert cursor.fetchone()[0] == before + 1


def test_deleting_all_orders_leaves_empty_table() -> None:
    cursor = _cursor()
    cursor.execute("DELETE FROM orders")

    cursor.execute("SELECT count(*) FROM orders")

    assert cursor.fetchone()[0] == 0
