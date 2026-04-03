from __future__ import annotations

from typing import Any

from flask import Flask, flash, render_template, request, session
from mysql.connector import Error
from werkzeug.security import check_password_hash, generate_password_hash

from auth_utils import dashboard_redirect, get_current_user, go, inject_session_user, login_required, role_required
from db_utils import close_db, execute_write, fetch_customer_dashboard_data, fetch_one, fetch_owner_dashboard_data, init_db, sync_room_status

OWNER_DASHBOARD_ROOMS = "owner_dashboard#rooms"
OWNER_DASHBOARD_BOOKINGS = "owner_dashboard#bookings"
CUSTOMER_DASHBOARD_BOOKINGS = "customer_dashboard#bookings"

app = Flask(__name__)
app.config["SECRET_KEY"] = "hotel-management-demo-key"
app.teardown_appcontext(lambda _: close_db())
app.context_processor(inject_session_user)

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
