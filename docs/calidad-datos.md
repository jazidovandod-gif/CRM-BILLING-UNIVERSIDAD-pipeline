# Calidad de datos — hallazgos del discovery

Resultados del perfilado sobre los 18 CSV de origen en `data/raw/{university,billing,crm}/`, ejecutado el 2026-07-20.

## Resumen ejecutivo

| Categoría | Resultado |
|-----------|-----------|
| Duplicados en PKs | 0 en las 18 tablas |
| Huérfanos referenciales | 0 en todas las FK verificadas |
| Nulos problemáticos | 3 casos documentados (todos intencionales, no errores de datos) |
| Integridad cross-dominio | 100% match en `customers.external_ref` → `students.student_id` |

## Nulos detectados

### 1. `billing.customers.external_ref` — 5,000 nulos (50%)

| Métrica | Valor |
|---|---|
| Total filas | 10,000 |
| Nulos | 5,000 |
| Con valor | 5,000 |
| Match con `students.student_id` | 5,000 (100%) |

**Interpretación:** diseño intencional — la mitad de los clientes de billing son estudiantes de la universidad, la otra mitad son clientes externos (empresas/individuos).

**Regla Silver sugerida:** derivar `is_student BOOLEAN` de `external_ref IS NOT NULL`; mantener el nulo como NULL, no imputar.

### 2. `crm.activities.contact_id` — 5,976 nulos (29.9%)

**Interpretación:** actividades vinculadas solo a una oportunidad, sin contacto asociado.

**Regla Silver sugerida:** validar que al menos uno de `contact_id` / `opportunity_id` exista; documentar en `decisiones.md` si se descartan filas sin ninguna FK.

### 3. `crm.activities.opportunity_id` — 9,985 nulos (49.9%)

**Interpretación:** actividades vinculadas solo a un contacto (p. ej. llamadas de prospección sin oportunidad abierta todavía).

**Regla Silver sugerida:** misma validación cruzada que el punto anterior; clasificar `contact_only` / `opportunity_only` / `both`.

## Integridad referencial completa

| Relación | Huérfanos | Nulos (FK opcional) | Total filas |
|---|---|---|---|
| enrollments → students | 0 | 0 | 25,000 |
| enrollments → courses | 0 | 0 | 25,000 |
| enrollments → semesters | 0 | 0 | 25,000 |
| courses → professors | 0 | 0 | 300 |
| grades → enrollments | 0 | 0 | 60,000 |
| subscriptions → customers | 0 | 0 | 15,000 |
| subscriptions → products | 0 | 0 | 15,000 |
| invoices → customers | 0 | 0 | 50,000 |
| invoice_items → invoices | 0 | 0 | 150,000 |
| invoice_items → products | 0 | 0 | 150,000 |
| payments → invoices | 0 | 0 | 80,000 |
| contacts → accounts | 0 | 0 | 15,000 |
| opportunities → accounts | 0 | 0 | 3,000 |
| activities → contacts | 0 | 5,976 | 20,000 |
| activities → opportunities | 0 | 9,985 | 20,000 |
| customers.external_ref → students | 0 | 5,000 | 10,000 |

## Relaciones cross-dominio

### Enlace explícito: University ↔ Billing

`customers.external_ref` = `students.student_id`, match exacto 5,000/5,000 (100%), 0 huérfanos. Modelo conceptual: un estudiante puede existir también como cliente de billing (`external_ref` apunta a su `student_id`); los 5,000 clientes sin `external_ref` son clientes que no son estudiantes.

### Enlaces implícitos (sin FK directa)

- **CRM ↔ Billing:** no hay columna que vincule `accounts` con `customers`. Estrategias posibles para Gold: match por email (riesgo de duplicados), match por nombre+país (heurístico, baja confianza), o mantener ambos dominios separados.
- **CRM ↔ University:** sin enlace directo; un estudiante podría ser contacto de una cuenta CRM pero no hay FK que lo confirme.

### Propuesta para el modelo Gold

Dimensión puente `dim_person` para unificar identidades cross-dominio (`person_key` ↔ `source` [`student`/`customer`/`contact`] ↔ `source_id`), habilitando tablas de hechos como `fact_student_revenue`, `fact_enrollment_revenue` y `fact_account_pipeline`, y preguntas de negocio como:

1. ¿Los estudiantes que pagan suscripción tienen mejor rendimiento académico?
2. ¿Las cuentas CRM con oportunidades ganadas generan más revenue en billing?
3. ¿Cuál es el LTV de un estudiante vs. un cliente externo?
4. ¿Hay leads convertidos que nunca se convirtieron en clientes de billing?

## Validaciones adicionales recomendadas para Silver

```sql
-- Grades: score entre 0 y 100
-- Grades: weight entre 0 y 1, suma por enrollment ≈ 1
-- Invoices: due_at >= issued_at
-- Subscriptions: end_date >= start_date (cuando end_date no es null)
-- Invoice_items: line_total = quantity * unit_price (con tolerancia)
-- Payments: amount > 0
-- Opportunities: amount > 0 cuando stage = 'won'
```

## Outliers a investigar en discovery

- Estudiantes con `enrolled_at` posterior a semestres activos
- Facturas con `total = 0`
- Oportunidades con `close_date` anterior a `created_at`
- Pagos que exceden el total de la factura

Cada hallazgo tratado a partir de esta lista debe registrarse en [`decisiones.md`](./decisiones.md) con contexto, decisión tomada, alternativas descartadas e impacto.
