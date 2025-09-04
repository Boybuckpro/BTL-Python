CREATE DATABASE product_db;
USE product_db;
CREATE TABLE products (
    id INT AUTO_INCREMENT PRIMARY KEY,
    image_name VARCHAR(255),
    image_path VARCHAR(255),
    image_base64 TEXT,
    product_name VARCHAR(255),
    manufacturer_company VARCHAR(255),
    manufacturer_address TEXT,
    manufacturer_phone VARCHAR(50),
    importer_company VARCHAR(255),
    importer_address TEXT,
    importer_phone VARCHAR(50),
    manufacturing_date DATE,
    expiry_date DATE,
    type VARCHAR(100)
);