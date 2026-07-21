# Calidad de datos — hallazgos del discovery

Resultados del perfilado sobre los 18 CSV de origen en `data/raw/{university,billing,crm}/`.
El notebook fue corregido y reejecutado el 2026-07-21. La auditoría ampliada y sus
resultados reproducibles están en:

- [`notebooks/01_discovery.ipynb`](../notebooks/01_discovery.ipynb)
- [`analisis-datos-completo.md`](./analisis-datos-completo.md)
- [`analisis-datos-resultados.json`](./analisis-datos-resultados.json)
- [`src/comprehensive_data_audit.py`](../src/comprehensive_data_audit.py)

## Resumen ejecutivo

**Tesis del discovery:** el dataset es *estructuralmente perfecto* pero *semánticamente roto* en puntos específicos — montos y fechas fueron generados de forma independiente de sus tablas relacionadas. La estrategia de limpieza es: confiar en la estructura (FKs, PKs), desconfiar de la semántica derivada (totales, fechas correlacionadas, pesos), y **flaggear en vez de borrar**.

| Categoría | Resultado |
|-----------|-----------|
| Duplicados en PKs | 0 en las 18 tablas |
| Huérfanos referenciales | 0 en las 18 relaciones FK verificadas |
| Nulos | 3 columnas; 2,981 activities tienen ambas FK nulas |
| Integridad cross-dominio | 100% match en `customers.external_ref` → `students.student_id` (1:1) |
| **Reglas de negocio violadas** | **9 hallazgos críticos + 9 de severidad media/alta** (tabla al final) |

## Nulos detectados

### 1. `billing.customers.external_ref` — 5,000 nulos (50%)

| Métrica | Valor |
|---|---|
| Total filas | 10,000 |
| Nulos | 5,000 |
| Con valor | 5,000 |
| Match con `students.student_id` | 5,000 (100%) |

**Interpretación:** los valores presentes forman un bridge técnico 1:1 con students. Un
nulo solo demuestra que no existe una referencia académica; no permite inferir que el
cliente sea una empresa.

**Regla Silver sugerida:** derivar `has_student_reference BOOLEAN`; mantener el nulo como
NULL y no fusionar atributos personales.

### 2. `crm.activities.contact_id` — 5,976 nulos (29.9%)

**Interpretación:** este conteo por columna mezcla actividades con opportunity y
actividades sin ninguna relación.

**Regla Silver sugerida:** validar que al menos uno de `contact_id` / `opportunity_id` exista; documentar en `decisiones.md` si se descartan filas sin ninguna FK.

### 3. `crm.activities.opportunity_id` — 9,985 nulos (49.9%)

**Interpretación:** este conteo por columna mezcla actividades con contact y actividades
sin ninguna relación.

**Regla Silver sugerida:** evaluar ambas FK conjuntamente y clasificar
`contact_only` / `opportunity_only` / `both` / `unlinked`.

Combinación observada:

| Alcance | Filas |
|---|---:|
| Ambas FK | 7,020 |
| Solo contact | 7,004 |
| Solo opportunity | 2,995 |
| Ambas nulas (`unlinked`) | 2,981 |

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
| opportunity_contacts → opportunities | 0 | 0 | 6,000 |
| opportunity_contacts → contacts | 0 | 0 | 6,000 |
| activities → contacts | 0 | 5,976 | 20,000 |
| activities → opportunities | 0 | 9,985 | 20,000 |
| customers.external_ref → students | 0 | 5,000 | 10,000 |

## Relaciones cross-dominio

### Enlace explícito: University ↔ Billing

`customers.external_ref` = `students.student_id`, match exacto 5,000/5,000 (100%), 0 huérfanos. Modelo conceptual: un estudiante puede existir también como cliente de billing (`external_ref` apunta a su `student_id`); los 5,000 clientes sin `external_ref` son clientes que no son estudiantes.

### Enlaces implícitos (sin FK directa)

- **CRM ↔ Billing:** no hay una clave verificable. Nombre, país o email solo permitirían
  heurísticas de muy baja confianza; Gold debe mantener estos dominios separados.
- **CRM ↔ University:** no existe enlace directo verificable.

### Propuesta para el modelo Gold

Mantener dimensiones separadas y un bridge técnico exclusivamente entre student y
customer mediante `external_ref`. No consolidar contact ni fusionar PII. Los análisis
student-customer son técnicamente posibles, pero el vínculo es posicional y sus atributos
y comportamientos fueron generados de forma casi independiente.

## Reglas de negocio verificadas — resultados del perfilado profundo

Cada regla fue verificada con código sobre los 18 CSV (ver notebook, secciones 5–8). Los números fueron además re-verificados de forma independiente con un segundo script.

### Hallazgos críticos 🔴

| # | Hallazgo | Magnitud | Acción Silver |
|---|----------|----------|---------------|
| 1 | `invoices.total` no cuadra con la suma de sus items (correlación ≈ 0) | 47,497 de 47,498 facturas con items | Conservar `total_reported` y derivar `line_sum` + reconciliación |
| 2 | La suma de pagos no reconcilia con la factura | 20,483 sobre, 10,948 bajo y 2 exactas a centavos | Conservar `payment_sum` y derivar reconciliación; no sustituir medidas |
| 3 | Facturas `status='paid'` sin ningún pago registrado | 3,533 | Flag `paid_without_payment`; status = declarativo, pagos = medido |
| 4 | `grades.weight` no suma 1.0 por enrollment | 22,645 de 22,786 (99.4%) | Nota final renormalizada `Σ(score·w)/Σ(w)` + flag `weight_sum_ok` |
| 5 | Assessments duplicados en el mismo enrollment (dos "midterm", etc.) | 10,544 grupos, 22,867 filas (38.1% de grades) | Tratar grades como eventos de evaluación; flag `has_duplicate_assessment` |
| 6 | `enrollments.enrolled_at` sin relación con la ventana del semestre | Solo 9.1% dentro de [start, end]; 46.6% antes, 44.3% después | Preservar ambas fechas + flag `enrolled_at_out_of_window` |
| 7 | Relaciones CRM cruzan cuentas y bridges | 5,995/6,000 en `opportunity_contacts`; solo 4/7,020 pares de activities existen en el bridge | Flags de cuenta/bridge; analizar alcances por separado |
| 8 | `opportunities.close_date` anterior a `created_at` | 1,029 de 3,000 (34.3%), en todos los stages | Flag `is_close_before_created`; excluir de métricas de ciclo de venta |
| 9 | Atributos de persona no coinciden en los pares student↔customer vinculados | 0/5,000 mismo email, 1/5,000 mismo nombre, 21.4% mismo país (≈ azar) | Vínculo técnico sin merge de PII; flag `person_attributes_mismatch` |

### Hallazgos de severidad media/alta 🟡

| # | Hallazgo | Magnitud | Acción Silver |
|---|----------|----------|---------------|
| 10 | Activities huérfanas totales (ambos FK nulos) | 2,981 (14.9%) | Flag `is_orphan`; excluir de métricas de engagement |
| 11 | Suscripciones con `end_date < start_date` | 783 (5.2%) | Preservar original + flag `invalid_date_range` |
| 12 | Facturas sin ningún item | 2,502 (5.0%) | Flag `has_no_items`; usar `total_reported` |
| 13 | Suscripciones activas con `end_date` ya vencida (status congelado) | 7,154 al 2026-07-21 (63.5% de activas) | Derivar `is_effectively_expired` con fecha parametrizada |
| 14 | Suscripciones activas sobre productos `active=False` | 1,753 | Flag para revenue assurance (legacy plausible) |
| 15 | Inscripciones duplicadas lógicas (alumno+curso+semestre) | 23 grupos / 46 filas, 14 con status contradictorios | Flag y cuarentena antes de elegir superviviente |
| 16 | Estudiantes con <15 años al inscribirse (mínimo 10.2) | 636 (12.7%) | Flag `age_at_enrollment_lt_15`; edad no confiable |
| 17 | Cursos con profesor de otro departamento | 264/300 (88%) | Conservar ambos departamentos + flag de discrepancia |
| 18 | Solo 599 nombres distintos para 5,000 cuentas | Repetidos 2–19 veces | `name` no es clave de negocio ni criterio de dedupe |

### Informativos 🔵

- **Leads `converted` no rastreables** (205): 0 overlap de emails con contacts/customers/students — el funnel solo puede medirse por `status`.
- **Multi-moneda sin tipo de cambio** (8 currencies): toda agregación de montos debe segmentar por `currency`.
- **2,214 enrollments sin ninguna nota**, incluidos 1,303 `completed` — flag `completed_without_grades`.
- **`close_date` poblado en oportunidades abiertas**: es fecha *proyectada* de cierre, no real.
- **Fechas futuras**: solo `subscriptions.end_date` (5,518 filas, fin de vigencia programado — válido). Rango global del negocio: 2005-03-10 → 2027-12-31 (insumo para `dim_date`).
- **Items vs catálogo/suscripción**: solo 16/150,000 precios igualan el catálogo y
  646 líneas corresponden a una suscripción vigente.
- **Cronología adicional**: 19,809 payments preceden al customer y 4,729 enrollments
  referencian un student registrado después del fin del semester.

## Lo que está limpio (y se aprovecha)

Integridad referencial completa (18/18 FK sin huérfanos), PKs 100% únicas,
`invoice_items` internamente consistentes (`line_total = quantity × unit_price` en
150,000/150,000), catálogo de semesters coherente, formatos de email válidos y bridge
`external_ref` 1:1 sin huérfanos. La consistencia interna de items **no demuestra** que
sean la fuente verdadera de revenue.

Cada tratamiento aplicado en Silver a partir de esta lista se registrará en [`decisiones.md`](./decisiones.md) con contexto, decisión, alternativas descartadas e impacto.
