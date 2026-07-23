"""Validación de la capa Silver.

Comprueba tres cosas:
  1. Reconciliación de conteos Bronze -> Silver (Silver no pierde filas).
  2. Cada flag de calidad reproduce el conteo esperado del discovery.
  3. Coherencia de columnas derivadas (nulos esperados, rangos).

Los conteos esperados usan aritmética NUMERIC exacta de PostgreSQL. Difieren
levemente del perfilado original en pandas (float) en los bordes de tolerancia:
`weight_sum_ok` (401 exacto vs 141 float) y las bandas de `payment_status_derived`.
El cálculo exacto es el correcto; ver docs/decisiones.md.

Uso (dentro del contenedor):
    docker exec bootcamp-jupyter python /home/jovyan/src/validate_silver.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_database_config  # noqa: E402


# Reconciliación de filas Bronze -> Silver (todas espejo salvo la derivada).
ROW_RECONCILIATION = [
    ("university_semesters", "university_semesters"),
    ("university_professors", "university_professors"),
    ("university_students", "university_students"),
    ("university_courses", "university_courses"),
    ("university_enrollments", "university_enrollments"),
    ("university_grades", "university_grades"),
    ("billing_products", "billing_products"),
    ("billing_customers", "billing_customers"),
    ("billing_subscriptions", "billing_subscriptions"),
    ("billing_invoices", "billing_invoices"),
    ("billing_invoice_items", "billing_invoice_items"),
    ("billing_payments", "billing_payments"),
    ("crm_accounts", "crm_accounts"),
    ("crm_contacts", "crm_contacts"),
    ("crm_leads", "crm_leads"),
    ("crm_opportunities", "crm_opportunities"),
    ("crm_opportunity_contacts", "crm_opportunity_contacts"),
    ("crm_activities", "crm_activities"),
]

# (etiqueta, SQL que devuelve un entero, valor esperado)
FLAG_CHECKS = [
    ("students.age_at_enrollment_lt_15",
     "SELECT count(*) FROM silver.university_students WHERE age_at_enrollment_lt_15", 636),
    ("courses.department_mismatch",
     "SELECT count(*) FROM silver.university_courses WHERE department_mismatch", 264),
    ("enrollments.enrolled_at_out_of_window",
     "SELECT count(*) FROM silver.university_enrollments WHERE enrolled_at_out_of_window", 22729),
    ("enrollments.is_duplicate_enrollment",
     "SELECT count(*) FROM silver.university_enrollments WHERE is_duplicate_enrollment", 46),
    ("enrollments.is_duplicate_survivor",
     "SELECT count(*) FROM silver.university_enrollments WHERE is_duplicate_survivor", 24977),
    ("enrollments.has_grades",
     "SELECT count(*) FROM silver.university_enrollments WHERE has_grades", 22786),
    ("grades.has_duplicate_assessment",
     "SELECT count(*) FROM silver.university_grades WHERE has_duplicate_assessment", 22867),
    ("grade_summary.weight_sum_ok (exacto)",
     "SELECT count(*) FROM silver.enrollment_grade_summary WHERE weight_sum_ok", 401),
    ("customers.is_student",
     "SELECT count(*) FROM silver.billing_customers WHERE is_student", 5000),
    ("subscriptions.invalid_date_range",
     "SELECT count(*) FROM silver.billing_subscriptions WHERE invalid_date_range", 783),
    ("subscriptions.is_effectively_expired",
     "SELECT count(*) FROM silver.billing_subscriptions WHERE is_effectively_expired", 7146),
    ("subscriptions.active_sub_on_inactive_product",
     "SELECT count(*) FROM silver.billing_subscriptions WHERE active_sub_on_inactive_product", 1753),
    ("invoices.is_total_mismatch",
     "SELECT count(*) FROM silver.billing_invoices WHERE is_total_mismatch", 47497),
    ("invoices.has_no_items",
     "SELECT count(*) FROM silver.billing_invoices WHERE has_no_items", 2502),
    ("invoices.paid_without_payment",
     "SELECT count(*) FROM silver.billing_invoices WHERE paid_without_payment", 3533),
    ("invoices.payment_status=overpaid (exacto)",
     "SELECT count(*) FROM silver.billing_invoices WHERE payment_status_derived='overpaid'", 20482),
    ("invoices.payment_status=partial (exacto)",
     "SELECT count(*) FROM silver.billing_invoices WHERE payment_status_derived='partial'", 10943),
    ("invoices.payment_status=full (exacto)",
     "SELECT count(*) FROM silver.billing_invoices WHERE payment_status_derived='full'", 8),
    ("invoices.payment_status=unpaid",
     "SELECT count(*) FROM silver.billing_invoices WHERE payment_status_derived='unpaid'", 18567),
    ("accounts.name_is_shared",
     "SELECT count(*) FROM silver.crm_accounts WHERE name_is_shared", 5000),
    ("contacts.is_duplicate_email",
     "SELECT count(*) FROM silver.crm_contacts WHERE is_duplicate_email", 4),
    ("leads.is_converted",
     "SELECT count(*) FROM silver.crm_leads WHERE is_converted", 205),
    ("opportunities.is_close_before_created",
     "SELECT count(*) FROM silver.crm_opportunities WHERE is_close_before_created", 1029),
    ("opportunities.is_won",
     "SELECT count(*) FROM silver.crm_opportunities WHERE is_won", 476),
    ("opportunities.has_contacts",
     "SELECT count(*) FROM silver.crm_opportunities WHERE has_contacts", 2586),
    ("opportunity_contacts.account_mismatch",
     "SELECT count(*) FROM silver.crm_opportunity_contacts WHERE account_mismatch", 5995),
    ("activities.is_orphan",
     "SELECT count(*) FROM silver.crm_activities WHERE is_orphan", 2981),
    ("activities.account_mismatch",
     "SELECT count(*) FROM silver.crm_activities WHERE account_mismatch", 7019),
]

# Coherencia de columnas derivadas (etiqueta, SQL, esperado).
DERIVED_CHECKS = [
    ("invoices.total NULL == has_no_items",
     "SELECT (count(*) FILTER (WHERE total IS NULL)) - (count(*) FILTER (WHERE has_no_items)) "
     "FROM silver.billing_invoices", 0),
    ("subscriptions.end_date NULL == invalid_date_range",
     "SELECT (count(*) FILTER (WHERE end_date IS NULL)) - (count(*) FILTER (WHERE invalid_date_range)) "
     "FROM silver.billing_subscriptions", 0),
    ("invoices.payment_status_derived nunca NULL",
     "SELECT count(*) FROM silver.billing_invoices WHERE payment_status_derived IS NULL", 0),
    ("enrollment_grade_summary sin nota ponderada NULL",
     "SELECT count(*) FROM silver.enrollment_grade_summary WHERE final_score_weighted IS NULL", 0),
    ("grades.score fuera de [0,100]",
     "SELECT count(*) FROM silver.university_grades WHERE score < 0 OR score > 100", 0),
]


def _scalar(cursor, query: str) -> int:
    cursor.execute(query)
    return int(cursor.fetchone()[0])


def main() -> None:
    database = get_database_config()
    failures = 0

    with psycopg2.connect(**database.as_psycopg_kwargs()) as conn:
        with conn.cursor() as cur:
            print("== Reconciliación de filas Bronze -> Silver ==")
            for bronze_table, silver_table in ROW_RECONCILIATION:
                b = _scalar(cur, f"SELECT count(*) FROM bronze.{bronze_table}")
                s = _scalar(cur, f"SELECT count(*) FROM silver.{silver_table}")
                ok = b == s
                failures += not ok
                print(f"  {'OK ' if ok else 'FALLA'}  {silver_table}: bronze={b:,} silver={s:,}")

            print("\n== Flags de calidad vs discovery ==")
            for label, query, expected in FLAG_CHECKS:
                got = _scalar(cur, query)
                ok = got == expected
                failures += not ok
                print(f"  {'OK ' if ok else 'FALLA'}  {label}: got={got:,} exp={expected:,}")

            print("\n== Coherencia de columnas derivadas ==")
            for label, query, expected in DERIVED_CHECKS:
                got = _scalar(cur, query)
                ok = got == expected
                failures += not ok
                print(f"  {'OK ' if ok else 'FALLA'}  {label}: got={got} exp={expected}")

    total = len(ROW_RECONCILIATION) + len(FLAG_CHECKS) + len(DERIVED_CHECKS)
    print(f"\n{total - failures}/{total} comprobaciones OK.")
    if failures:
        print(f"FALLARON {failures} comprobaciones.")
        sys.exit(1)
    print("Silver validado correctamente.")


if __name__ == "__main__":
    main()
