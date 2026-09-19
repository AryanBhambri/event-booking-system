-- Run this file in MySQL before starting the application.
CREATE DATABASE IF NOT EXISTS event_booking_system
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE event_booking_system;

CREATE TABLE IF NOT EXISTS users (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(150) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('user', 'admin') NOT NULL DEFAULT 'user',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS events (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT NOT NULL,
    category VARCHAR(80) NOT NULL,
    event_date DATE NOT NULL,
    event_time TIME NOT NULL,
    venue VARCHAR(150) NOT NULL,
    city VARCHAR(100) NOT NULL,
    ticket_price DECIMAL(10,2) NOT NULL CHECK (ticket_price >= 0),
    total_seats INT UNSIGNED NOT NULL CHECK (total_seats > 0),
    available_seats INT UNSIGNED NOT NULL,
    image_filename VARCHAR(255) NULL,
    created_by INT UNSIGNED NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    CONSTRAINT chk_events_available_seats
        CHECK (available_seats <= total_seats),
    CONSTRAINT fk_events_creator FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE RESTRICT,
    INDEX idx_events_date (event_date),
    INDEX idx_events_category (category),
    INDEX idx_events_city (city)
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS bookings (
    id INT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    booking_code CHAR(12) NOT NULL UNIQUE,
    user_id INT UNSIGNED NOT NULL,
    event_id INT UNSIGNED NOT NULL,
    ticket_quantity INT UNSIGNED NOT NULL CHECK (ticket_quantity > 0),
    total_amount DECIMAL(10,2) NOT NULL CHECK (total_amount >= 0),
    status ENUM('confirmed', 'cancelled') NOT NULL DEFAULT 'confirmed',
    booked_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_bookings_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE RESTRICT,
    CONSTRAINT fk_bookings_event FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE RESTRICT,
    INDEX idx_bookings_user (user_id),
    INDEX idx_bookings_event (event_id),
    INDEX idx_bookings_date (booked_at)
) ENGINE=InnoDB;
