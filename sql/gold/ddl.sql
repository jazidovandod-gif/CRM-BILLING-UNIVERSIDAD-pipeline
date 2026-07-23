-- ============================================================================
-- Gold: modelo dimensional (estrella) + vistas de KPIs de negocio.
--
-- Dimensiones y hechos son TABLAS materializadas (para el dashboard y el
-- export a Parquet). Los KPIs son VISTAS (se recalculan al consultarse).
--
-- Decisiones de modelado (ver docs/decisiones.md):
--   * Revenue = Σ(line_total) de items (fuente confiable), no el total_reported
--     ni la suma de pagos. Para facturas sin items se usa total_reported.
--   * Los montos NO se suman entre monedas: todo KPI de dinero segmenta por currency.
--   * fact_enrollment usa solo la fila superviviente de cada grupo duplicado.
--   * Aprobación académica: final_score_weighted >= 60.
--   * dim_customer y dim_student se enlazan por external_ref SIN fusionar PII.
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS gold;

-- ----------------------------------------------------------------- DIMENSIONES

DROP TABLE IF EXISTS gold.dim_date CASCADE;
CREATE TABLE gold.dim_date (
    date_key     DATE PRIMARY KEY,
    year         SMALLINT NOT NULL,
    quarter      SMALLINT NOT NULL,
    month        SMALLINT NOT NULL,
    month_name   TEXT NOT NULL,
    day          SMALLINT NOT NULL,
    day_of_week  SMALLINT NOT NULL,
    is_weekend   BOOLEAN NOT NULL
);

DROP TABLE IF EXISTS gold.dim_student CASCADE;
CREATE TABLE gold.dim_student (
    student_id   TEXT PRIMARY KEY,
    country      TEXT,
    birth_date   DATE,
    enrolled_at  DATE,
    age_at_enrollment_lt_15 BOOLEAN
);

DROP TABLE IF EXISTS gold.dim_customer CASCADE;
CREATE TABLE gold.dim_customer (
    customer_id  TEXT PRIMARY KEY,
    is_student   BOOLEAN NOT NULL,
    student_id   TEXT,                 -- enlace técnico a dim_student (o NULL)
    segment      TEXT,
    country      TEXT,
    created_date DATE
);

DROP TABLE IF EXISTS gold.dim_product CASCADE;
CREATE TABLE gold.dim_product (
    product_id   TEXT PRIMARY KEY,
    sku          TEXT,
    name         TEXT,
    category     TEXT,
    monthly_price NUMERIC(10,2),
    active       BOOLEAN
);

DROP TABLE IF EXISTS gold.dim_course CASCADE;
CREATE TABLE gold.dim_course (
    course_id    TEXT PRIMARY KEY,
    code         TEXT,
    name         TEXT,
    credits      SMALLINT,
    department   TEXT,
    professor_id TEXT,
    department_mismatch BOOLEAN
);

DROP TABLE IF EXISTS gold.dim_semester CASCADE;
CREATE TABLE gold.dim_semester (
    semester_id  TEXT PRIMARY KEY,
    code         TEXT,
    year         SMALLINT,
    half         SMALLINT,
    start_date   DATE,
    end_date     DATE
);

DROP TABLE IF EXISTS gold.dim_account CASCADE;
CREATE TABLE gold.dim_account (
    account_id   TEXT PRIMARY KEY,
    name         TEXT,
    industry     TEXT,
    country      TEXT,
    annual_revenue NUMERIC(14,2),
    employees    INTEGER,
    employee_band TEXT,                -- small (<50) / mid (50-500) / large (>500)
    name_is_shared BOOLEAN
);

-- ---------------------------------------------------------------------- HECHOS

DROP TABLE IF EXISTS gold.fact_enrollment CASCADE;
CREATE TABLE gold.fact_enrollment (
    enrollment_id TEXT PRIMARY KEY,
    student_id    TEXT REFERENCES gold.dim_student (student_id),
    course_id     TEXT REFERENCES gold.dim_course (course_id),
    semester_id   TEXT REFERENCES gold.dim_semester (semester_id),
    enrolled_date DATE REFERENCES gold.dim_date (date_key),
    status        TEXT,
    has_grades    BOOLEAN,
    final_score   NUMERIC(6,3),
    weight_sum_ok BOOLEAN,
    passed        BOOLEAN
);

DROP TABLE IF EXISTS gold.fact_invoice CASCADE;
CREATE TABLE gold.fact_invoice (
    invoice_id    TEXT PRIMARY KEY,
    customer_id   TEXT REFERENCES gold.dim_customer (customer_id),
    issued_date   DATE REFERENCES gold.dim_date (date_key),
    due_date      DATE,
    currency      TEXT,
    invoiced_amount NUMERIC(12,2),     -- Σ items, o total_reported si no hay items
    total_reported  NUMERIC(12,2),
    status        TEXT,
    payment_status_derived TEXT,
    has_no_items  BOOLEAN,
    is_total_mismatch BOOLEAN
);

DROP TABLE IF EXISTS gold.fact_payment CASCADE;
CREATE TABLE gold.fact_payment (
    payment_id    TEXT PRIMARY KEY,
    invoice_id    TEXT REFERENCES gold.fact_invoice (invoice_id),
    customer_id   TEXT REFERENCES gold.dim_customer (customer_id),
    paid_date     DATE REFERENCES gold.dim_date (date_key),
    amount        NUMERIC(12,2),
    method        TEXT
);

DROP TABLE IF EXISTS gold.fact_subscription CASCADE;
CREATE TABLE gold.fact_subscription (
    subscription_id TEXT PRIMARY KEY,
    customer_id   TEXT REFERENCES gold.dim_customer (customer_id),
    product_id    TEXT REFERENCES gold.dim_product (product_id),
    status        TEXT,
    start_date    DATE,
    end_date      DATE,
    is_effectively_expired BOOLEAN,
    invalid_date_range BOOLEAN,
    monthly_price NUMERIC(10,2)
);

DROP TABLE IF EXISTS gold.fact_opportunity CASCADE;
CREATE TABLE gold.fact_opportunity (
    opportunity_id TEXT PRIMARY KEY,
    account_id    TEXT REFERENCES gold.dim_account (account_id),
    stage         TEXT,
    amount        NUMERIC(14,2),
    created_date  DATE REFERENCES gold.dim_date (date_key),
    close_date    DATE,
    is_won        BOOLEAN,
    is_closed     BOOLEAN,
    is_close_before_created BOOLEAN
);

DROP TABLE IF EXISTS gold.fact_activity CASCADE;
CREATE TABLE gold.fact_activity (
    activity_id   TEXT PRIMARY KEY,
    type          TEXT,
    occurred_date DATE REFERENCES gold.dim_date (date_key),
    contact_id    TEXT,
    opportunity_id TEXT,
    is_orphan     BOOLEAN,
    account_mismatch BOOLEAN
);

DROP TABLE IF EXISTS gold.fact_lead CASCADE;
CREATE TABLE gold.fact_lead (
    lead_id       TEXT PRIMARY KEY,
    source        TEXT,
    status        TEXT,
    score         SMALLINT,
    created_date  DATE REFERENCES gold.dim_date (date_key),
    is_converted  BOOLEAN
);

-- ------------------------------------------------------------- KPIs (VISTAS)

-- Revenue facturado por mes y moneda (NO se suma entre monedas).
CREATE OR REPLACE VIEW gold.kpi_revenue_monthly AS
SELECT date_trunc('month', issued_date)::date AS month,
       currency,
       count(*)                    AS invoices,
       sum(invoiced_amount)        AS revenue,
       round(avg(invoiced_amount), 2) AS avg_ticket
FROM gold.fact_invoice
GROUP BY 1, 2;

-- Cobranza por moneda. Los montos de pago son inconsistentes en el dataset,
-- así que la cobranza se mide por estado de factura, no por suma de pagos.
CREATE OR REPLACE VIEW gold.kpi_collection_by_currency AS
SELECT currency,
       count(*)                                             AS invoices,
       sum(invoiced_amount)                                 AS billed_amount,
       count(*) FILTER (WHERE status = 'paid')              AS paid_invoices,
       round(100.0 * count(*) FILTER (WHERE status = 'paid') / count(*), 1) AS paid_pct
FROM gold.fact_invoice
GROUP BY 1;

-- Rendimiento académico por departamento del curso.
CREATE OR REPLACE VIEW gold.kpi_academic_by_department AS
SELECT c.department,
       count(*)                                          AS enrollments,
       count(*) FILTER (WHERE f.has_grades)              AS with_grades,
       round(avg(f.final_score) FILTER (WHERE f.has_grades), 2) AS avg_final_score,
       round(100.0 * count(*) FILTER (WHERE f.passed)
             / NULLIF(count(*) FILTER (WHERE f.has_grades), 0), 1) AS pass_rate_pct
FROM gold.fact_enrollment f
JOIN gold.dim_course c ON f.course_id = c.course_id
GROUP BY 1;

-- Estado de suscripciones y MRR (revenue recurrente mensual).
CREATE OR REPLACE VIEW gold.kpi_subscription_status AS
SELECT status,
       count(*)                                              AS subscriptions,
       count(*) FILTER (WHERE is_effectively_expired)        AS effectively_expired,
       round(sum(monthly_price) FILTER (
             WHERE status = 'active' AND NOT is_effectively_expired), 2) AS active_mrr
FROM gold.fact_subscription
GROUP BY 1;

-- Pipeline comercial por etapa.
CREATE OR REPLACE VIEW gold.kpi_sales_pipeline AS
SELECT stage,
       count(*)          AS opportunities,
       round(sum(amount), 2) AS total_amount,
       round(avg(amount), 2) AS avg_amount
FROM gold.fact_opportunity
GROUP BY 1;

-- Embudo de leads por estado.
CREATE OR REPLACE VIEW gold.kpi_lead_funnel AS
SELECT status,
       count(*) AS leads,
       round(avg(score), 1) AS avg_score
FROM gold.fact_lead
GROUP BY 1;

-- Comportamiento de facturación: estudiantes vs. clientes externos.
CREATE OR REPLACE VIEW gold.kpi_student_vs_external AS
SELECT CASE WHEN d.is_student THEN 'estudiante' ELSE 'externo' END AS customer_type,
       count(DISTINCT d.customer_id)                    AS customers,
       count(f.invoice_id)                              AS invoices,
       round(count(f.invoice_id)::numeric
             / count(DISTINCT d.customer_id), 3)        AS invoices_per_customer,
       round(sum(f.invoiced_amount)
             / count(DISTINCT d.customer_id), 2)        AS revenue_per_customer
FROM gold.dim_customer d
LEFT JOIN gold.fact_invoice f ON d.customer_id = f.customer_id
GROUP BY 1;

-- MRR: reportado (todas las activas) vs. real (vigentes) vs. en riesgo (vencidas).
-- Materializa el insight central de suscripciones: el 63% del MRR "activo" ya venció.
CREATE OR REPLACE VIEW gold.kpi_mrr_breakdown AS
SELECT 'MRR real (vigente)' AS segmento,
       count(*) FILTER (WHERE status = 'active' AND NOT is_effectively_expired)  AS suscripciones,
       round(sum(monthly_price) FILTER (
             WHERE status = 'active' AND NOT is_effectively_expired), 2)         AS mrr
FROM gold.fact_subscription
UNION ALL
SELECT 'MRR en riesgo (activa vencida)',
       count(*) FILTER (WHERE status = 'active' AND is_effectively_expired),
       round(sum(monthly_price) FILTER (
             WHERE status = 'active' AND is_effectively_expired), 2)
FROM gold.fact_subscription;

-- Embudo de leads por canal de origen (soporta el insight cold_call > web).
CREATE OR REPLACE VIEW gold.kpi_lead_by_source AS
SELECT source,
       count(*)                                      AS leads,
       count(*) FILTER (WHERE is_converted)          AS convertidos,
       round(100.0 * count(*) FILTER (WHERE is_converted) / count(*), 1) AS conversion_pct
FROM gold.fact_lead
GROUP BY 1;

-- Números titulares (una sola fila) para los "big numbers" del dashboard.
-- Cada columna es un insight cuantificado.
CREATE OR REPLACE VIEW gold.kpi_headline AS
SELECT
    (SELECT round(sum(monthly_price) FILTER (WHERE status = 'active' AND NOT is_effectively_expired), 0)
       FROM gold.fact_subscription)                                          AS mrr_real,
    (SELECT round(sum(monthly_price) FILTER (WHERE status = 'active'), 0)
       FROM gold.fact_subscription)                                          AS mrr_nominal,
    (SELECT round(100.0 * count(*) FILTER (WHERE status <> 'paid') / count(*), 1)
       FROM gold.fact_invoice)                                               AS pct_sin_cobrar,
    (SELECT round(100.0 * count(*) FILTER (WHERE is_won)
             / NULLIF(count(*) FILTER (WHERE is_closed), 0), 1)
       FROM gold.fact_opportunity)                                           AS win_rate_pct,
    (SELECT round(100.0 * count(*) FILTER (WHERE is_converted) / count(*), 1)
       FROM gold.fact_lead)                                                  AS lead_conversion_pct;
