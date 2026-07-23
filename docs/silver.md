# Capa Silver

Datos limpios, tipados, estandarizados y con calidad **explícita**. Silver toma Bronze (todo `TEXT`) y produce tablas tipadas donde cada anomalía del discovery es una columna-flag consultable.

**Filosofía:** *preservar + flaggear + derivar*, nunca sobrescribir. Se conserva el valor original (`total_reported`, `enrolled_at_raw`, `end_date_raw`) junto a la versión corregida y un flag. No se borra ninguna fila: Silver conserva las 446.708 filas de Bronze; Gold decide qué filtrar.

- **Schema:** `silver`
- **Scripts:** [`sql/silver/ddl.sql`](../sql/silver/ddl.sql) (estructura), [`sql/silver/transform.sql`](../sql/silver/transform.sql) (Bronze→Silver)
- **Validación:** [`src/validate_silver.py`](../src/validate_silver.py)

## Tablas

18 tablas espejo de Bronze (tipadas) + 1 derivada:

| Tabla | Tipado destacado | Flags de calidad |
|---|---|---|
| `university_semesters` | `year`/`half` SMALLINT, fechas DATE | — |
| `university_professors` | `hired_at` DATE | — |
| `university_students` | `birth_date`, `enrolled_at` DATE | `age_at_enrollment_lt_15` |
| `university_courses` | `credits` SMALLINT | `department_mismatch` |
| `university_enrollments` | fechas DATE | `enrolled_at_out_of_window`, `is_duplicate_enrollment`, `is_duplicate_survivor`, `has_grades` |
| `university_grades` | `score`/`weight` NUMERIC | `has_duplicate_assessment` |
| `enrollment_grade_summary` *(derivada)* | nota renormalizada | `weight_sum_ok` |
| `billing_products` | `monthly_price` NUMERIC, `active` BOOLEAN | — |
| `billing_customers` | `created_at` TIMESTAMPTZ | `is_student` |
| `billing_subscriptions` | fechas DATE | `invalid_date_range`, `is_effectively_expired`, `active_sub_on_inactive_product` |
| `billing_invoices` | `total`/`total_reported` NUMERIC | `is_total_mismatch`, `has_no_items`, `is_past_due`, `paid_without_payment`, `payment_status_derived` |
| `billing_invoice_items` | `line_total` NUMERIC | — |
| `billing_payments` | `amount` NUMERIC | — |
| `crm_accounts` | `annual_revenue` NUMERIC, `employees` INT | `name_is_shared` |
| `crm_contacts` | `created_at` TIMESTAMPTZ | `is_duplicate_email` |
| `crm_leads` | `score` SMALLINT | `is_converted` |
| `crm_opportunities` | `amount` NUMERIC | `is_close_before_created`, `is_closed`, `is_won`, `has_contacts` |
| `crm_opportunity_contacts` | PK compuesta | `account_mismatch` |
| `crm_activities` | `occurred_at` TIMESTAMPTZ | `is_orphan`, `account_mismatch` |

## Transformaciones clave

Estandarización general: emails a minúscula, `active` `'True'/'False'` → BOOLEAN, fechas/timestamps tipados, faltantes (`''` en Bronze) → NULL con `NULLIF`.

Reglas formales (justificadas en [`decisiones.md`](./decisiones.md)):

1. **Facturas** — `total` recalculado = Σ(`line_total`) de items (única medida internamente consistente); original en `total_reported`. Sin items → `total` NULL.
2. **Notas** — nota final por inscripción renormalizada `Σ(score·w)/Σ(w)` en `enrollment_grade_summary` (los pesos crudos no suman 1).
3. **Inscripciones** — `enrolled_at` canónico = `semester.start_date` (el crudo es ruido); superviviente de duplicados por prioridad `completed > failed > dropped > active`.
4. **Pagos** — `payment_status_derived` (unpaid/partial/full/overpaid); no se usan como revenue.
5. **CRM / cross-domain** — solo flags; sin merge de PII entre `student` y `customer`.

## Validación

[`src/validate_silver.py`](../src/validate_silver.py) — **51 comprobaciones**: reconciliación de filas Bronze→Silver, cada flag contra el conteo del discovery, y coherencia de columnas derivadas.

> **Nota float vs NUMERIC exacto:** algunos conteos difieren levemente del perfilado original en pandas por redondeo en los bordes de tolerancia (`weight_sum_ok` = 401, no 141; bandas de `payment_status_derived`). El cálculo exacto de Postgres es el correcto y es el que valida el script.

## Ejecutar Silver

```powershell
docker exec bootcamp-jupyter python /home/jovyan/src/run_sql.py sql/silver/ddl.sql sql/silver/transform.sql
docker exec bootcamp-jupyter python /home/jovyan/src/validate_silver.py
```
