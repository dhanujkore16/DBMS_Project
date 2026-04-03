from __future__ import annotations

from pathlib import Path
from typing import Any

import mysql.connector
from flask import g
from werkzeug.security import generate_password_hash


SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Dhanuj@1356",
    "database": "hotel_management",
}


def raw_connection(use_database: bool = True) -> mysql.connector.MySQLConnection:
    config = MYSQL_CONFIG if use_database else {k: v for k, v in MYSQL_CONFIG.items() if k != "database"}
    return mysql.connector.connect(**config)


def get_db() -> mysql.connector.MySQLConnection:
    if "db" not in g:
        g.db = raw_connection()
    return g.db


def close_db() -> None:
    db = g.pop("db", None)
    if db is not None and db.is_connected():
        db.close()


def fetch_one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    cursor = get_db().cursor(dictionary=True)
    cursor.execute(query, params)
    row = cursor.fetchone()
    cursor.close()
    return row


def fetch_all(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cursor = get_db().cursor(dictionary=True)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    cursor.close()
    return rows


def execute_write(query: str, params: Any = (), many: bool = False) -> None:
    cursor = get_db().cursor()
    if many:
        cursor.executemany(query, params)
    else:
        cursor.execute(query, params)
    get_db().commit()
    cursor.close()


def init_db() -> None:
    db = raw_connection(use_database=False)
    cursor = db.cursor()
    statements = [part.strip() for part in SCHEMA_PATH.read_text(encoding="utf-8").split(";") if part.strip()]
    for statement in statements:
        cursor.execute(statement)
    db.commit()
    cursor.close()
    db.close()

    db = raw_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute("SELECT COUNT(*) AS total FROM users")
    user_count = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM rooms")
    room_count = cursor.fetchone()["total"]
    cursor.execute("SELECT COUNT(*) AS total FROM bookings")
    booking_count = cursor.fetchone()["total"]

    if user_count == 0:
        cursor.executemany(
            """
            INSERT INTO users (full_name, username, email, phone, city, password_hash, role)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                ("Riya Sharma", "owner", "owner@staysphere.com", "9876543210", "Jaipur", generate_password_hash("owner123"), "Owner"),
                ("Aman Verma", "aman", "aman@example.com", "9123456780", "Delhi", generate_password_hash("aman123"), "Customer"),
            ],
        )
        db.commit()

    cursor.execute("SELECT user_id FROM users WHERE role = 'Owner' ORDER BY user_id LIMIT 1")
    owner_id = cursor.fetchone()["user_id"]
    cursor.execute("SELECT user_id FROM users WHERE role = 'Customer' ORDER BY user_id LIMIT 1")
    customer_id = cursor.fetchone()["user_id"]

    if room_count == 0:
        cursor.executemany(
            """
            INSERT INTO rooms (owner_id, room_number, room_type, capacity, price_per_night, status, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            [
                (owner_id, "101", "Single", 1, 2200, "Available", "Comfortable single room for solo travelers."),
                (owner_id, "205", "Double", 2, 3500, "Available", "Spacious double room with breakfast included."),
                (owner_id, "301", "Suite", 4, 6200, "Maintenance", "Premium suite with lounge area and city view."),
            ],
        )
        db.commit()

    if booking_count == 0:
        cursor.execute(
            """
            INSERT INTO bookings (customer_id, room_id, check_in, check_out, guests_count, total_amount, booking_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (customer_id, 1, "2026-04-05", "2026-04-07", 1, 4400, "Confirmed"),
        )
        db.commit()

    cursor.close()
    db.close()


def fetch_owner_dashboard_data() -> dict[str, Any]:
    rooms = fetch_all("SELECT rooms.*, users.full_name AS owner_name FROM rooms JOIN users ON users.user_id = rooms.owner_id ORDER BY room_number")
    customers = fetch_all("SELECT * FROM users WHERE role = 'Customer' ORDER BY user_id DESC")
    bookings = fetch_all(
        "SELECT bookings.*, users.full_name AS customer_name, users.phone AS customer_phone, rooms.room_number, rooms.room_type FROM bookings JOIN users ON users.user_id = bookings.customer_id JOIN rooms ON rooms.room_id = bookings.room_id ORDER BY bookings.booking_id DESC"
    )
    stats = {
        "rooms": fetch_one("SELECT COUNT(*) AS total FROM rooms")["total"],
        "customers": fetch_one("SELECT COUNT(*) AS total FROM users WHERE role = 'Customer'")["total"],
        "bookings": fetch_one("SELECT COUNT(*) AS total FROM bookings")["total"],
        "available_rooms": fetch_one("SELECT COUNT(*) AS total FROM rooms WHERE status = 'Available'")["total"],
    }
    return {"rooms": rooms, "customers": customers, "bookings": bookings, "stats": stats}


def fetch_customer_dashboard_data(user_id: int) -> dict[str, Any]:
    rooms = fetch_all(
        "SELECT rooms.*, users.full_name AS owner_name FROM rooms JOIN users ON users.user_id = rooms.owner_id ORDER BY CASE rooms.status WHEN 'Available' THEN 0 ELSE 1 END, room_number"
    )
    bookings = fetch_all(
        "SELECT bookings.*, rooms.room_number, rooms.room_type FROM bookings JOIN rooms ON rooms.room_id = bookings.room_id WHERE bookings.customer_id = %s ORDER BY bookings.booking_id DESC",
        (user_id,),
    )
    return {"rooms": rooms, "bookings": bookings}


def sync_room_status(room_id: int) -> None:
    active_booking = fetch_one(
        "SELECT booking_id FROM bookings WHERE room_id = %s AND booking_status IN ('Confirmed', 'Checked In') LIMIT 1",
        (room_id,),
    )
    execute_write(
        "UPDATE rooms SET status = CASE WHEN status = 'Maintenance' THEN status ELSE %s END WHERE room_id = %s",
        ("Booked" if active_booking else "Available", room_id),
    )
