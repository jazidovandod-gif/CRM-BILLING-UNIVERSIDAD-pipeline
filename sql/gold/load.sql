-- ============================================================================
-- Carga Gold desde Silver. Idempotente: TRUNCATE + INSERT.
-- ============================================================================

TRUNCATE
    gold.fact_enrollment, gold.fact_invoice, gold.fact_payment,
    gold.fact_subscription, gold.fact_opportunity, gold.fact_activity,
    gold.fact_lead,
    gold.dim_date, gold.dim_student, gold.dim_customer, gold.dim_product,
    gold.dim_course, gold.dim_semester, gold.dim_account
    CASCADE;

-- ----------------------------------------------------------------- DIMENSIONES

INSERT INTO gold.dim_date (date_key, year, quarter, month, month_name, day, day_of_week, is_weekend)
SELECT d::date,
       extract(year FROM d), extract(quarter FROM d), extract(month FROM d),
       trim(to_char(d, 'Month')),
       extract(day FROM d), extract(isodow FROM d),
       extract(isodow FROM d) IN (6, 7)
FROM generate_series(DATE '2005-01-01', DATE '2027-12-31', INTERVAL '1 day') AS d;

INSERT INTO gold.dim_student (student_id, country, birth_date, enrolled_at, age_at_enrollment_lt_15)
SELECT student_id, country, birth_date, enrolled_at, age_at_enrollment_lt_15
FROM silver.university_students;

INSERT INTO gold.dim_customer (customer_id, is_student, student_id, segment, country, created_date)
SELECT customer_id, is_student, external_ref, segment, country, created_at::date
FROM silver.billing_customers;

INSERT INTO gold.dim_product (product_id, sku, name, category, monthly_price, active)
SELECT product_id, sku, name, category, monthly_price, active
FROM silver.billing_products;

INSERT INTO gold.dim_course (course_id, code, name, credits, department, professor_id, department_mismatch)
SELECT course_id, code, name, credits, department, professor_id, department_mismatch
FROM silver.university_courses;

INSERT INTO gold.dim_semester (semester_id, code, year, half, start_date, end_date)
SELECT semester_id, code, year, half, start_date, end_date
FROM silver.university_semesters;

INSERT INTO gold.dim_account (account_id, name, industry, country, annual_revenue, employees, employee_band, name_is_shared)
SELECT account_id, name, industry, country, annual_revenue, employees,
       CASE WHEN employees < 50 THEN 'small'
            WHEN employees <= 500 THEN 'mid'
            ELSE 'large' END,
       name_is_shared
FROM silver.crm_accounts;

-- ---------------------------------------------------------------------- HECHOS

-- Solo la fila superviviente de cada grupo de inscripciones duplicadas.
INSERT INTO gold.fact_enrollment
    (enrollment_id, student_id, course_id, semester_id, enrolled_date,
     status, has_grades, final_score, weight_sum_ok, passed)
SELECT e.enrollment_id, e.student_id, e.course_id, e.semester_id, e.enrolled_at,
       e.status, e.has_grades,
       g.final_score_weighted, g.weight_sum_ok,
       (g.final_score_weighted >= 60)
FROM silver.university_enrollments e
LEFT JOIN silver.enrollment_grade_summary g ON e.enrollment_id = g.enrollment_id
WHERE e.is_duplicate_survivor;

INSERT INTO gold.fact_invoice
    (invoice_id, customer_id, issued_date, due_date, currency,
     invoiced_amount, total_reported, status, payment_status_derived, has_no_items, is_total_mismatch)
SELECT invoice_id, customer_id, issued_at, due_at, currency,
       COALESCE(total, total_reported), total_reported,
       status, payment_status_derived, has_no_items, is_total_mismatch
FROM silver.billing_invoices;

INSERT INTO gold.fact_payment (payment_id, invoice_id, customer_id, paid_date, amount, method)
SELECT p.payment_id, p.invoice_id, i.customer_id, p.paid_at, p.amount, p.method
FROM silver.billing_payments p
JOIN silver.billing_invoices i ON p.invoice_id = i.invoice_id;

INSERT INTO gold.fact_subscription
    (subscription_id, customer_id, product_id, status, start_date, end_date,
     is_effectively_expired, invalid_date_range, monthly_price)
SELECT s.subscription_id, s.customer_id, s.product_id, s.status, s.start_date, s.end_date,
       s.is_effectively_expired, s.invalid_date_range, p.monthly_price
FROM silver.billing_subscriptions s
JOIN silver.billing_products p ON s.product_id = p.product_id;

INSERT INTO gold.fact_opportunity
    (opportunity_id, account_id, stage, amount, created_date, close_date,
     is_won, is_closed, is_close_before_created)
SELECT opportunity_id, account_id, stage, amount, created_at::date, close_date,
       is_won, is_closed, is_close_before_created
FROM silver.crm_opportunities;

INSERT INTO gold.fact_activity
    (activity_id, type, occurred_date, contact_id, opportunity_id, is_orphan, account_mismatch)
SELECT activity_id, type, occurred_at::date, contact_id, opportunity_id, is_orphan, account_mismatch
FROM silver.crm_activities;

INSERT INTO gold.fact_lead (lead_id, source, status, score, created_date, is_converted)
SELECT lead_id, source, status, score, created_at::date, is_converted
FROM silver.crm_leads;
