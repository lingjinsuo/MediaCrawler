-- =====================================================
-- 评论购买意图分析 - 数据库结构脚本
-- 支持：小红书(xhs)、抖音(dy)、快手(ks)
-- =====================================================

-- 1. 创建评论推送表 (comment_push)
CREATE TABLE IF NOT EXISTS `comment_push` (
  `id` INT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
  
  -- 平台标识
  `platform` VARCHAR(20) NOT NULL COMMENT '平台: xhs-小红书, dy-抖音, ks-快手',
  
  -- 作品信息
  `note_title` VARCHAR(500) COMMENT '作品标题',
  `note_url` VARCHAR(500) COMMENT '作品链接',
  `note_nickname` VARCHAR(100) COMMENT '作品作者昵称',
  
  -- 评论信息
  `comment_id` VARCHAR(255) COMMENT '评论ID',
  `comment_content` TEXT COMMENT '评论内容',
  `comment_nickname` VARCHAR(100) COMMENT '评论者昵称',
  `comment_time` BIGINT COMMENT '评论时间戳(毫秒)',
  
  -- 关联原始评论
  `original_comment_id` INT COMMENT '原始评论表ID',
  
  -- 推送状态
  `push_status` TINYINT DEFAULT 0 COMMENT '推送状态: 0-待处理, 1-已处理',
  `process_content` TEXT COMMENT '处理内容',
  `process_time` DATETIME COMMENT '处理时间',
  
  -- 时间戳
  `create_time` BIGINT COMMENT '创建时间戳(毫秒)',
  `analysis_time` DATETIME COMMENT '分析时间',
  
  INDEX `idx_platform_status` (`platform`, `push_status`),
  INDEX `idx_create_time` (`create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='评论购买意图推送表(支持小红书/抖音/快手)';

-- =====================================================
-- 2. 为各平台评论表添加分析状态字段
-- =====================================================

-- 小红书评论表
ALTER TABLE `xhs_note_comment` 
ADD COLUMN `analysis_status` TINYINT DEFAULT 0 COMMENT '分析状态: 0-未分析, 1-已分析(无购买意图), 2-已推送(有购买意图)',
ADD COLUMN `analysis_time` DATETIME COMMENT '分析时间';

-- 抖音评论表
ALTER TABLE `douyin_aweme_comment` 
ADD COLUMN `analysis_status` TINYINT DEFAULT 0 COMMENT '分析状态: 0-未分析, 1-已分析(无购买意图), 2-已推送(有购买意图)',
ADD COLUMN `analysis_time` DATETIME COMMENT '分析时间';

-- 快手评论表
ALTER TABLE `kuaishou_video_comment` 
ADD COLUMN `analysis_status` TINYINT DEFAULT 0 COMMENT '分析状态: 0-未分析, 1-已分析(无购买意图), 2-已推送(有购买意图)',
ADD COLUMN `analysis_time` DATETIME COMMENT '分析时间';

-- =====================================================
-- 3. 说明
-- =====================================================
-- analysis_status 状态说明:
--   0 - 未分析 (初始状态)
--   1 - 已分析，无购买意图
--   2 - 已推送，有购买意图 (已写入 comment_push 表)
--
-- 跑批查询未分析评论:
--   SELECT * FROM xhs_note_comment WHERE analysis_status = 0;
--
-- 平台标识:
--   xhs - 小红书
--   dy  - 抖音
--   ks  - 快手
