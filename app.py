from __future__ import annotations

from functools import wraps
from pathlib import Path
from typing import Any, Callable

import mysql.connector
from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from mysql.connector import Error
from werkzeug.security import check_password_hash, generate_password_hash


SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"
MYSQL_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "Dhanuj@1356",
    "database": "hotel_management",
}
OWNER_DASHBOARD_ROOMS = "owner_dashboard#rooms"
OWNER_DASHBOARD_BOOKINGS = "owner_dashboard#bookings"
CUSTOMER_DASHBOARD_BOOKINGS = "customer_dashboard#bookings"

app = Flask(__name__)
app.config["SECRET_KEY"] = "hotel-management-demo-key"


def raw_connection(use_database: bool = True) -> mysql.connector.MySQLConnection:
    config = MYSQL_CONFIG if use_database else {k: v for k, v in MYSQL_CONFIG.items() if k != "database"}
    return mysql.connector.connect(**config)


def get_db() -> mysql.connector.MySQLConnection:
    if "db" not in g:
        g.db = raw_connection()
    return g.db


@app.teardown_appcontext
def close_db(_: Any) -> None:
    db = g.pop("db", None)
    if db is not None and db.is_connected():
        db.close()


def go(endpoint: str) -> Any:
    if "#" in endpoint:
        name, anchor = endpoint.split("#", 1)
        return redirect(f"{url_for(name)}#{anchor}")
    return redirect(url_for(endpoint))


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


def get_current_user() -> dict[str, Any] | None:
    user_id = session.get("user_id")
    return fetch_one("SELECT * FROM users WHERE user_id = %s", (user_id,)) if user_id else None


@app.context_processor
def inject_session_user() -> dict[str, Any]:
    return {"current_user": get_current_user()}


def login_required(view: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(view)
    def wrapped_view(*args: Any, **kwargs: Any) -> Any:
        if get_current_user() is None:
            flash("Please log in first.")
            return go("login")
        return view(*args, **kwargs)

    return wrapped_view


def role_required(role: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def decorator(view: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(view)
        def wrapped_view(*args: Any, **kwargs: Any) -> Any:
            user = get_current_user()
            if user is None:
                flash("Please log in first.")
                return go("login")
            if user["role"] != role:
                flash("You do not have permission to open that page.")
                return go("dashboard")
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def dashboard_redirect() -> Any:
    user = get_current_user()
    if user is None:
        return go("login")
    return go("owner_dashboard" if user["role"] == "Owner" else "customer_dashboard")


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


try:
    init_db()
except Error:
    pass


@app.route("/")
def index() -> Any:
    return go("login")


@app.route("/login", methods=["GET", "POST"])
def login() -> Any:
    if request.method == "POST":
        user = fetch_one("SELECT * FROM users WHERE username = %s", (request.form["username"].strip(),))
        if user is None or not check_password_hash(user["password_hash"], request.form["password"]):
            flash("Invalid username or password.")
            return go("login")
        session.clear()
        session["user_id"] = user["user_id"]
        flash(f"Welcome back, {user['full_name']}.")
        return dashboard_redirect()
    return render_template("login.html")


@app.route("/register", methods=["GET", "POST"])
def register() -> Any:
    if request.method == "POST":
        form = request.form
        try:
            execute_write(
                """
                INSERT INTO users (full_name, username, email, phone, city, password_hash, role)
                VALUES (%s, %s, %s, %s, %s, %s, 'Customer')
                """,
                (form["full_name"].strip(), form["username"].strip(), form["email"].strip(), form["phone"].strip(), form["city"].strip(), generate_password_hash(form["password"])),
            )
        except Error:
            flash("Username or email already exists. Try another one.")
            return go("register")
        flash("Registration successful. Please log in as a customer.")
        return go("login")
    return render_template("register.html")


@app.route("/dashboard")
@login_required
def dashboard() -> Any:
    return dashboard_redirect()


@app.route("/owner/dashboard")
@role_required("Owner")
def owner_dashboard() -> str:
    return render_template("owner_dashboard.html", **fetch_owner_dashboard_data())


@app.route("/customer/dashboard")
@role_required("Customer")
def customer_dashboard() -> str:
    return render_template("customer_dashboard.html", **fetch_customer_dashboard_data(get_current_user()["user_id"]))


@app.get("/logout")
def logout() -> Any:
    session.clear()
    flash("You have been logged out.")
    return go("index")


@app.post("/rooms/add")
@role_required("Owner")
def add_room() -> Any:
    form, owner = request.form, get_current_user()
    try:
        execute_write(
            """
            INSERT INTO rooms (owner_id, room_number, room_type, capacity, price_per_night, status, description)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (owner["user_id"], form["room_number"].strip(), form["room_type"].strip(), form["capacity"], form["price_per_night"], form["status"], form["description"].strip()),
        )
        flash("Room added successfully.")
    except Error:
        flash("Room number already exists.")
    return go(OWNER_DASHBOARD_ROOMS)


@app.post("/rooms/<int:room_id>/update")
@role_required("Owner")
def update_room(room_id: int) -> Any:
    form = request.form
    try:
        execute_write(
            """
            UPDATE rooms SET room_number = %s, room_type = %s, capacity = %s, price_per_night = %s, status = %s, description = %s
            WHERE room_id = %s
            """,
            (form["room_number"].strip(), form["room_type"].strip(), form["capacity"], form["price_per_night"], form["status"], form["description"].strip(), room_id),
        )
        flash("Room updated successfully.")
    except Error:
        flash("Room number already exists.")
    return go(OWNER_DASHBOARD_ROOMS)


@app.post("/rooms/<int:room_id>/delete")
@role_required("Owner")
def delete_room(room_id: int) -> Any:
    if fetch_one("SELECT booking_id FROM bookings WHERE room_id = %s LIMIT 1", (room_id,)):
        flash("Room cannot be deleted because bookings are linked to it.")
        return go(OWNER_DASHBOARD_ROOMS)
    execute_write("DELETE FROM rooms WHERE room_id = %s", (room_id,))
    flash("Room deleted successfully.")
    return go(OWNER_DASHBOARD_ROOMS)


@app.post("/bookings/add")
@role_required("Customer")
def add_booking() -> Any:
    form, user = request.form, get_current_user()
    room = fetch_one("SELECT * FROM rooms WHERE room_id = %s", (form["room_id"],))
    if room is None:
        flash("Selected room does not exist.")
        return go(CUSTOMER_DASHBOARD_BOOKINGS)
    if room["status"] != "Available":
        flash("Only available rooms can be booked.")
        return go(CUSTOMER_DASHBOARD_BOOKINGS)
    if int(form["guests_count"]) > int(room["capacity"]):
        flash("Guest count cannot be more than room capacity.")
        return go(CUSTOMER_DASHBOARD_BOOKINGS)
    if form["check_out"] <= form["check_in"]:
        flash("Check-out date must be after check-in date.")
        return go(CUSTOMER_DASHBOARD_BOOKINGS)
    total_amount = float(room["price_per_night"]) * int(form["nights"])
    execute_write(
        """
        INSERT INTO bookings (customer_id, room_id, check_in, check_out, guests_count, total_amount, booking_status)
        VALUES (%s, %s, %s, %s, %s, %s, 'Confirmed')
        """,
        (user["user_id"], form["room_id"], form["check_in"], form["check_out"], form["guests_count"], total_amount),
    )
    sync_room_status(int(form["room_id"]))
    flash("Booking created successfully.")
    return go(CUSTOMER_DASHBOARD_BOOKINGS)


@app.post("/bookings/<int:booking_id>/status")
@role_required("Owner")
def update_booking_status(booking_id: int) -> Any:
    booking = fetch_one("SELECT room_id FROM bookings WHERE booking_id = %s", (booking_id,))
    execute_write("UPDATE bookings SET booking_status = %s WHERE booking_id = %s", (request.form["booking_status"], booking_id))
    if booking:
        sync_room_status(booking["room_id"])
    flash("Booking status updated.")
    return go(OWNER_DASHBOARD_BOOKINGS)


@app.post("/bookings/<int:booking_id>/delete")
@login_required
def delete_booking(booking_id: int) -> Any:
    user = get_current_user()
    booking = fetch_one("SELECT * FROM bookings WHERE booking_id = %s", (booking_id,))
    if booking is None:
        flash("Booking not found.")
        return dashboard_redirect()
    if user["role"] == "Customer" and booking["customer_id"] != user["user_id"]:
        flash("You can only cancel your own bookings.")
        return go("customer_dashboard")
    execute_write("DELETE FROM bookings WHERE booking_id = %s", (booking_id,))
    sync_room_status(booking["room_id"])
    flash("Booking deleted successfully.")
    return dashboard_redirect()


if __name__ == "__main__":
    app.run(debug=True)
