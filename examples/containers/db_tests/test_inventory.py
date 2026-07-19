from db_tests._shared import SinglePostgres


def _cursor():
    conn = SinglePostgres.connection()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS inventory (sku TEXT PRIMARY KEY, quantity INT NOT NULL)"
    )
    return conn.cursor()


def test_upsert_increments_quantity() -> None:
    cursor = _cursor()
    cursor.execute(
        "INSERT INTO inventory VALUES ('widget', 5) "
        "ON CONFLICT (sku) DO UPDATE SET quantity = inventory.quantity + 5"
    )
    cursor.execute(
        "INSERT INTO inventory VALUES ('widget', 5) "
        "ON CONFLICT (sku) DO UPDATE SET quantity = inventory.quantity + 5"
    )

    cursor.execute("SELECT quantity FROM inventory WHERE sku = 'widget'")

    assert cursor.fetchone()[0] >= 10


def test_negative_stock_is_queryable() -> None:
    cursor = _cursor()
    cursor.execute(
        "INSERT INTO inventory VALUES ('rare-part', -1) ON CONFLICT (sku) DO NOTHING"
    )

    cursor.execute("SELECT count(*) FROM inventory WHERE quantity < 0")

    assert cursor.fetchone()[0] >= 1
