"""Public event discovery, search, filters, and details."""
from flask import Blueprint, abort, render_template, request

from database.db import get_db_connection

events_bp = Blueprint("events", __name__, url_prefix="/events")


@events_bp.get("/")
def list_events():
    """Show upcoming events with optional search/category/city filters."""
    search = request.args.get("search", "").strip()
    category = request.args.get("category", "").strip()
    city = request.args.get("city", "").strip()
    upcoming = request.args.getlist("upcoming")[-1:] != ["0"]
    conditions, parameters = [], []
    if search:
        conditions.append("(title LIKE %s OR category LIKE %s OR city LIKE %s)")
        parameters.extend([f"%{search}%"] * 3)
    if category:
        conditions.append("category = %s")
        parameters.append(category)
    if city:
        conditions.append("city = %s")
        parameters.append(city)
    if upcoming:
        conditions.append("event_date >= CURDATE()")
    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(f"SELECT events.*, TIMESTAMP(event_date, event_time) <= NOW() AS has_started, TIME_FORMAT(event_time, '%H:%i') AS event_time_input, TIME_FORMAT(event_time, '%h:%i %p') AS event_time_display FROM events {where_clause} ORDER BY event_date, event_time", tuple(parameters))
        events = cursor.fetchall()
        cursor.execute("SELECT DISTINCT category FROM events ORDER BY category")
        categories = [row["category"] for row in cursor.fetchall()]
        cursor.execute("SELECT DISTINCT city FROM events ORDER BY city")
        cities = [row["city"] for row in cursor.fetchall()]
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return render_template("events.html", events=events, categories=categories, cities=cities, filters={"search": search, "category": category, "city": city, "upcoming": upcoming})


@events_bp.get("/<int:event_id>")
def event_details(event_id):
    """Show one public event without exposing admin controls."""
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute("SELECT events.*, TIMESTAMP(event_date, event_time) <= NOW() AS has_started, TIME_FORMAT(event_time, '%H:%i') AS event_time_input, TIME_FORMAT(event_time, '%h:%i %p') AS event_time_display FROM events WHERE id = %s", (event_id,))
        event = cursor.fetchone()
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    if not event:
        abort(404)
    return render_template("event-details.html", event=event)
