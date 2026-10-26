-- Trinity Text-to-SQL 演示库种子（虚构公司「云启智能」）
--
-- 由 scripts/seed_demo_sql.py 读取并写入 data/demo_sql/demo.db（gitignore）。
-- 数据固定、可重复生成；不要写真实个人信息。
--
-- 演示问题：各部门差旅报销总额是多少？
-- 预期（status='approved' 且 category LIKE '差旅%'）：
--   研发部 5790.00 / 市场部 5360.00 / 销售部 8970.00 / 交付部 3220.00 / 职能部 2700.00

PRAGMA foreign_keys = OFF;

DROP TABLE IF EXISTS expense_claims;
DROP TABLE IF EXISTS employees;
DROP TABLE IF EXISTS travel_standards;
DROP TABLE IF EXISTS departments;

CREATE TABLE departments (
    dept_id     INTEGER PRIMARY KEY,
    dept_name   TEXT NOT NULL UNIQUE,
    cost_center TEXT NOT NULL
);

CREATE TABLE employees (
    employee_id   INTEGER PRIMARY KEY,
    employee_name TEXT NOT NULL,
    dept_id       INTEGER NOT NULL REFERENCES departments(dept_id),
    title         TEXT NOT NULL,
    level         TEXT NOT NULL,
    hire_date     TEXT NOT NULL
);

CREATE TABLE travel_standards (
    level              TEXT NOT NULL,
    city_tier          TEXT NOT NULL,
    hotel_limit_cny    INTEGER NOT NULL,
    meal_allowance_cny INTEGER NOT NULL,
    PRIMARY KEY (level, city_tier)
);

CREATE TABLE expense_claims (
    claim_id       INTEGER PRIMARY KEY,
    employee_id    INTEGER NOT NULL REFERENCES employees(employee_id),
    dept_id        INTEGER NOT NULL REFERENCES departments(dept_id),
    claim_month    TEXT NOT NULL,
    category       TEXT NOT NULL,
    amount_cny     REAL NOT NULL,
    status         TEXT NOT NULL,
    submitted_date TEXT NOT NULL,
    note           TEXT
);

INSERT INTO departments (dept_id, dept_name, cost_center) VALUES
    (1, '研发部', 'CC-RD'),
    (2, '市场部', 'CC-MKT'),
    (3, '销售部', 'CC-SALES'),
    (4, '交付部', 'CC-DELIVERY'),
    (5, '职能部', 'CC-FUNC');

INSERT INTO employees (employee_id, employee_name, dept_id, title, level, hire_date) VALUES
    (1,  '张伟', 1, '高级工程师',   'P4', '2019-03-11'),
    (2,  '李娜', 1, '工程师',       'P3', '2021-07-05'),
    (3,  '王磊', 1, '助理工程师',   'P2', '2023-09-18'),
    (4,  '赵敏', 2, '品牌经理',     'P4', '2018-06-25'),
    (5,  '陈晨', 2, '市场专员',     'P3', '2022-02-14'),
    (6,  '周宁', 2, '活动助理',     'P2', '2024-04-08'),
    (7,  '孙浩', 3, '销售总监',     'P5', '2017-11-02'),
    (8,  '林悦', 3, '大客户经理',   'P4', '2020-08-17'),
    (9,  '何静', 3, '销售经理',     'P3', '2022-10-10'),
    (10, '郑凯', 4, '交付经理',     'P4', '2019-12-09'),
    (11, '吴雨', 4, '实施工程师',   'P3', '2021-05-24'),
    (12, '冯博', 4, '实施助理',     'P2', '2023-12-04'),
    (13, '许琳', 5, '财务主管',     'P3', '2020-03-16'),
    (14, '罗成', 5, '行政专员',     'P2', '2022-06-20'),
    (15, '高远', 5, '人力经理',     'P4', '2019-09-02');

INSERT INTO travel_standards (level, city_tier, hotel_limit_cny, meal_allowance_cny) VALUES
    ('P1', '一线', 900, 200),
    ('P1', '二线', 650, 150),
    ('P2', '一线', 800, 180),
    ('P2', '二线', 550, 130),
    ('P3', '一线', 650, 150),
    ('P3', '二线', 450, 110),
    ('P4', '一线', 500, 120),
    ('P4', '二线', 350, 90),
    ('P5', '一线', 700, 160),
    ('P5', '二线', 500, 120);

INSERT INTO expense_claims
    (claim_id, employee_id, dept_id, claim_month, category, amount_cny, status, submitted_date, note)
VALUES
    (1,  1,  1, '2026-07', '差旅-交通', 1280.00, 'approved', '2026-07-18', '华东客户拜访'),
    (2,  1,  1, '2026-07', '差旅-住宿', 1750.00, 'approved', '2026-07-18', '华东客户拜访'),
    (3,  2,  1, '2026-08', '差旅-餐饮',  460.00, 'approved', '2026-08-12', '项目启动会'),
    (4,  3,  1, '2026-08', '差旅-交通',  980.00, 'approved', '2026-08-26', '现场调试'),
    (5,  2,  1, '2026-09', '差旅-住宿', 1320.00, 'approved', '2026-09-09', '行业峰会'),
    (6,  3,  1, '2026-09', '办公',       260.00, 'approved', '2026-09-22', '开发板采购'),
    (7,  1,  1, '2026-09', '差旅-餐饮',  380.00, 'pending',  '2026-09-28', '行业峰会'),

    (8,  4,  2, '2026-07', '差旅-交通', 1560.00, 'approved', '2026-07-21', '品牌发布会'),
    (9,  4,  2, '2026-07', '差旅-住宿', 2100.00, 'approved', '2026-07-21', '品牌发布会'),
    (10, 5,  2, '2026-08', '差旅-餐饮',  520.00, 'approved', '2026-08-07', '渠道培训'),
    (11, 5,  2, '2026-08', '办公',       310.00, 'approved', '2026-08-19', '物料印刷'),
    (12, 6,  2, '2026-09', '差旅-交通', 1180.00, 'approved', '2026-09-15', '展会支持'),
    (13, 6,  2, '2026-09', '差旅-住宿',  890.00, 'rejected', '2026-09-16', '超出住宿标准'),

    (14, 7,  3, '2026-07', '差旅-交通', 2200.00, 'approved', '2026-07-09', '重点客户续约'),
    (15, 7,  3, '2026-07', '差旅-住宿', 2600.00, 'approved', '2026-07-09', '重点客户续约'),
    (16, 8,  3, '2026-08', '差旅-餐饮',  640.00, 'approved', '2026-08-14', '客户答谢会'),
    (17, 8,  3, '2026-08', '差旅-交通', 1750.00, 'approved', '2026-08-21', '西南区巡访'),
    (18, 9,  3, '2026-09', '差旅-住宿', 1480.00, 'approved', '2026-09-06', '投标答辩'),
    (19, 9,  3, '2026-09', '差旅-餐饮',  300.00, 'approved', '2026-09-06', '投标答辩'),

    (20, 10, 4, '2026-07', '差旅-交通',  960.00, 'approved', '2026-07-13', '现场交付'),
    (21, 10, 4, '2026-07', '差旅-餐饮',  280.00, 'approved', '2026-07-13', '现场交付'),
    (22, 11, 4, '2026-08', '差旅-住宿', 1120.00, 'approved', '2026-08-10', '驻场实施'),
    (23, 11, 4, '2026-08', '差旅-交通',  860.00, 'approved', '2026-08-10', '驻场实施'),
    (24, 12, 4, '2026-09', '差旅-住宿',  740.00, 'pending',  '2026-09-25', '客户回访'),
    (25, 12, 4, '2026-09', '办公',       190.00, 'approved', '2026-09-25', '现场耗材'),

    (26, 13, 5, '2026-07', '差旅-交通',  540.00, 'approved', '2026-07-06', '供应商走访'),
    (27, 13, 5, '2026-07', '差旅-餐饮',  220.00, 'approved', '2026-07-06', '供应商走访'),
    (28, 14, 5, '2026-08', '差旅-住宿',  680.00, 'approved', '2026-08-18', '园区安全检查'),
    (29, 14, 5, '2026-08', '办公',       450.00, 'approved', '2026-08-18', '安全物资'),
    (30, 15, 5, '2026-09', '差旅-交通',  320.00, 'approved', '2026-09-03', '校园招聘'),
    (31, 15, 5, '2026-09', '差旅-餐饮',  180.00, 'approved', '2026-09-03', '校园招聘'),
    (32, 14, 5, '2026-09', '差旅-住宿',  760.00, 'approved', '2026-09-19', '年度审计接待');

PRAGMA foreign_keys = ON;
