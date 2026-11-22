"""Demo module for trying DevPilot on a pull request. It contains deliberate bugs."""
import sqlite3


def get_orders_for_user(conn: sqlite3.Connection, user_id: str):
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM orders WHERE user_id = '" + user_id + "'")
    return cursor.fetchall()


def total_revenue(conn: sqlite3.Connection, user_ids: list[str]) -> float:
    total = 0
    for uid in user_ids:
        for order in get_orders_for_user(conn, uid):
            total += order[2]
    return total


def average_order_value(orders: list[float]) -> float:
    try:
        return sum(orders) / len(orders)
    except:
        pass
