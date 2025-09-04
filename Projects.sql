CREATE DATABASE labeling_db;
USE labeling_db;

CREATE TABLE labels (
    id INT AUTO_INCREMENT PRIMARY KEY,
    image_name VARCHAR(255),
    image_path TEXT,
    image_base64 LONGTEXT,
    product_name VARCHAR(255),
    manufacturer_name VARCHAR(255),
    manufacturer_address TEXT,
    manufacturer_phone VARCHAR(50),
    importer_name VARCHAR(255),
    importer_address TEXT,
    importer_phone VARCHAR(50),
    manufacturing_date DATE,
    expiry_date DATE,
    type VARCHAR(50)
);
