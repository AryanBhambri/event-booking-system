"""Validation and safe image-file helpers for event management."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import uuid4
import re
import warnings

import cloudinary.uploader
from flask import current_app, url_for
from PIL import Image, UnidentifiedImageError
from werkzeug.utils import secure_filename


def validate_event_form(form):
    """Validate event fields and return cleaned values plus any errors."""
    values = {
        "title": form.get("title", "").strip(),
        "description": form.get("description", "").strip(),
        "category": form.get("category", "").strip(),
        "event_date": form.get("event_date", "").strip(),
        "event_time": form.get("event_time", "").strip(),
        "venue": form.get("venue", "").strip(),
        "city": form.get("city", "").strip(),
        "ticket_price": form.get("ticket_price", "").strip(),
        "total_seats": form.get("total_seats", "").strip(),
    }
    errors = []
    for field, label, maximum in (("title", "Title", 200), ("category", "Category", 80), ("venue", "Venue", 150), ("city", "City", 100)):
        if not values[field] or len(values[field]) > maximum:
            errors.append(f"{label} is required and must be no more than {maximum} characters.")
    if len(values["description"]) < 10 or len(values["description"].encode("utf-8")) > 65535:
        errors.append("Description must contain at least 10 characters and fit within 65,535 bytes.")

    try:
        parsed_date = datetime.strptime(values["event_date"], "%Y-%m-%d").date()
        if parsed_date < date.today():
            errors.append("Event date cannot be in the past.")
    except ValueError:
        errors.append("Enter a valid event date.")
        parsed_date = None
    try:
        parsed_time = datetime.strptime(values["event_time"], "%H:%M").time()
    except ValueError:
        errors.append("Enter a valid event time.")
        parsed_time = None
    try:
        price = Decimal(values["ticket_price"])
        if not price.is_finite() or price > Decimal("99999999.99"):
            errors.append("Enter a finite ticket price no greater than 99,999,999.99.")
        elif price < 0:
            errors.append("Ticket price cannot be negative.")
        elif price.as_tuple().exponent < -2:
            errors.append("Ticket price can have at most two decimal places.")
    except (InvalidOperation, ValueError):
        errors.append("Enter a valid ticket price.")
        price = None
    try:
        total_seats = int(values["total_seats"])
        if not 1 <= total_seats <= 4294967295:
            errors.append("Total seats must be between 1 and 4,294,967,295.")
    except ValueError:
        errors.append("Enter a whole number for total seats.")
        total_seats = None

    values.update({"parsed_date": parsed_date, "parsed_time": parsed_time, "price": price, "seat_count": total_seats})
    return values, errors


def save_event_image(file_storage):
    """Validate an optional banner, returning its unchanged Cloudinary HTTPS URL."""
    if not file_storage or not file_storage.filename:
        return None, None
    original_name = secure_filename(file_storage.filename)
    extension = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""
    if not original_name or extension not in current_app.config["ALLOWED_IMAGE_EXTENSIONS"]:
        return None, "Upload a PNG, JPG, JPEG, GIF, or WEBP image."
    if file_storage.mimetype and not file_storage.mimetype.startswith("image/"):
        return None, "The uploaded file must be an image."

    file_storage.stream.seek(0, 2)
    size = file_storage.stream.tell()
    file_storage.stream.seek(0)
    if size > current_app.config["MAX_IMAGE_SIZE"]:
        return None, "Choose an image no larger than 5 MB."
    formats = {"png": "PNG", "jpg": "JPEG", "jpeg": "JPEG", "gif": "GIF", "webp": "WEBP"}
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(file_storage.stream, formats=list(set(formats.values()))) as image:
                if image.format != formats[extension]:
                    return None, "The image contents must match the file extension."
                image.verify()
            file_storage.stream.seek(0)
            with Image.open(file_storage.stream, formats=list(set(formats.values()))) as image:
                image.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return None, "Upload a valid, undamaged image."
    finally:
        file_storage.stream.seek(0)

    options = _cloudinary_options()
    if not all(options[key] for key in ("cloud_name", "api_key", "api_secret")):
        return None, "Banner uploads are not configured. Please contact the site administrator."
    public_id = f"evently/event-banners/{uuid4().hex}"
    try:
        result = cloudinary.uploader.upload(
            file_storage.stream,
            public_id=public_id,
            asset_folder="evently/event-banners",
            overwrite=False,
            unique_filename=False,
            use_filename=False,
            **options,
        )
    except Exception:
        # SDK/network failures must not reach the event's database transaction.
        # Do not log exception text: it may contain credentials or request details.
        current_app.logger.error("Could not upload an event banner to Cloudinary.")
        return None, "The banner could not be uploaded. Please try again."

    # Never remove a pre-existing asset, even in the unlikely event of an ID collision.
    if not isinstance(result, dict) or result.get("existing") or result.get("public_id") != public_id:
        return None, "The banner upload could not be verified. Please try again."
    image_url = result.get("secure_url")
    if isinstance(image_url, str) and len(image_url) > 255:
        _destroy_cloudinary_image(public_id)
        return None, "The banner URL exceeds the 255-character storage limit. The event was not saved. Please contact the site administrator."
    if owned_event_image_id(image_url) != public_id:
        _destroy_cloudinary_image(public_id)
        return None, "The banner upload did not return a valid secure image URL. Please try again."
    return image_url, None


def _cloudinary_options():
    """Pass app-specific credentials explicitly; do not mutate SDK global config."""
    return {
        "cloud_name": current_app.config["CLOUDINARY_CLOUD_NAME"],
        "api_key": current_app.config["CLOUDINARY_API_KEY"],
        "api_secret": current_app.config["CLOUDINARY_API_SECRET"],
        "secure": True,
        "resource_type": "image",
        "type": "upload",
        "timeout": 30,
    }


def owned_event_image_id(image_url):
    """Recognize only canonical URLs for UUID banners in this app's account."""
    cloud_name = current_app.config["CLOUDINARY_CLOUD_NAME"]
    if not cloud_name or not isinstance(image_url, str):
        return None
    match = re.fullmatch(
        r"https://res\.cloudinary\.com/" + re.escape(cloud_name)
        + r"/image/upload/v[0-9]+/(evently/event-banners/[0-9a-f]{32})\.(?:png|jpg|jpeg|gif|webp)",
        image_url,
    )
    return match.group(1) if match else None


def event_image_url(image_filename):
    """Resolve external HTTPS banners, legacy filenames, and the existing default."""
    if not image_filename:
        return url_for("static", filename="images/default-event.svg")
    if image_filename.startswith("https://"):
        return image_filename
    return url_for("static", filename="uploads/" + image_filename)


def _destroy_cloudinary_image(public_id):
    """Best-effort cleanup; a storage outage must not undo a committed DB change."""
    try:
        result = cloudinary.uploader.destroy(public_id, invalidate=True, **_cloudinary_options())
        if result.get("result") not in {"ok", "not found"}:
            current_app.logger.warning("An unused Cloudinary event banner could not be deleted: %s", public_id)
    except Exception:
        current_app.logger.warning("An unused Cloudinary event banner could not be deleted: %s", public_id)


def remove_event_image(filename):
    """Delete only owned Cloudinary banners; retain all legacy local files."""
    public_id = owned_event_image_id(filename)
    if public_id:
        _destroy_cloudinary_image(public_id)


def remove_unreferenced_event_image(filename):
    """Keep shared banners; leave the file intact if references cannot be checked."""
    if not filename:
        return
    from database.db import get_db_connection
    from mysql.connector import Error

    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor()
        cursor.execute("SELECT id FROM events WHERE image_filename = %s LIMIT 1", (filename,))
        if cursor.fetchone() is None:
            remove_event_image(filename)
    except Error:
        current_app.logger.warning("Unused banner cleanup deferred: references could not be checked.")
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
