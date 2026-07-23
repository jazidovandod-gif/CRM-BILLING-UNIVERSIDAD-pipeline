-- ============================================================================
-- Silver: datos limpios, tipados, estandarizados y con flags de calidad.
--
-- Diseño:
--   * Una tabla Silver por cada tabla fuente (tipos reales, no TEXT).
--   * Cada anomalía detectada en el discovery se materializa como una columna
--     flag booleana (o una columna derivada), no se borra la fila. Filosofía:
--     "flaggear en vez de borrar" — Gold decide qué filtrar.
--   * `silver.enrollment_grade_summary` es una tabla derivada (nota final
--     renormalizada por inscripción) porque `weight` no suma 1.0.
--   * Trazabilidad: `_silver_loaded_at`. El linaje a Bronze se conserva vía
--     las PK naturales (Bronze guarda _batch_id/_row_hash por fila).
--
-- Silver es reconstruible desde Bronze en cualquier momento -> DROP + CREATE.
-- El conteo de filas de Silver == conteo de Bronze (no se deduplica físicamente;
-- los duplicados lógicos se marcan con flags y Gold los resuelve).
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS silver;

-- ------------------------------------------------------------------ UNIVERSITY

DROP TABLE IF EXISTS silver.university_semesters CASCADE;
CREATE TABLE silver.university_semesters (
    semester_id     TEXT PRIMARY KEY,
    code            TEXT NOT NULL,
    year            SMALLINT NOT NULL,
    half            SMALLINT NOT NULL,
    start_date      DATE NOT NULL,
    end_date        DATE NOT NULL,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CHECK (end_date >= start_date)
);

DROP TABLE IF EXISTS silver.university_professors CASCADE;
CREATE TABLE silver.university_professors (
    professor_id    TEXT PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    email           TEXT,
    department      TEXT,
    hired_at        DATE,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.university_students CASCADE;
CREATE TABLE silver.university_students (
    student_id      TEXT PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    email           TEXT,
    birth_date      DATE,
    enrolled_at     DATE,
    country         TEXT,
    -- flag: edad al momento de enrolled_at menor a 15 (birth_date y enrolled_at
    -- fueron generados de forma independiente; 636 casos en el discovery)
    age_at_enrollment_lt_15 BOOLEAN NOT NULL DEFAULT FALSE,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.university_courses CASCADE;
CREATE TABLE silver.university_courses (
    course_id       TEXT PRIMARY KEY,
    code            TEXT,
    name            TEXT,
    credits         SMALLINT,
    department      TEXT,
    professor_id    TEXT REFERENCES silver.university_professors (professor_id),
    -- flag: el departamento del curso difiere del del profesor asignado (88%)
    department_mismatch BOOLEAN NOT NULL DEFAULT FALSE,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.university_enrollments CASCADE;
CREATE TABLE silver.university_enrollments (
    enrollment_id   TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    student_id      TEXT NOT NULL REFERENCES silver.university_students (student_id),
    course_id       TEXT NOT NULL REFERENCES silver.university_courses (course_id),
    semester_id     TEXT NOT NULL REFERENCES silver.university_semesters (semester_id),
    enrolled_at_raw DATE,                 -- fecha original (no confiable)
    enrolled_at     DATE NOT NULL,        -- fecha canónica = semester.start_date
    -- flags del discovery:
    enrolled_at_out_of_window BOOLEAN NOT NULL DEFAULT FALSE, -- 91% fuera de ventana
    is_duplicate_enrollment   BOOLEAN NOT NULL DEFAULT FALSE, -- participa en grupo dup (23 grupos)
    is_duplicate_survivor     BOOLEAN NOT NULL DEFAULT TRUE,  -- fila que Gold conserva del grupo
    has_grades                BOOLEAN NOT NULL DEFAULT FALSE, -- 2214 sin ninguna nota
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.university_grades CASCADE;
CREATE TABLE silver.university_grades (
    grade_id        TEXT PRIMARY KEY,
    assessment      TEXT NOT NULL,
    score           NUMERIC(5,2) CHECK (score BETWEEN 0 AND 100),
    weight          NUMERIC(4,3) CHECK (weight BETWEEN 0 AND 1),
    graded_at       DATE,
    enrollment_id   TEXT NOT NULL REFERENCES silver.university_enrollments (enrollment_id),
    -- flag: existe otra nota con el mismo (enrollment_id, assessment) (38% de filas)
    has_duplicate_assessment BOOLEAN NOT NULL DEFAULT FALSE,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Tabla derivada: nota final por inscripción, con peso RENORMALIZADO
-- (Σ(score·weight)/Σ(weight)) porque los pesos crudos no suman 1.0.
DROP TABLE IF EXISTS silver.enrollment_grade_summary CASCADE;
CREATE TABLE silver.enrollment_grade_summary (
    enrollment_id       TEXT PRIMARY KEY REFERENCES silver.university_enrollments (enrollment_id),
    n_grades            SMALLINT NOT NULL,
    weight_sum          NUMERIC(6,3) NOT NULL,
    weight_sum_ok       BOOLEAN NOT NULL,   -- |Σweight - 1| <= 0.01 (solo 141 casos)
    final_score_weighted NUMERIC(6,3),      -- Σ(score·weight)/Σ(weight)
    final_score_simple  NUMERIC(6,3),       -- promedio simple (referencia)
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- --------------------------------------------------------------------- BILLING

DROP TABLE IF EXISTS silver.billing_products CASCADE;
CREATE TABLE silver.billing_products (
    product_id      TEXT PRIMARY KEY,
    sku             TEXT,
    name            TEXT,
    category        TEXT,
    monthly_price   NUMERIC(10,2) CHECK (monthly_price >= 0),
    active          BOOLEAN NOT NULL,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.billing_customers CASCADE;
CREATE TABLE silver.billing_customers (
    customer_id     TEXT PRIMARY KEY,
    external_ref    TEXT,                 -- FK a students.student_id (o NULL)
    first_name      TEXT,
    last_name       TEXT,
    email           TEXT,
    country         TEXT,
    created_at      TIMESTAMPTZ,
    segment         TEXT,
    -- flag: cliente vinculado a un estudiante (external_ref no nulo)
    is_student      BOOLEAN NOT NULL DEFAULT FALSE,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.billing_subscriptions CASCADE;
CREATE TABLE silver.billing_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    start_date      DATE,
    end_date        DATE,                 -- se anula si el rango es inválido
    end_date_raw    DATE,                 -- valor original conservado
    customer_id     TEXT NOT NULL REFERENCES silver.billing_customers (customer_id),
    product_id      TEXT NOT NULL REFERENCES silver.billing_products (product_id),
    -- flags del discovery:
    invalid_date_range           BOOLEAN NOT NULL DEFAULT FALSE, -- end<start (783)
    is_effectively_expired       BOOLEAN NOT NULL DEFAULT FALSE, -- active + end vencida (7146)
    active_sub_on_inactive_product BOOLEAN NOT NULL DEFAULT FALSE, -- (1753)
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.billing_invoices CASCADE;
CREATE TABLE silver.billing_invoices (
    invoice_id      TEXT PRIMARY KEY,
    issued_at       DATE,
    due_at          DATE,
    total_reported  NUMERIC(12,2),        -- total original del CSV (no confiable)
    total           NUMERIC(12,2),        -- recalculado = Σ(line_total) de items
    status          TEXT,
    currency        TEXT,
    customer_id     TEXT NOT NULL REFERENCES silver.billing_customers (customer_id),
    -- flags del discovery:
    is_total_mismatch     BOOLEAN NOT NULL DEFAULT FALSE, -- reported != recalculado (47497)
    has_no_items          BOOLEAN NOT NULL DEFAULT FALSE, -- factura sin items (2502)
    is_past_due           BOOLEAN NOT NULL DEFAULT FALSE, -- due_at < snapshot y no pagada
    paid_without_payment  BOOLEAN NOT NULL DEFAULT FALSE, -- status=paid sin pagos (3533)
    payment_status_derived TEXT,          -- unpaid|partial|full|overpaid
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.billing_invoice_items CASCADE;
CREATE TABLE silver.billing_invoice_items (
    invoice_item_id TEXT PRIMARY KEY,
    quantity        NUMERIC(10,2) CHECK (quantity > 0),
    unit_price      NUMERIC(10,2) CHECK (unit_price >= 0),
    line_total      NUMERIC(12,2),
    invoice_id      TEXT NOT NULL REFERENCES silver.billing_invoices (invoice_id),
    product_id      TEXT NOT NULL REFERENCES silver.billing_products (product_id),
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.billing_payments CASCADE;
CREATE TABLE silver.billing_payments (
    payment_id      TEXT PRIMARY KEY,
    amount          NUMERIC(12,2) CHECK (amount > 0),
    paid_at         DATE,
    method          TEXT,
    invoice_id      TEXT NOT NULL REFERENCES silver.billing_invoices (invoice_id),
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- ------------------------------------------------------------------------- CRM

DROP TABLE IF EXISTS silver.crm_accounts CASCADE;
CREATE TABLE silver.crm_accounts (
    account_id      TEXT PRIMARY KEY,
    name            TEXT,
    industry        TEXT,
    country         TEXT,
    annual_revenue  NUMERIC(14,2),
    employees       INTEGER,
    created_at      TIMESTAMPTZ,
    -- flag: el nombre se comparte con otras cuentas (solo 599 nombres p/ 5000);
    -- name NO es clave de negocio
    name_is_shared  BOOLEAN NOT NULL DEFAULT FALSE,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.crm_contacts CASCADE;
CREATE TABLE silver.crm_contacts (
    contact_id      TEXT PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    email           TEXT,
    phone           TEXT,
    title           TEXT,
    created_at      TIMESTAMPTZ,
    account_id      TEXT NOT NULL REFERENCES silver.crm_accounts (account_id),
    -- flag: email repetido en otro contacto (4 filas)
    is_duplicate_email BOOLEAN NOT NULL DEFAULT FALSE,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.crm_leads CASCADE;
CREATE TABLE silver.crm_leads (
    lead_id         TEXT PRIMARY KEY,
    first_name      TEXT,
    last_name       TEXT,
    email           TEXT,
    source          TEXT,
    status          TEXT,
    score           SMALLINT CHECK (score BETWEEN 0 AND 100),
    created_at      TIMESTAMPTZ,
    -- flag: lead marcado como convertido (no rastreable a contact/customer)
    is_converted    BOOLEAN NOT NULL DEFAULT FALSE,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.crm_opportunities CASCADE;
CREATE TABLE silver.crm_opportunities (
    opportunity_id  TEXT PRIMARY KEY,
    name            TEXT,
    stage           TEXT,
    amount          NUMERIC(14,2) CHECK (amount > 0),
    close_date      DATE,
    created_at      TIMESTAMPTZ,
    account_id      TEXT NOT NULL REFERENCES silver.crm_accounts (account_id),
    -- flags del discovery:
    is_close_before_created BOOLEAN NOT NULL DEFAULT FALSE, -- 34.3%
    is_closed       BOOLEAN NOT NULL DEFAULT FALSE,         -- stage in (won, lost)
    is_won          BOOLEAN NOT NULL DEFAULT FALSE,
    has_contacts    BOOLEAN NOT NULL DEFAULT FALSE,         -- 414 sin contactos
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

DROP TABLE IF EXISTS silver.crm_opportunity_contacts CASCADE;
CREATE TABLE silver.crm_opportunity_contacts (
    opportunity_id  TEXT NOT NULL REFERENCES silver.crm_opportunities (opportunity_id),
    contact_id      TEXT NOT NULL REFERENCES silver.crm_contacts (contact_id),
    role            TEXT,
    -- flag: el contacto pertenece a una cuenta distinta a la de la oportunidad (99.9%)
    account_mismatch BOOLEAN NOT NULL DEFAULT FALSE,
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (opportunity_id, contact_id)
);

DROP TABLE IF EXISTS silver.crm_activities CASCADE;
CREATE TABLE silver.crm_activities (
    activity_id     TEXT PRIMARY KEY,
    type            TEXT,
    subject         TEXT,
    occurred_at     TIMESTAMPTZ,
    contact_id      TEXT REFERENCES silver.crm_contacts (contact_id),
    opportunity_id  TEXT REFERENCES silver.crm_opportunities (opportunity_id),
    -- flags del discovery:
    is_orphan        BOOLEAN NOT NULL DEFAULT FALSE, -- ambos FK nulos (2981)
    account_mismatch BOOLEAN NOT NULL DEFAULT FALSE, -- opp y contact de cuentas distintas
    _silver_loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);
