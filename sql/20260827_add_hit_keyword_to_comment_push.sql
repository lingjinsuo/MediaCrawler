-- =====================================================
-- 2026-08-27
-- 为 comment_push 表新增 hit_keyword 字段
-- 用途:记录本条评论是由 mc_setting.comment_key 中的哪个关键词命中
--       (即过滤出"有购买意图"评论的关键词)
-- 支持:MySQL (与 sql/comment_push_schema.sql 保持一致)
-- =====================================================

-- 1. 新增 hit_keyword 列(默认 NULL,老数据保留为空)
ALTER TABLE `comment_push`
ADD COLUMN `hit_keyword` VARCHAR(255) DEFAULT NULL
  COMMENT '命中关键词(由 mc_setting.comment_key 触发本条推送)';

-- 2. 常用按关键词聚合查询,加一个索引提升效率
ALTER TABLE `comment_push`
ADD INDEX `idx_hit_keyword` (`hit_keyword`);

-- =====================================================
-- 3. 更新后的 comment_push 表结构(供阅读参考,不执行)
-- =====================================================
-- CREATE TABLE IF NOT EXISTS `comment_push` (
--   `id` INT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
--
--   `platform` VARCHAR(20) NOT NULL COMMENT '平台: xhs-小红书, dy-抖音, ks-快手',
--
--   `note_title` VARCHAR(500) COMMENT '作品标题',
--   `note_url` VARCHAR(500) COMMENT '作品链接',
--   `note_nickname` VARCHAR(100) COMMENT '作品作者昵称',
--
--   `comment_id` VARCHAR(255) COMMENT '评论ID',
--   `comment_content` TEXT COMMENT '评论内容',
--   `comment_nickname` VARCHAR(100) COMMENT '评论者昵称',
--   `comment_time` BIGINT COMMENT '评论时间戳(毫秒)',
--
--   `original_comment_id` INT COMMENT '原始评论表ID',
--
--   `hit_keyword` VARCHAR(255) DEFAULT NULL
--     COMMENT '命中关键词(由 mc_setting.comment_key 触发本条推送)',
--
--   `push_status` TINYINT DEFAULT 0 COMMENT '推送状态: 0-待处理, 1-已处理',
--   `process_content` TEXT COMMENT '处理内容',
--   `process_time` DATETIME COMMENT '处理时间',
--
--   `create_time` BIGINT COMMENT '创建时间戳(毫秒)',
--   `analysis_time` DATETIME COMMENT '分析时间',
--
--   INDEX `idx_platform_status` (`platform`, `push_status`),
--   INDEX `idx_create_time` (`create_time`),
--   INDEX `idx_hit_keyword` (`hit_keyword`)
-- ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评论购买意图推送表(支持小红书/抖音/快手)';

-- =====================================================
-- 4. 回滚脚本(如需)
-- =====================================================
-- ALTER TABLE `comment_push` DROP INDEX `idx_hit_keyword`;
-- ALTER TABLE `comment_push` DROP COLUMN `hit_keyword`;