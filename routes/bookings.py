"""Ticket reservation, confirmation, and booking-history routes."""
from decimal import Decimal, ROUND_HALF_UP
import secrets

from flask import Blueprint, abort, flash, redirect, render_template, request, session, url_for
from mysql.connector import Error

from database.db import get_db_connection
from utils.decorators import login_required

bookings_bp = Blueprint("bookings", __name__, url_prefix="/bookings")


def get_event_for_booking(event_id):
    """Read an event with presentation-ready time values."""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT events.*, TIMESTAMP(event_date, event_time) <= NOW() AS has_started, TIME_FORMAT(event_time, '%h:%i %p') AS event_time_display FROM events WHERE id = %s",
            (event_id,),
        )
        event = cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    if not event:
        abort(404)
    return event


def new_booking_code():
    """Generate a short, human-friendly 12-character booking identifier."""
    return f"BK{secrets.token_hex(5).upper()}"


@bookings_bp.route("/events/<int:event_id>/book", methods=["GET", "POST"])
@login_required
def create_booking(event_id):
    """Reserve tickets atomically and create a confirmed booking."""
    event = get_event_for_booking(event_id)
    if request.method == "GET":
        return render_template("booking.html", event=event)

    quantity_text = request.form.get("quantity", "").strip()
    try:
        quantity = int(quantity_text)
        if quantity < 1 or str(quantity) != quantity_text:
            raise ValueError
    except ValueError:
        flash("Ticket quantity must be a whole number of at least 1.", "danger")
        return render_template("booking.html", event=event), 400

    connection = cursor = None
    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)
        # Lock the event row until its availability and booking record are updated together.
        cursor.execute("SELECT id, title, ticket_price, available_seats, TIMESTAMP(event_date, event_time) <= NOW() AS has_started FROM events WHERE id = %s FOR UPDATE", (event_id,))
        locked_event = cursor.fetchone()
        if not locked_event:
            connection.rollback()
            abort(404)
        if locked_event["has_started"]:
            connection.rollback()
            flash("Booking is closed because this event has already started.", "warning")
            return redirect(url_for("events.event_details", event_id=event_id))
        if locked_event["available_seats"] == 0:
            connection.rollback()
            flash("This event is sold out.", "danger")
            return redirect(url_for("events.event_details", event_id=event_id))
        if quantity > locked_event["available_seats"]:
            connection.rollback()
            event["available_seats"] = locked_event["available_seats"]
            flash(f"Only {locked_event['available_seats']} seats are available.", "danger")
            return render_template("booking.html", event=event), 400

        total_amount = (Decimal(locked_event["ticket_price"]) * quantity).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if total_amount > Decimal("99999999.99"):
            connection.rollback()
            flash("This booking exceeds the supported total. Please select fewer tickets.", "danger")
            return render_template("booking.html", event=event), 400
        booking_code = new_booking_code()
        # The unique index is retained as the final safeguard for the extremely unlikely code collision.
        cursor.execute("SELECT id FROM bookings WHERE booking_code = %s", (booking_code,))
        while cursor.fetchone():
            booking_code = new_booking_code()
            cursor.execute("SELECT id FROM bookings WHERE booking_code = %s", (booking_code,))
        cursor.execute(
            "INSERT INTO bookings (booking_code, user_id, event_id, ticket_quantity, total_amount) VALUES (%s, %s, %s, %s, %s)",
            (booking_code, session["user_id"], event_id, quantity, total_amount),
        )
        cursor.execute(
            "UPDATE events SET available_seats = available_seats - %s WHERE id = %s AND available_seats >= %s",
            (quantity, event_id, quantity),
        )
        if cursor.rowcount != 1:
            raise Error("Could not reserve the requested seats.")
        connection.commit()
    except Error:
        if connection:
            connection.rollback()
        flash("Your booking could not be completed. Please try again.", "danger")
        return render_template("booking.html", event=event), 500
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return redirect(url_for("bookings.booking_confirmation", booking_code=booking_code))


@bookings_bp.get("/")
@login_required
def my_bookings():
    """Show bookings belonging to the signed-in user only."""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT bookings.*, events.title, events.event_date, TIME_FORMAT(events.event_time, '%h:%i %p') AS event_time_display
               FROM bookings JOIN events ON bookings.event_id = events.id
               WHERE bookings.user_id = %s ORDER BY bookings.booked_at DESC""",
            (session["user_id"],),
        )
        bookings = cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return render_template("my-bookings.html", bookings=bookings)


@bookings_bp.get("/<booking_code>")
@login_required
def booking_confirmation(booking_code):
    """Show one confirmation only when the booking belongs to the current user."""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT bookings.*, users.name AS user_name, users.email AS user_email, events.title, events.event_date,
                      TIME_FORMAT(events.event_time, '%h:%i %p') AS event_time_display,
                      events.venue, events.city, bookings.total_amount / bookings.ticket_quantity AS ticket_price, events.image_filename
               FROM bookings JOIN users ON bookings.user_id = users.id
               JOIN events ON bookings.event_id = events.id
               WHERE bookings.booking_code = %s AND bookings.user_id = %s""",
            (booking_code, session["user_id"]),
        )
        booking = cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    if not booking:
        abort(404)
    return render_template("booking-confirmation.html", booking=booking)
