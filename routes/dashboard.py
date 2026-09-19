"""Personal booking dashboard for the authenticated user."""
from flask import Blueprint, render_template

from database.db import get_db_connection
from utils.decorators import login_required

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.get("/")
@login_required
def index():
    """Show only the signed-in user's booking activity and history."""
    from flask import session

    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """SELECT COUNT(*) AS total_bookings,
                      COALESCE(SUM(CASE WHEN events.event_date >= CURDATE() THEN 1 ELSE 0 END), 0) AS upcoming_bookings,
                      COALESCE(SUM(CASE WHEN events.event_date < CURDATE() THEN 1 ELSE 0 END), 0) AS past_bookings,
                      COALESCE(SUM(CASE WHEN bookings.status = 'confirmed' THEN bookings.ticket_quantity ELSE 0 END), 0) AS total_tickets
               FROM bookings JOIN events ON bookings.event_id = events.id WHERE bookings.user_id = %s""",
            (session["user_id"],),
        )
        summary = cursor.fetchone()
        cursor.execute(
            """SELECT bookings.*, events.title, events.event_date, events.venue, events.city, events.image_filename,
                      TIME_FORMAT(events.event_time, '%h:%i %p') AS event_time_display
               FROM bookings JOIN events ON bookings.event_id = events.id
               WHERE bookings.user_id = %s AND events.event_date >= CURDATE()
               ORDER BY events.event_date, events.event_time""",
            (session["user_id"],),
        )
        upcoming_bookings = cursor.fetchall()
        cursor.execute(
            """SELECT bookings.*, events.title, events.event_date,
                      TIME_FORMAT(events.event_time, '%h:%i %p') AS event_time_display
               FROM bookings JOIN events ON bookings.event_id = events.id
               WHERE bookings.user_id = %s AND events.event_date < CURDATE()
               ORDER BY events.event_date DESC, bookings.booked_at DESC""",
            (session["user_id"],),
        )
        booking_history = cursor.fetchall()
        cursor.execute(
            """SELECT bookings.*, events.title, events.event_date
               FROM bookings JOIN events ON bookings.event_id = events.id
               WHERE bookings.user_id = %s ORDER BY bookings.booked_at DESC LIMIT 5""",
            (session["user_id"],),
        )
        recent_bookings = cursor.fetchall()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return render_template("dashboard.html", summary=summary, upcoming_bookings=upcoming_bookings, booking_history=booking_history, recent_bookings=recent_bookings)
