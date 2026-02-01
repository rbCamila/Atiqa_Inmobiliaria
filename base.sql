SET SQL_MODE = "NO_AUTO_VALUE_ON_ZERO";
START TRANSACTION;
SET time_zone = "-05:00";

-- 1. ESTRUCTURA DE TABLAS

-- Tabla de Usuarios (Agentes y Administradores)
CREATE TABLE IF NOT EXISTS `Users` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `email` VARCHAR(150) NOT NULL,
  `password` VARCHAR(255) NOT NULL,
  `fullName` VARCHAR(100) NOT NULL,
  `phone` VARCHAR(20),
  `role` ENUM('ADMIN', 'AGENTE') DEFAULT 'AGENTE',
  `photoUrl` VARCHAR(500) DEFAULT NULL,
  `isActive` TINYINT(1) DEFAULT 1,
  `createdAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `email_unique` (`email`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabla de Clientes (Propietarios y Compradores)
CREATE TABLE IF NOT EXISTS `Clients` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `fullName` VARCHAR(100) NOT NULL,
  `dniRuc` VARCHAR(20),
  `phone` VARCHAR(20) NOT NULL,
  `email` VARCHAR(100),
  `isOwner` TINYINT(1) DEFAULT 1, 
  `notes` TEXT,
  `createdAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabla de Propiedades (Inventario)
CREATE TABLE IF NOT EXISTS `Properties` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `title` VARCHAR(200) NOT NULL,
  `description` TEXT,
  `address` VARCHAR(255),
  `city` VARCHAR(100) DEFAULT 'Ilo',
  `price` DECIMAL(12, 2) NOT NULL,
  `currency` CHAR(3) DEFAULT 'USD',
  `commissionPct` DECIMAL(5, 2) DEFAULT 3.00,
  `status` ENUM('DISPONIBLE', 'RESERVADO', 'VENDIDO', 'ALQUILADO', 'RETIRADO') DEFAULT 'DISPONIBLE',
  `operation` ENUM('VENTA', 'ALQUILER') NOT NULL,
  `agentId` INT NOT NULL,
  `ownerId` INT NOT NULL,
  `createdAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `updatedAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `fk_property_agent` (`agentId`),
  KEY `fk_property_owner` (`ownerId`),
  CONSTRAINT `fk_property_agent` FOREIGN KEY (`agentId`) REFERENCES `Users` (`id`),
  CONSTRAINT `fk_property_owner` FOREIGN KEY (`ownerId`) REFERENCES `Clients` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabla de Documentos (Gestor Documental)
CREATE TABLE IF NOT EXISTS `Documents` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `name` VARCHAR(100),
  `url` VARCHAR(500) NOT NULL,
  `type` ENUM('PARTIDA_REGISTRAL', 'ESCRITURA_PUBLICA', 'HR_PU', 'DNI_PROPIETARIO', 'CONTRATO_FIRMADO', 'OTRO') NOT NULL,
  `propertyId` INT NOT NULL,
  `uploadedAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `fk_document_property` (`propertyId`),
  CONSTRAINT `fk_document_property` FOREIGN KEY (`propertyId`) REFERENCES `Properties` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabla de Ventas / Cierres (Finanzas)
CREATE TABLE IF NOT EXISTS `Sales` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `propertyId` INT NOT NULL,
  `finalPrice` DECIMAL(12, 2) NOT NULL,
  `totalCommission` DECIMAL(10, 2) NOT NULL,
  `listingAgentId` INT NOT NULL,
  
  `isShared` TINYINT(1) DEFAULT 0,
  `externalAgency` VARCHAR(100) DEFAULT NULL,
  `sharedPct` DECIMAL(5, 2) DEFAULT 50.00,
  
  `sellingAgentId` INT DEFAULT NULL,
  
  `closedAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  `notes` TEXT,
  PRIMARY KEY (`id`),
  UNIQUE KEY `property_unique` (`propertyId`),
  CONSTRAINT `fk_sale_property` FOREIGN KEY (`propertyId`) REFERENCES `Properties` (`id`),
  CONSTRAINT `fk_sale_listing_agent` FOREIGN KEY (`listingAgentId`) REFERENCES `Users` (`id`),
  CONSTRAINT `fk_sale_selling_agent` FOREIGN KEY (`sellingAgentId`) REFERENCES `Users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Tabla de Publicaciones Internas (Muro de Novedades)
CREATE TABLE IF NOT EXISTS `InternalPosts` (
  `id` INT NOT NULL AUTO_INCREMENT,
  `title` VARCHAR(150),
  `body` TEXT,
  `category` ENUM('NOTICIA', 'CURSO', 'EVENTO', 'URGENTE') DEFAULT 'NOTICIA',
  `authorId` INT NOT NULL,
  `createdAt` TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  CONSTRAINT `fk_post_author` FOREIGN KEY (`authorId`) REFERENCES `Users` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- 2. TRIGGERS (AUTOMATIZACIÓN)
-- ==========================================================================

DELIMITER //

-- TRIGGER: Actualización Automática de Estado al registrar Venta
DROP TRIGGER IF EXISTS `trg_UpdateStatusOnSale` //
CREATE TRIGGER `trg_UpdateStatusOnSale` AFTER INSERT ON `Sales`
FOR EACH ROW
BEGIN
    DECLARE opType VARCHAR(20);
    
    SELECT operation INTO opType FROM Properties WHERE id = NEW.propertyId;
    
    IF opType = 'VENTA' THEN
        UPDATE Properties SET status = 'VENDIDO' WHERE id = NEW.propertyId;
    ELSE
        UPDATE Properties SET status = 'ALQUILADO' WHERE id = NEW.propertyId;
    END IF;
END //

DELIMITER ;


-- 3. PROCEDIMIENTOS ALMACENADOS (LÓGICA DEL SISTEMA)
-- ==========================================================================

DELIMITER //

-- ----------------------------
-- SP: GESTIÓN DE USUARIOS
-- ----------------------------

DROP PROCEDURE IF EXISTS `sp_User_Create` //
CREATE PROCEDURE `sp_User_Create`(
    IN p_email VARCHAR(150),
    IN p_password VARCHAR(255),
    IN p_fullName VARCHAR(100),
    IN p_phone VARCHAR(20),
    IN p_role VARCHAR(10)
)
BEGIN
    INSERT INTO Users (email, password, fullName, phone, role)
    VALUES (p_email, p_password, p_fullName, p_phone, p_role);
END //

DROP PROCEDURE IF EXISTS `sp_User_List` //
CREATE PROCEDURE `sp_User_List`()
BEGIN
    SELECT id, email, fullName, phone, role, photoUrl, isActive, createdAt 
    FROM Users WHERE isActive = 1;
END //

-- ----------------------------
-- SP: GESTIÓN DE PROPIEDADES
-- ----------------------------

DROP PROCEDURE IF EXISTS `sp_Property_Create` //
CREATE PROCEDURE `sp_Property_Create`(
    IN p_title VARCHAR(200),
    IN p_description TEXT,
    IN p_address VARCHAR(255),
    IN p_city VARCHAR(100),
    IN p_price DECIMAL(12, 2),
    IN p_currency CHAR(3),
    IN p_commissionPct DECIMAL(5, 2),
    IN p_operation VARCHAR(20),
    IN p_agentId INT,
    IN p_ownerId INT
)
BEGIN
    INSERT INTO Properties (title, description, address, city, price, currency, commissionPct, operation, agentId, ownerId)
    VALUES (p_title, p_description, p_address, p_city, p_price, p_currency, p_commissionPct, p_operation, p_agentId, p_ownerId);
END //

DROP PROCEDURE IF EXISTS `sp_Property_List` //
CREATE PROCEDURE `sp_Property_List`(
    IN p_status VARCHAR(20),
    IN p_agentId INT
)
BEGIN
    SELECT 
        p.id, p.title, p.price, p.currency, p.operation, p.status, p.address,
        u.fullName as AgentName, u.phone as AgentPhone, u.photoUrl as AgentPhoto,
        c.fullName as OwnerName
    FROM Properties p
    JOIN Users u ON p.agentId = u.id
    JOIN Clients c ON p.ownerId = c.id
    WHERE (p_status IS NULL OR p.status = p_status)
      AND (p_agentId IS NULL OR p.agentId = p_agentId)
    ORDER BY p.createdAt DESC;
END //

-- SP CRÍTICO: Eliminar Propiedad (Borra documentos y ventas primero)
DROP PROCEDURE IF EXISTS `sp_Property_Delete` //
CREATE PROCEDURE `sp_Property_Delete`(IN p_id INT)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
    END;

    START TRANSACTION;
        DELETE FROM Documents WHERE propertyId = p_id;
        DELETE FROM Sales WHERE propertyId = p_id;
        DELETE FROM Properties WHERE id = p_id;
    COMMIT;
END //

-- ----------------------------
-- SP: GESTIÓN DE DOCUMENTOS
-- ----------------------------

DROP PROCEDURE IF EXISTS `sp_Document_Add` //
CREATE PROCEDURE `sp_Document_Add`(
    IN p_name VARCHAR(100),
    IN p_url VARCHAR(500),
    IN p_type VARCHAR(50),
    IN p_propertyId INT
)
BEGIN
    INSERT INTO Documents (name, url, type, propertyId)
    VALUES (p_name, p_url, p_type, p_propertyId);
END //

-- ----------------------------
-- SP: FINANZAS Y CIERRES
-- ----------------------------

-- Registrar Venta (El trigger se encargará de cambiar el estado de la propiedad)
DROP PROCEDURE IF EXISTS `sp_Sale_Register` //
CREATE PROCEDURE `sp_Sale_Register`(
    IN p_propertyId INT,
    IN p_finalPrice DECIMAL(12, 2),
    IN p_totalCommission DECIMAL(10, 2),
    IN p_listingAgentId INT,
    IN p_isShared BOOLEAN,
    IN p_externalAgency VARCHAR(100),
    IN p_sharedPct DECIMAL(5, 2),
    IN p_sellingAgentId INT
)
BEGIN
    INSERT INTO Sales (propertyId, finalPrice, totalCommission, listingAgentId, isShared, externalAgency, sharedPct, sellingAgentId)
    VALUES (p_propertyId, p_finalPrice, p_totalCommission, p_listingAgentId, p_isShared, p_externalAgency, p_sharedPct, p_sellingAgentId);
END //

-- Reporte de Dashboard (Filtrar ingresos por fecha)
DROP PROCEDURE IF EXISTS `sp_Report_Sales` //
CREATE PROCEDURE `sp_Report_Sales`(
    IN p_startDate DATE,
    IN p_endDate DATE
)
BEGIN
    SELECT 
        s.id,
        p.title as Property,
        p.operation,
        s.finalPrice,
        s.totalCommission as IngresoComision,
        s.closedAt as FechaCierre,
        u_capt.fullName as AgenteCaptador,
        CASE 
            WHEN s.isShared = 1 THEN CONCAT('EXTERNA: ', s.externalAgency)
            WHEN s.sellingAgentId IS NOT NULL THEN (SELECT fullName FROM Users WHERE id = s.sellingAgentId)
            ELSE 'Mismo Captador'
        END as AgenteCierre
    FROM Sales s
    JOIN Properties p ON s.propertyId = p.id
    JOIN Users u_capt ON s.listingAgentId = u_capt.id
    WHERE DATE(s.closedAt) BETWEEN p_startDate AND p_endDate
    ORDER BY s.closedAt DESC;
END //

DELIMITER ;


-- 4. DATOS INICIALES (SEEDER)
-- ==========================================================================

-- Crear el usuario Administrador (Erwin)
INSERT INTO Users (email, password, fullName, phone, role) 
VALUES ('admin@sistema.com', '123456', 'Erwin Admin', '999000111', 'ADMIN');

-- Crear un Cliente de prueba
INSERT INTO Clients (fullName, dniRuc, phone, email, isOwner) 
VALUES ('Juan Propietario', '45887799', '988777666', 'juan@mail.com', 1);

-- Crear una Propiedad de prueba
INSERT INTO Properties (title, description, address, city, price, currency, commissionPct, operation, agentId, ownerId)
VALUES ('Casa de Playa en Pozo de Lisas', 'Hermosa casa frente al mar', 'Av Costanera 123', 'Ilo', 150000.00, 'USD', 3.0, 'VENTA', 1, 1);

COMMIT;