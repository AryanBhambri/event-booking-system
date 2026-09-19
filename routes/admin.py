"""Admin-only dashboard, event management, and reporting routes."""
import csv
from datetime import datetime
from io import StringIO

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, session, url_for
from mysql.connector import Error

from database.db import get_db_connection
from utils.decorators import admin_required
from utils.event_helpers import remove_event_image, save_event_image, validate_event_form

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def csv_cell(value):
    """Keep user-controlled text from becoming a spreadsheet formula."""
    if isinstance(value, str) and value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")):
        return "'" + value
    return value


def booking_report_filters():
    """Build safe parameterized WHERE conditions for the booking report."""
    event_id = request.args.get("event_id", "").strip()
    status = request.args.get("status", "").strip()
    booking_date = request.args.get("date", "").strip()
    conditions, parameters = [], []
    filters = {"event_id": event_id, "status": status, "date": booking_date}
    if event_id:
        try:
            event_id = int(event_id)
            if event_id < 1:
                raise ValueError
            conditions.append("bookings.event_id = %s")
            parameters.append(event_id)
        except ValueError:
            filters["event_id"] = ""
    if status in {"confirmed", "cancelled"}:
        conditions.append("bookings.status = %s")
        parameters.append(status)
    else:
        filters["status"] = ""
    if booking_date:
        try:
            datetime.strptime(booking_date, "%Y-%m-%d")
            conditions.append("DATE(bookings.booked_at) = %s")
            parameters.append(booking_date)
        except ValueError:
            filters["date"] = ""
    return conditions, parameters, filters


def get_booking_report():
    """Return filtered booking-report rows and the available event filter choices."""
    conditions, parameters, filters = booking_report_filters()
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            f"""SELECT bookings.booking_code, bookings.ticket_quantity, bookings.total_amount, bookings.booked_at, bookings.status,
                       users.name AS user_name, users.email AS user_email, events.title AS event_title
                FROM bookings JOIN users ON bookings.user_id = users.id JOIN events ON bookings.event_id = events.id
                {where_clause} ORDER BY bookings.booked_at DESC""",
            tuple(parameters),
        )
        rows = cursor.fetchall()
        cursor.execute("SELECT id, title FROM events ORDER BY event_date DESC, title")
        events = cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return rows, events, filters


@admin_bp.get("/")
@admin_required
def index():
    """Show admin-only booking and event analytics from the live database."""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT (SELECT COUNT(*) FROM users) AS total_users,
                      (SELECT COUNT(*) FROM events) AS total_events,
                      (SELECT COUNT(*) FROM bookings) AS total_bookings,
                      (SELECT COALESCE(SUM(ticket_quantity), 0) FROM bookings WHERE status = 'confirmed') AS total_tickets,
                      (SELECT COALESCE(SUM(total_amount), 0) FROM bookings WHERE status = 'confirmed') AS total_revenue,
                      (SELECT COUNT(DISTINCT user_id) FROM bookings WHERE status = 'confirmed') AS active_users"""
        )
        summary = cursor.fetchone()
        cursor.execute(
            """SELECT events.id, events.title, events.event_date, events.venue, events.city, events.total_seats, events.available_seats,
                      COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN bookings.ticket_quantity ELSE 0 END), 0) AS tickets_sold
               FROM events LEFT JOIN bookings ON bookings.event_id = events.id
               WHERE events.event_date >= CURDATE()
               GROUP BY events.id, events.title, events.event_date, events.venue, events.city, events.total_seats, events.available_seats
               ORDER BY events.event_date, events.event_time LIMIT 8"""
        )
        upcoming_events = cursor.fetchall()
        cursor.execute(
            """SELECT bookings.booking_code, bookings.ticket_quantity, bookings.total_amount, bookings.booked_at, bookings.status,
                      users.name AS user_name, events.title AS event_title
               FROM bookings JOIN users ON bookings.user_id = users.id JOIN events ON bookings.event_id = events.id
               ORDER BY bookings.booked_at DESC LIMIT 8"""
        )
        recent_bookings = cursor.fetchall()
        cursor.execute(
            """SELECT events.id, events.title, events.total_seats, events.available_seats,
                      COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN bookings.ticket_quantity ELSE 0 END), 0) AS tickets_sold,
                      COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN 1 ELSE 0 END), 0) AS booking_count,
                      COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN bookings.total_amount ELSE 0 END), 0) AS revenue
               FROM events LEFT JOIN bookings ON bookings.event_id = events.id
               GROUP BY events.id, events.title, events.total_seats, events.available_seats
               ORDER BY events.event_date DESC, events.id DESC"""
        )
        event_statistics = cursor.fetchall()
        cursor.execute("SELECT name, email, created_at FROM users ORDER BY created_at DESC LIMIT 6")
        recent_users = cursor.fetchall()
        cursor.execute(
            """SELECT users.name, users.email, COUNT(bookings.id) AS booking_count
               FROM users LEFT JOIN bookings ON bookings.user_id = users.id
               GROUP BY users.id, users.name, users.email ORDER BY booking_count DESC, users.created_at DESC LIMIT 6"""
        )
        user_activity = cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()

    chart_data = {
        "labels": [row["title"] for row in event_statistics],
        "bookings": [int(row["booking_count"]) for row in event_statistics],
        "tickets": [int(row["tickets_sold"]) for row in event_statistics],
        "revenue": [float(row["revenue"]) for row in event_statistics],
    }
    return render_template("admin/index.html", summary=summary, upcoming_events=upcoming_events, recent_bookings=recent_bookings, event_statistics=event_statistics, recent_users=recent_users, user_activity=user_activity, chart_data=chart_data)


@admin_bp.get("/reports/bookings")
@admin_required
def booking_report():
    """Display an admin-only filterable booking summary."""
    rows, events, filters = get_booking_report()
    return render_template("admin/booking-report.html", rows=rows, events=events, filters=filters)


@admin_bp.get("/reports/bookings/export")
@admin_required
def export_booking_report():
    """Export the filtered booking summary as a safe, password-free CSV."""
    rows, _, _ = get_booking_report()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Booking ID", "User", "Email", "Event", "Tickets", "Amount", "Booking Date", "Status"])
    for row in rows:
        writer.writerow([csv_cell(value) for value in [row["booking_code"], row["user_name"], row["user_email"], row["event_title"], row["ticket_quantity"], row["total_amount"], row["booked_at"].strftime("%Y-%m-%d %H:%M"), row["status"]]])
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=evently-booking-report.csv"})


@admin_bp.get("/reports/events")
@admin_required
def event_report():
    """Display event capacity and revenue reports using booking aggregates."""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT events.title, events.event_date, events.venue, events.city, events.total_seats, events.available_seats,
                      COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN bookings.ticket_quantity ELSE 0 END), 0) AS tickets_sold,
                      COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN 1 ELSE 0 END), 0) AS booking_count,
                      COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN bookings.total_amount ELSE 0 END), 0) AS revenue
               FROM events LEFT JOIN bookings ON bookings.event_id = events.id
               GROUP BY events.id, events.title, events.event_date, events.venue, events.city, events.total_seats, events.available_seats
               ORDER BY events.event_date DESC, events.id DESC"""
        )
        rows = cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return render_template("admin/event-report.html", rows=rows)


@admin_bp.get("/reports/events/export")
@admin_required
def export_event_report():
    """Export appropriate event performance values as CSV."""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("""SELECT events.title, events.event_date, events.venue, events.city, events.total_seats, events.available_seats, COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN bookings.ticket_quantity ELSE 0 END), 0), COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN 1 ELSE 0 END), 0), COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN bookings.total_amount ELSE 0 END), 0) FROM events LEFT JOIN bookings ON bookings.event_id = events.id GROUP BY events.id, events.title, events.event_date, events.venue, events.city, events.total_seats, events.available_seats ORDER BY events.event_date DESC, events.id DESC""")
        rows = cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Event", "Date", "Venue", "City", "Total Seats", "Available Seats", "Tickets Sold", "Bookings", "Revenue"])
    writer.writerows([csv_cell(value) for value in row] for row in rows)
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=evently-event-report.csv"})


@admin_bp.get("/reports/users")
@admin_required
def user_report():
    """Display a registration summary without sensitive credential fields."""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT name, email, role, created_at FROM users ORDER BY created_at DESC")
        rows = cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return render_template("admin/user-report.html", rows=rows)


@admin_bp.get("/reports/users/export")
@admin_required
def export_user_report():
    """Export registration data only; password hashes are never selected."""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT name, email, role, created_at FROM users ORDER BY created_at DESC")
        rows = cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Name", "Email", "Role", "Registration Date"])
    writer.writerows([csv_cell(value) for value in row] for row in rows)
    return Response(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment; filename=evently-registration-report.csv"})


def get_event_or_404(event_id):
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT events.*, TIME_FORMAT(event_time, '%H:%i') AS event_time_input, TIME_FORMAT(event_time, '%h:%i %p') AS event_time_display FROM events WHERE id = %s", (event_id,))
        event = cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    if not event:
        abort(404)
    return event


@admin_bp.get("/events")
@admin_required
def manage_events():
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT events.*, TIME_FORMAT(event_time, '%H:%i') AS event_time_input, TIME_FORMAT(event_time, '%h:%i %p') AS event_time_display, CASE WHEN event_date >= CURDATE() THEN 'Upcoming' ELSE 'Past' END AS event_status FROM events ORDER BY event_date, event_time")
        events = cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return render_template("admin/events.html", events=events)


@admin_bp.route("/events/create", methods=["GET", "POST"])
@admin_required
def create_event():
    if request.method == "POST":
        values, errors = validate_event_form(request.form)
        image_filename, image_error = save_event_image(request.files.get("image"))
        if image_error:
            errors.append(image_error)
        if errors:
            if image_filename:
                remove_event_image(image_filename)
            for error in errors:
                flash(error, "danger")
            return render_template("admin/event-form.html", event=None, form_title="Create event"), 400
        connection = cursor = None
        try:
            connection = get_db_connection()
            cursor = connection.cursor()
            cursor.execute(
                """INSERT INTO events (title, description, category, event_date, event_time, venue, city, ticket_price, total_seats, available_seats, image_filename, created_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (values["title"], values["description"], values["category"], values["parsed_date"], values["parsed_time"], values["venue"], values["city"], values["price"], values["seat_count"], values["seat_count"], image_filename, session["user_id"]),
            )
            connection.commit()
        except Error:
            if connection:
                connection.rollback()
            if image_filename:
                remove_event_image(image_filename)
            flash("The event could not be created. Please try again.", "danger")
            return render_template("admin/event-form.html", event=None, form_title="Create event"), 500
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
        flash("Event created successfully.", "success")
        return redirect(url_for("admin.manage_events"))
    return render_template("admin/event-form.html", event=None, form_title="Create event")


@admin_bp.route("/events/<int:event_id>/edit", methods=["GET", "POST"])
@admin_required
def edit_event(event_id):
    event = get_event_or_404(event_id)
    if request.method == "POST":
        values, errors = validate_event_form(request.form)
        new_image, image_error = save_event_image(request.files.get("image"))
        if image_error:
            errors.append(image_error)
        booked_seats = event["total_seats"] - event["available_seats"]
        if values["seat_count"] is not None and values["seat_count"] < booked_seats:
            errors.append(f"Total seats cannot be lower than the {booked_seats} seat(s) already booked.")
        if errors:
            if new_image:
                remove_event_image(new_image)
            for error in errors:
                flash(error, "danger")
            return render_template("admin/event-form.html", event=event, form_title="Edit event"), 400
        image_filename = new_image or event["image_filename"]
        available_seats = values["seat_count"] - booked_seats
        connection = cursor = None
        try:
            connection = get_db_connection()
            connection.start_transaction()
            cursor = connection.cursor(dictionary=True)
            cursor.execute("SELECT total_seats, available_seats, image_filename FROM events WHERE id = %s FOR UPDATE", (event_id,))
            current_event = cursor.fetchone()
            if not current_event:
                connection.rollback()
                if new_image:
                    remove_event_image(new_image)
                abort(404)
            booked_seats = current_event["total_seats"] - current_event["available_seats"]
            if values["seat_count"] < booked_seats:
                connection.rollback()
                if new_image:
                    remove_event_image(new_image)
                flash(f"Total seats cannot be lower than the {booked_seats} seat(s) already booked.", "danger")
                return render_template("admin/event-form.html", event=event, form_title="Edit event"), 400
            available_seats = values["seat_count"] - booked_seats
            image_filename = new_image or current_event["image_filename"]
            cursor.execute(
                """UPDATE events SET title=%s, description=%s, category=%s, event_date=%s, event_time=%s, venue=%s, city=%s,
                   ticket_price=%s, total_seats=%s, available_seats=%s, image_filename=%s WHERE id=%s""",
                (values["title"], values["description"], values["category"], values["parsed_date"], values["parsed_time"], values["venue"], values["city"], values["price"], values["seat_count"], available_seats, image_filename, event_id),
            )
            connection.commit()
        except Error:
            if connection:
                connection.rollback()
            if new_image:
                remove_event_image(new_image)
            flash("The event could not be updated. Please try again.", "danger")
            return render_template("admin/event-form.html", event=event, form_title="Edit event"), 500
        finally:
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()
        if new_image:
            remove_event_image(current_event["image_filename"])
        flash("Event updated successfully.", "success")
        return redirect(url_for("admin.manage_events"))
    return render_template("admin/event-form.html", event=event, form_title="Edit event")


@admin_bp.post("/events/<int:event_id>/delete")
@admin_required
def delete_event(event_id):
    event = get_event_or_404(event_id)
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("DELETE FROM events WHERE id = %s", (event_id,))
        connection.commit()
    except Error as error:
        if connection:
            connection.rollback()
        if getattr(error, "errno", None) == 1451:
            flash("This event has bookings and cannot be deleted.", "danger")
        else:
            flash("The event could not be deleted. Please try again.", "danger")
        return redirect(url_for("admin.manage_events"))
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    remove_event_image(event["image_filename"])
    flash("Event deleted successfully.", "success")
    return redirect(url_for("admin.manage_events"))
