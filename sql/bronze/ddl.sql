-- Bronze: copia fiel de los 18 CSV con trazabilidad de ingesta.
-- Las columnas fuente permanecen como TEXT; el tipado de negocio corresponde a Silver.

CREATE SCHEMA IF NOT EXISTS bronze;

CREATE TABLE IF NOT EXISTS bronze.ingestion_batches (
    batch_id UUID PRIMARY KEY,
    source_domain TEXT NOT NULL,
    source_table TEXT NOT NULL,
    target_table TEXT NOT NULL,
    source_file TEXT NOT NULL,
    source_checksum CHAR(64) NOT NULL,
    expected_rows INTEGER NOT NULL CHECK (expected_rows >= 0),
    loaded_rows INTEGER NOT NULL DEFAULT 0 CHECK (loaded_rows >= 0),
    status TEXT NOT NULL CHECK (status IN ('loading', 'success', 'failed')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    UNIQUE (source_domain, source_table, source_checksum)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_batches_status
    ON bronze.ingestion_batches (status, started_at);

CREATE TABLE IF NOT EXISTS bronze.university_semesters (
    _bronze_id BIGSERIAL PRIMARY KEY,
    semester_id TEXT,
    code TEXT,
    year TEXT,
    half TEXT,
    start_date TEXT,
    end_date TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.university_professors (
    _bronze_id BIGSERIAL PRIMARY KEY,
    professor_id TEXT,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    department TEXT,
    hired_at TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.university_students (
    _bronze_id BIGSERIAL PRIMARY KEY,
    student_id TEXT,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    birth_date TEXT,
    enrolled_at TEXT,
    country TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.university_courses (
    _bronze_id BIGSERIAL PRIMARY KEY,
    course_id TEXT,
    code TEXT,
    name TEXT,
    credits TEXT,
    department TEXT,
    professor_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.university_enrollments (
    _bronze_id BIGSERIAL PRIMARY KEY,
    enrollment_id TEXT,
    enrolled_at TEXT,
    status TEXT,
    student_id TEXT,
    course_id TEXT,
    semester_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.university_grades (
    _bronze_id BIGSERIAL PRIMARY KEY,
    grade_id TEXT,
    assessment TEXT,
    score TEXT,
    weight TEXT,
    graded_at TEXT,
    enrollment_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.billing_customers (
    _bronze_id BIGSERIAL PRIMARY KEY,
    customer_id TEXT,
    external_ref TEXT,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    country TEXT,
    created_at TEXT,
    segment TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.billing_products (
    _bronze_id BIGSERIAL PRIMARY KEY,
    product_id TEXT,
    sku TEXT,
    name TEXT,
    category TEXT,
    monthly_price TEXT,
    active TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.billing_subscriptions (
    _bronze_id BIGSERIAL PRIMARY KEY,
    subscription_id TEXT,
    status TEXT,
    start_date TEXT,
    end_date TEXT,
    customer_id TEXT,
    product_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.billing_invoices (
    _bronze_id BIGSERIAL PRIMARY KEY,
    invoice_id TEXT,
    issued_at TEXT,
    due_at TEXT,
    total TEXT,
    status TEXT,
    currency TEXT,
    customer_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.billing_invoice_items (
    _bronze_id BIGSERIAL PRIMARY KEY,
    invoice_item_id TEXT,
    quantity TEXT,
    unit_price TEXT,
    line_total TEXT,
    invoice_id TEXT,
    product_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.billing_payments (
    _bronze_id BIGSERIAL PRIMARY KEY,
    payment_id TEXT,
    amount TEXT,
    paid_at TEXT,
    method TEXT,
    invoice_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.crm_accounts (
    _bronze_id BIGSERIAL PRIMARY KEY,
    account_id TEXT,
    name TEXT,
    industry TEXT,
    country TEXT,
    annual_revenue TEXT,
    employees TEXT,
    created_at TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.crm_contacts (
    _bronze_id BIGSERIAL PRIMARY KEY,
    contact_id TEXT,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    phone TEXT,
    title TEXT,
    created_at TEXT,
    account_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.crm_leads (
    _bronze_id BIGSERIAL PRIMARY KEY,
    lead_id TEXT,
    first_name TEXT,
    last_name TEXT,
    email TEXT,
    source TEXT,
    status TEXT,
    score TEXT,
    created_at TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.crm_opportunities (
    _bronze_id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT,
    name TEXT,
    stage TEXT,
    amount TEXT,
    close_date TEXT,
    created_at TEXT,
    account_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.crm_opportunity_contacts (
    _bronze_id BIGSERIAL PRIMARY KEY,
    opportunity_id TEXT,
    contact_id TEXT,
    role TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);

CREATE TABLE IF NOT EXISTS bronze.crm_activities (
    _bronze_id BIGSERIAL PRIMARY KEY,
    activity_id TEXT,
    type TEXT,
    subject TEXT,
    occurred_at TEXT,
    contact_id TEXT,
    opportunity_id TEXT,
    _batch_id UUID NOT NULL REFERENCES bronze.ingestion_batches (batch_id),
    _source_file TEXT NOT NULL,
    _source_domain TEXT NOT NULL,
    _source_row_number INTEGER NOT NULL,
    _row_hash CHAR(64) NOT NULL,
    _ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (_batch_id, _source_row_number)
);
