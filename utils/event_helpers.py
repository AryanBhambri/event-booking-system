"""Validation and safe image-file helpers for event management."""
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from uuid import uuid4
import warnings

from flask import current_app
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
    """Validate and save an optional banner, returning its generated filename."""
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

    filename = f"{uuid4().hex}.{extension}"
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"])
    try:
        upload_folder.mkdir(parents=True, exist_ok=True)
        file_storage.save(upload_folder / filename)
    except OSError:
        current_app.logger.error("Could not save an event image.")
        return None, "The image could not be saved. Please try again."
    return filename, None


def remove_event_image(filename):
    """Delete a stored event banner only when it is inside the upload folder."""
    if not filename:
        return
    upload_folder = Path(current_app.config["UPLOAD_FOLDER"]).resolve()
    file_path = (upload_folder / filename).resolve()
    if file_path.parent == upload_folder and file_path.is_file():
        file_path.unlink()
