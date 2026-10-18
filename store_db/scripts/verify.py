"""Rerun-anytime sanity check over the seeded database."""

from _db import get_conn


def check_row_counts(conn):
    tables = [
        "products",
        "merchants",
        "consignments",
        "consignment_items",
        "inventory",
        "customers",
        "orders",
        "order_items",
        "price_history",
        "payments",
        "shipments",
        "returns",
        "reviews",
    ]
    print("-- Row counts --")
    for table in tables:
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        print(f"  {table}: {count}")


def check_no_negative_inventory(conn):
    bad = conn.execute("SELECT product_upc FROM inventory WHERE quantity_on_hand < 0").fetchall()
    assert not bad, f"Negative inventory for: {bad}"
    print("OK: no negative inventory.")


def check_no_oversold(conn):
    rows = conn.execute(
        """
        SELECT p.upc,
               COALESCE(SUM(ci.quantity), 0) AS received,
               COALESCE((SELECT SUM(oi.quantity) FROM order_items oi WHERE oi.product_upc = p.upc), 0) AS sold,
               COALESCE((SELECT quantity_on_hand FROM inventory i WHERE i.product_upc = p.upc), 0) AS on_hand
        FROM products p
        LEFT JOIN consignment_items ci ON ci.product_upc = p.upc
        GROUP BY p.upc
        """
    ).fetchall()
    oversold = [r for r in rows if r[1] - r[2] != r[3]]
    assert not oversold, f"Received - sold != on_hand for: {oversold[:5]}"
    print("OK: no product oversold (received - sold == on_hand for every product).")


def check_no_orphan_orders(conn):
    bad = conn.execute(
        "SELECT o.id FROM orders o LEFT JOIN order_items oi ON oi.order_id = o.id WHERE oi.id IS NULL"
    ).fetchall()
    assert not bad, f"Orders with no line items: {bad}"
    print("OK: no orphan orders.")


def check_fk_violation_raises(conn):
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO order_items (order_id, product_upc, quantity, unit_price) VALUES (999999999, 'nonexistent', 1, 1.00)")
        conn.rollback()
        raise AssertionError("Expected a foreign key violation but insert succeeded.")
    except Exception as e:
        conn.rollback()
        assert "foreign key" in str(e).lower(), f"Unexpected error: {e}"
        print("OK: FK violation correctly rejected.")


def check_price_volume_correlation(conn):
    rows = conn.execute(
        """
        WITH monthly AS (
            SELECT date_trunc('month', order_date) AS month, COUNT(*) AS order_count
            FROM orders GROUP BY 1
        ),
        monthly_price AS (
            SELECT date_trunc('month', effective_from) AS month, AVG(price) AS avg_price
            FROM price_history GROUP BY 1
        )
        SELECT m.month, m.order_count, mp.avg_price
        FROM monthly m JOIN monthly_price mp ON mp.month = m.month
        ORDER BY mp.avg_price
        """
    ).fetchall()
    median_price = sorted(r[2] for r in rows)[len(rows) // 2]
    below = [r[1] for r in rows if r[2] < median_price]
    above = [r[1] for r in rows if r[2] >= median_price]
    avg_below = sum(below) / len(below) if below else 0
    avg_above = sum(above) / len(above) if above else 0
    print(f"Avg orders/month in below-median-price months: {avg_below:.1f}")
    print(f"Avg orders/month in above-median-price months: {avg_above:.1f}")


def main() -> None:
    with get_conn() as conn:
        check_row_counts(conn)
        print()
        check_no_negative_inventory(conn)
        check_no_oversold(conn)
        check_no_orphan_orders(conn)
        check_fk_violation_raises(conn)
        print()
        check_price_volume_correlation(conn)


if __name__ == "__main__":
    main()
