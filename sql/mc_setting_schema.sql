-- =====================================================
-- System settings table (mc_setting)
-- Used to store system config (key-value)
-- Supports: MySQL / PostgreSQL / SQLite
-- =====================================================

-- MySQL version
CREATE TABLE IF NOT EXISTS `mc_setting` (
  `id` INT PRIMARY KEY AUTO_INCREMENT COMMENT 'PK',
  `key` VARCHAR(255) NOT NULL COMMENT 'Setting key (unique)',
  `content` TEXT COMMENT 'Setting content',
  `create_time` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT 'Create time',
  `update_time` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT 'Update time',
  UNIQUE KEY `uk_key` (`key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='System settings table';

-- =====================================================
-- PostgreSQL version (if using PostgreSQL)
-- =====================================================
-- CREATE TABLE IF NOT EXISTS mc_setting (
--   id SERIAL PRIMARY KEY,
--   key VARCHAR(255) NOT NULL UNIQUE,
--   content TEXT,
--   create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
--   update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
-- );

-- =====================================================
-- SQLite version (if using SQLite)
-- =====================================================
-- CREATE TABLE IF NOT EXISTS mc_setting (
--   id INTEGER PRIMARY KEY AUTOINCREMENT,
--   key TEXT NOT NULL UNIQUE,
--   content TEXT,
--   create_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
--   update_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
-- );
