-- ============================================================================
-- Transformaciones Bronze -> Silver.
--
-- Idempotente: TRUNCATE + INSERT. Reconstruible en cualquier momento.
-- Los flags reproducen EXACTAMENTE los conteos del discovery
-- (ver docs/calidad-datos.md y notebooks/01_discovery.ipynb).
--
-- SNAPSHOT_DATE = 2026-07-20: fecha de análisis usada para flags temporales
-- (is_effectively_expired, is_past_due). Fija por reproducibilidad; en
-- producción se reemplazaría por CURRENT_DATE.
-- ============================================================================

TRUNCATE
    silver.university_semesters, silver.university_professors,
    silver.university_students, silver.university_courses,
    silver.university_enrollments, silver.university_grades,
    silver.enrollment_grade_summary,
    silver.billing_products, silver.billing_customers,
    silver.billing_subscriptions, silver.billing_invoices,
    silver.billing_invoice_items, silver.billing_payments,
    silver.crm_accounts, silver.crm_contacts, silver.crm_leads,
    silver.crm_opportunities, silver.crm_opportunity_contacts,
    silver.crm_activities
    RESTART IDENTITY CASCADE;

-- ------------------------------------------------------------------ UNIVERSITY

INSERT INTO silver.university_semesters (semester_id, code, year, half, start_date, end_date)
SELECT semester_id, code, year::smallint, half::smallint,
       start_date::date, end_date::date
FROM bronze.university_semesters;

INSERT INTO silver.university_professors (professor_id, first_name, last_name, email, department, hired_at)
SELECT professor_id, first_name, last_name, lower(email), department,
       NULLIF(hired_at, '')::date
FROM bronze.university_professors;

INSERT INTO silver.university_students
    (student_id, first_name, last_name, email, birth_date, enrolled_at, country, age_at_enrollment_lt_15)
SELECT student_id, first_name, last_name, lower(email),
       birth_date::date, enrolled_at::date, country,
       ((enrolled_at::date - birth_date::date)::numeric / 365.25) < 15
FROM bronze.university_students;

INSERT INTO silver.university_courses
    (course_id, code, name, credits, department, professor_id, department_mismatch)
SELECT c.course_id, c.code, c.name, c.credits::smallint, c.department, c.professor_id,
       (c.department <> p.department)
FROM bronze.university_courses c
JOIN bronze.university_professors p ON c.professor_id = p.professor_id;

WITH graded AS (SELECT DISTINCT enrollment_id FROM bronze.university_grades),
dedup AS (
    SELECT enrollment_id,
           count(*) OVER (PARTITION BY student_id, course_id, semester_id) AS grp_size,
           row_number() OVER (
               PARTITION BY student_id, course_id, semester_id
               ORDER BY CASE status
                        WHEN 'completed' THEN 1 WHEN 'failed' THEN 2
                        WHEN 'dropped' THEN 3 WHEN 'active' THEN 4 ELSE 5 END,
                        enrollment_id
           ) AS rn
    FROM bronze.university_enrollments
)
INSERT INTO silver.university_enrollments
    (enrollment_id, status, student_id, course_id, semester_id,
     enrolled_at_raw, enrolled_at, enrolled_at_out_of_window,
     is_duplicate_enrollment, is_duplicate_survivor, has_grades)
SELECT e.enrollment_id, e.status, e.student_id, e.course_id, e.semester_id,
       e.enrolled_at::date,
       s.start_date::date,
       (e.enrolled_at::date < s.start_date::date OR e.enrolled_at::date > s.end_date::date),
       (d.grp_size > 1),
       (d.rn = 1),
       (g.enrollment_id IS NOT NULL)
FROM bronze.university_enrollments e
JOIN bronze.university_semesters s ON e.semester_id = s.semester_id
JOIN dedup d ON e.enrollment_id = d.enrollment_id
LEFT JOIN graded g ON e.enrollment_id = g.enrollment_id;

WITH dup AS (
    SELECT grade_id,
           count(*) OVER (PARTITION BY enrollment_id, assessment) AS c
    FROM bronze.university_grades
)
INSERT INTO silver.university_grades
    (grade_id, assessment, score, weight, graded_at, enrollment_id, has_duplicate_assessment)
SELECT g.grade_id, g.assessment, g.score::numeric, g.weight::numeric,
       g.graded_at::date, g.enrollment_id, (d.c > 1)
FROM bronze.university_grades g
JOIN dup d ON g.grade_id = d.grade_id;

INSERT INTO silver.enrollment_grade_summary
    (enrollment_id, n_grades, weight_sum, weight_sum_ok, final_score_weighted, final_score_simple)
SELECT enrollment_id,
       count(*),
       sum(weight::numeric),
       abs(sum(weight::numeric) - 1) <= 0.01,
       sum(score::numeric * weight::numeric) / NULLIF(sum(weight::numeric), 0),
       avg(score::numeric)
FROM bronze.university_grades
GROUP BY enrollment_id;

-- --------------------------------------------------------------------- BILLING

INSERT INTO silver.billing_products (product_id, sku, name, category, monthly_price, active)
SELECT product_id, sku, name, category, monthly_price::numeric, (active = 'True')
FROM bronze.billing_products;

INSERT INTO silver.billing_customers
    (customer_id, external_ref, first_name, last_name, email, country, created_at, segment, is_student)
SELECT customer_id, NULLIF(external_ref, ''), first_name, last_name, lower(email),
       country, created_at::timestamptz, segment,
       (NULLIF(external_ref, '') IS NOT NULL)
FROM bronze.billing_customers;

INSERT INTO silver.billing_subscriptions
    (subscription_id, status, start_date, end_date, end_date_raw, customer_id, product_id,
     invalid_date_range, is_effectively_expired, active_sub_on_inactive_product)
SELECT s.subscription_id, s.status, s.start_date::date,
       CASE WHEN s.end_date::date < s.start_date::date THEN NULL ELSE s.end_date::date END,
       s.end_date::date,
       s.customer_id, s.product_id,
       (s.end_date::date < s.start_date::date),
       (s.status = 'active' AND s.end_date::date < DATE '2026-07-20'),
       (s.status = 'active' AND p.active = 'False')
FROM bronze.billing_subscriptions s
JOIN bronze.billing_products p ON s.product_id = p.product_id;

WITH item_sum AS (
    SELECT invoice_id, sum(line_total::numeric) AS total_items
    FROM bronze.billing_invoice_items GROUP BY invoice_id
),
pay_sum AS (
    SELECT invoice_id, sum(amount::numeric) AS total_paid
    FROM bronze.billing_payments GROUP BY invoice_id
)
INSERT INTO silver.billing_invoices
    (invoice_id, issued_at, due_at, total_reported, total, status, currency, customer_id,
     is_total_mismatch, has_no_items, is_past_due, paid_without_payment, payment_status_derived)
SELECT i.invoice_id, i.issued_at::date, i.due_at::date,
       i.total::numeric,
       it.total_items,
       i.status, i.currency, i.customer_id,
       (it.total_items IS NOT NULL AND abs(i.total::numeric - it.total_items) > 0.01),
       (it.invoice_id IS NULL),
       (i.due_at::date < DATE '2026-07-20' AND i.status <> 'paid'),
       (i.status = 'paid' AND ps.invoice_id IS NULL),
       CASE
           WHEN ps.total_paid IS NULL THEN 'unpaid'
           WHEN ps.total_paid > i.total::numeric + 0.01 THEN 'overpaid'
           WHEN ps.total_paid < i.total::numeric - 0.01 THEN 'partial'
           ELSE 'full'
       END
FROM bronze.billing_invoices i
LEFT JOIN item_sum it ON i.invoice_id = it.invoice_id
LEFT JOIN pay_sum ps ON i.invoice_id = ps.invoice_id;

INSERT INTO silver.billing_invoice_items
    (invoice_item_id, quantity, unit_price, line_total, invoice_id, product_id)
SELECT invoice_item_id, quantity::numeric, unit_price::numeric, line_total::numeric,
       invoice_id, product_id
FROM bronze.billing_invoice_items;

INSERT INTO silver.billing_payments (payment_id, amount, paid_at, method, invoice_id)
SELECT payment_id, amount::numeric, paid_at::date, method, invoice_id
FROM bronze.billing_payments;

-- ------------------------------------------------------------------------- CRM

WITH shared AS (SELECT name, count(*) AS c FROM bronze.crm_accounts GROUP BY name)
INSERT INTO silver.crm_accounts
    (account_id, name, industry, country, annual_revenue, employees, created_at, name_is_shared)
SELECT a.account_id, a.name, a.industry, a.country,
       a.annual_revenue::numeric, a.employees::int, a.created_at::timestamptz,
       (sh.c > 1)
FROM bronze.crm_accounts a
JOIN shared sh ON a.name = sh.name;

WITH dup_email AS (
    SELECT lower(email) AS le, count(*) AS c FROM bronze.crm_contacts GROUP BY lower(email)
)
INSERT INTO silver.crm_contacts
    (contact_id, first_name, last_name, email, phone, title, created_at, account_id, is_duplicate_email)
SELECT c.contact_id, c.first_name, c.last_name, lower(c.email), c.phone, c.title,
       c.created_at::timestamptz, c.account_id, (de.c > 1)
FROM bronze.crm_contacts c
JOIN dup_email de ON lower(c.email) = de.le;

INSERT INTO silver.crm_leads
    (lead_id, first_name, last_name, email, source, status, score, created_at, is_converted)
SELECT lead_id, first_name, last_name, lower(email), source, status,
       score::smallint, created_at::timestamptz, (status = 'converted')
FROM bronze.crm_leads;

WITH with_contacts AS (SELECT DISTINCT opportunity_id FROM bronze.crm_opportunity_contacts)
INSERT INTO silver.crm_opportunities
    (opportunity_id, name, stage, amount, close_date, created_at, account_id,
     is_close_before_created, is_closed, is_won, has_contacts)
SELECT o.opportunity_id, o.name, o.stage, o.amount::numeric, o.close_date::date,
       o.created_at::timestamptz, o.account_id,
       (o.close_date::date < o.created_at::timestamptz::date),
       (o.stage IN ('won', 'lost')),
       (o.stage = 'won'),
       (wc.opportunity_id IS NOT NULL)
FROM bronze.crm_opportunities o
LEFT JOIN with_contacts wc ON o.opportunity_id = wc.opportunity_id;

INSERT INTO silver.crm_opportunity_contacts (opportunity_id, contact_id, role, account_mismatch)
SELECT oc.opportunity_id, oc.contact_id, oc.role,
       (o.account_id <> c.account_id)
FROM bronze.crm_opportunity_contacts oc
JOIN bronze.crm_opportunities o ON oc.opportunity_id = o.opportunity_id
JOIN bronze.crm_contacts c ON oc.contact_id = c.contact_id;

INSERT INTO silver.crm_activities
    (activity_id, type, subject, occurred_at, contact_id, opportunity_id, is_orphan, account_mismatch)
SELECT a.activity_id, a.type, a.subject, a.occurred_at::timestamptz,
       NULLIF(a.contact_id, ''), NULLIF(a.opportunity_id, ''),
       (NULLIF(a.contact_id, '') IS NULL AND NULLIF(a.opportunity_id, '') IS NULL),
       (NULLIF(a.contact_id, '') IS NOT NULL AND NULLIF(a.opportunity_id, '') IS NOT NULL
        AND c.account_id <> o.account_id)
FROM bronze.crm_activities a
LEFT JOIN bronze.crm_contacts c ON NULLIF(a.contact_id, '') = c.contact_id
LEFT JOIN bronze.crm_opportunities o ON NULLIF(a.opportunity_id, '') = o.opportunity_id;
