"""Validación de la capa Gold.

Comprueba cuatro cosas:
  1. Conteos de filas de dimensiones y hechos.
  2. Integridad referencial dentro de Gold (hechos -> dimensiones, 0 huérfanos).
  3. Consistencia de los hechos con Silver (p. ej. fact_invoice == invoices).
  4. Coherencia de las vistas de KPI (totales y valores conocidos del negocio).

Uso (dentro del contenedor):
    docker exec bootcamp-jupyter python /home/jovyan/src/validate_gold.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg2

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import get_database_config  # noqa: E402


# (etiqueta, SQL escalar, valor esperado)
ROW_COUNTS = [
    ("dim_date", "SELECT count(*) FROM gold.dim_date", 8400),
    ("dim_student", "SELECT count(*) FROM gold.dim_student", 5000),
    ("dim_customer", "SELECT count(*) FROM gold.dim_customer", 10000),
    ("dim_product", "SELECT count(*) FROM gold.dim_product", 200),
    ("dim_course", "SELECT count(*) FROM gold.dim_course", 300),
    ("dim_semester", "SELECT count(*) FROM gold.dim_semester", 8),
    ("dim_account", "SELECT count(*) FROM gold.dim_account", 5000),
    ("fact_enrollment (supervivientes)", "SELECT count(*) FROM gold.fact_enrollment", 24977),
    ("fact_invoice", "SELECT count(*) FROM gold.fact_invoice", 50000),
    ("fact_payment", "SELECT count(*) FROM gold.fact_payment", 80000),
    ("fact_subscription", "SELECT count(*) FROM gold.fact_subscription", 15000),
    ("fact_opportunity", "SELECT count(*) FROM gold.fact_opportunity", 3000),
    ("fact_activity", "SELECT count(*) FROM gold.fact_activity", 20000),
    ("fact_lead", "SELECT count(*) FROM gold.fact_lead", 2000),
]

# Integridad referencial: hechos cuyo FK no existe en la dimensión (debe ser 0).
INTEGRITY = [
    ("fact_enrollment.student_id huérfano",
     "SELECT count(*) FROM gold.fact_enrollment f "
     "LEFT JOIN gold.dim_student d ON f.student_id=d.student_id WHERE d.student_id IS NULL", 0),
    ("fact_enrollment.enrolled_date fuera de dim_date",
     "SELECT count(*) FROM gold.fact_enrollment f "
     "LEFT JOIN gold.dim_date d ON f.enrolled_date=d.date_key WHERE d.date_key IS NULL", 0),
    ("fact_invoice.customer_id huérfano",
     "SELECT count(*) FROM gold.fact_invoice f "
     "LEFT JOIN gold.dim_customer d ON f.customer_id=d.customer_id WHERE d.customer_id IS NULL", 0),
    ("fact_subscription.product_id huérfano",
     "SELECT count(*) FROM gold.fact_subscription f "
     "LEFT JOIN gold.dim_product d ON f.product_id=d.product_id WHERE d.product_id IS NULL", 0),
    ("fact_opportunity.account_id huérfano",
     "SELECT count(*) FROM gold.fact_opportunity f "
     "LEFT JOIN gold.dim_account d ON f.account_id=d.account_id WHERE d.account_id IS NULL", 0),
]

# Consistencia Silver -> Gold (los hechos no pierden ni inventan filas).
CONSISTENCY = [
    ("fact_invoice == silver.billing_invoices",
     "SELECT (SELECT count(*) FROM gold.fact_invoice) - (SELECT count(*) FROM silver.billing_invoices)", 0),
    ("fact_payment == silver.billing_payments",
     "SELECT (SELECT count(*) FROM gold.fact_payment) - (SELECT count(*) FROM silver.billing_payments)", 0),
    ("fact_enrollment == inscripciones supervivientes",
     "SELECT (SELECT count(*) FROM gold.fact_enrollment) - "
     "(SELECT count(*) FROM silver.university_enrollments WHERE is_duplicate_survivor)", 0),
    ("invoiced_amount nunca NULL (COALESCE items/reported)",
     "SELECT count(*) FROM gold.fact_invoice WHERE invoiced_amount IS NULL", 0),
]

# Coherencia de las vistas de KPI (totales y valores conocidos del negocio).
KPI = [
    ("kpi_revenue_monthly cubre 50.000 facturas",
     "SELECT sum(invoices) FROM gold.kpi_revenue_monthly", 50000),
    ("kpi_revenue_monthly reporta 8 monedas",
     "SELECT count(DISTINCT currency) FROM gold.kpi_revenue_monthly", 8),
    ("kpi_collection: facturas pagadas = 34.966",
     "SELECT sum(paid_invoices) FROM gold.kpi_collection_by_currency", 34966),
    ("kpi_academic cubre las 24.977 supervivientes",
     "SELECT sum(enrollments) FROM gold.kpi_academic_by_department", 24977),
    ("kpi_subscription: activas = 11.272",
     "SELECT sum(subscriptions) FILTER (WHERE status='active') FROM gold.kpi_subscription_status", 11272),
    ("kpi_pipeline: won = 476",
     "SELECT sum(opportunities) FILTER (WHERE stage='won') FROM gold.kpi_sales_pipeline", 476),
    ("kpi_pipeline: lost = 303",
     "SELECT sum(opportunities) FILTER (WHERE stage='lost') FROM gold.kpi_sales_pipeline", 303),
    ("kpi_lead_funnel: convertidos = 205",
     "SELECT sum(leads) FILTER (WHERE status='converted') FROM gold.kpi_lead_funnel", 205),
    ("kpi_student_vs_external cubre 50.000 facturas",
     "SELECT sum(invoices) FROM gold.kpi_student_vs_external", 50000),
]


def _scalar(cursor, query: str) -> int:
    cursor.execute(query)
    result = cursor.fetchone()[0]
    return int(result) if result is not None else 0


def _run_block(cur, title: str, checks) -> int:
    print(f"\n== {title} ==")
    failures = 0
    for label, query, expected in checks:
        got = _scalar(cur, query)
        ok = got == expected
        failures += not ok
        print(f"  {'OK ' if ok else 'FALLA'}  {label}: got={got:,} exp={expected:,}")
    return failures


def main() -> None:
    database = get_database_config()
    failures = 0
    with psycopg2.connect(**database.as_psycopg_kwargs()) as conn:
        with conn.cursor() as cur:
            failures += _run_block(cur, "Conteos de dimensiones y hechos", ROW_COUNTS)
            failures += _run_block(cur, "Integridad referencial (Gold)", INTEGRITY)
            failures += _run_block(cur, "Consistencia Silver -> Gold", CONSISTENCY)
            failures += _run_block(cur, "Coherencia de vistas de KPI", KPI)

    total = len(ROW_COUNTS) + len(INTEGRITY) + len(CONSISTENCY) + len(KPI)
    print(f"\n{total - failures}/{total} comprobaciones OK.")
    if failures:
        print(f"FALLARON {failures} comprobaciones.")
        sys.exit(1)
    print("Gold validado correctamente.")


if __name__ == "__main__":
    main()
