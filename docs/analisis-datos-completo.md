# Auditoría independiente completa de los datos

**Fecha de corte:** 2026-07-21

**Fuente:** 18 CSV de `data/raw/`

**Volumen:** 446,708 filas y 114 columnas

**Ejecución reproducible:** `src/comprehensive_data_audit.py`

**Resultados completos:** `docs/analisis-datos-resultados.json`

## Conclusión ejecutiva

El análisis independiente confirma la tesis principal del discovery: la estructura es
excelente, pero gran parte de la semántica entre tablas no representa procesos de negocio
coherentes.

- Las 18 tablas coinciden exactamente con `manifest.json`.
- No hay filas completamente duplicadas, PK duplicadas, valores numéricos/fechas
  imposibles de parsear ni FK huérfanas en las 18 relaciones verificadas.
- Los 20,961 valores nulos están concentrados en `customers.external_ref`,
  `activities.contact_id` y `activities.opportunity_id`.
- Las relaciones por identificador existen, pero fechas, cuentas, productos, precios,
  estados y atributos personales fueron asignados con muy poca dependencia entre sí.
- Los patrones de ocupación de las FK se parecen casi exactamente a una asignación
  aleatoria uniforme. Esto es evidencia fuerte de datos sintéticos generados por módulos
  independientes, aunque no prueba por sí solo el código del generador.

La consecuencia más importante es que no se debe declarar una única “fuente de verdad”
para revenue, identidad o atribución CRM. Bronze debe conservar todo; Silver debe exponer
las discrepancias; Gold debe publicar medidas paralelas con calidad y alcance explícitos.

## Comparación con el análisis existente

### Resultados confirmados

Se reprodujeron los hallazgos principales del notebook y la documentación:

- 0 PK duplicadas y 0 FK huérfanas.
- 5,000 `customers.external_ref` válidos, únicos y posicionales respecto de los 5,000
  estudiantes.
- 2,981 actividades sin contacto ni oportunidad.
- 47,497 de 47,498 facturas con líneas no coinciden con la suma de esas líneas.
- 2,502 facturas no tienen líneas.
- 3,533 facturas `paid` no tienen pagos.
- 22,645 de 22,786 grupos de notas quedan fuera de `1 ± 0.01`.
- 10,544 grupos de assessment duplicado, que abarcan 22,867 filas.
- 23 inscripciones lógicamente duplicadas; 14 tienen estados contradictorios.
- 1,029 oportunidades cierran antes de su creación.
- Solo 5 de 6,000 pares de `opportunity_contacts` comparten cuenta.
- Solo 1 de 7,020 actividades con ambas FK tiene cuentas coherentes.
- 0 emails y 1 nombre completo coinciden entre los 5,000 pares student-customer.

### Correcciones o matices necesarios

1. **Son 18 relaciones verificables, no 16.** El conteo de 16 omite las dos FK de
   `opportunity_contacts`.

2. **Los pagos no fueron generados sin relación con la factura.** Cada uno de los 80,000
   pagos representa entre 20 % y 100 % del total de su factura, ninguno excede
   individualmente el total y la correlación pago individual-total es 0.8872. El problema
   aparece al acumular varios pagos: la correlación suma-total sigue siendo 0.7772, pero
   20,483 facturas quedan por encima y 10,948 por debajo a precisión exacta de centavos.

3. **“Exacto” depende de la regla contable.** A precisión de centavos solo 2 sumas de
   pagos son iguales al total. Con tolerancia de ±1 centavo son 8; fuera de esa banda hay
   20,482 sobrepagadas y 10,943 parciales. El notebook mezcla floats y tolerancia, por eso
   reporta 20,483 / 10,945 / 5.

4. **`invoice_items` no está demostrado como fuente de verdad de revenue.** Su aritmética
   interna es perfecta, pero solo 16 de 150,000 `unit_price` coinciden con
   `products.monthly_price`, con correlación 0.0024. Solo 1,134 líneas corresponden a un
   producto alguna vez suscrito por el cliente y únicamente 646 ocurren dentro del
   intervalo de esa suscripción.

5. **El vencimiento depende de la fecha de corte.** El notebook obtuvo 7,146 suscripciones
   activas vencidas al 2026-07-20. Al 2026-07-21 son 7,154; no es una contradicción, sino
   una métrica temporal que debe parametrizarse.

6. **No conviene reemplazar ni deduplicar automáticamente.** Sustituir
   `enrollments.enrolled_at` por el inicio del semestre, anular fechas o elegir una fila
   por prioridad de status destruye evidencia. Primero deben conservarse los valores,
   generar flags y decidir formalmente si existe una regla de corrección defendible.

### Problemas encontrados en `src/extra_analysis.py`

- Llama “suscripciones superpuestas” a los 51 pares repetidos, pero no compara los
  intervalos. Hay 44 pares realmente superpuestos, con 88 filas involucradas.
- Usa tolerancia `0.001` para pesos y por eso obtiene 22,646 fallos; con la regla
  documentada `0.01` son 22,645.
- Imputa cero a facturas sin líneas y las cuenta como mismatch. El resultado 49,999 mezcla
  dos poblaciones: 47,497 mismatches comparables y 2,502 facturas sin detalle.
- La prueba titulada “leads convertidos sin oportunidades” solo busca el email en
  `contacts`; no comprueba oportunidades.

## Hallazgos nuevos — University

### Cronología adicional

- 1,901 de 25,000 inscripciones (7.60 %) ocurren antes de la contratación del profesor
  asignado al curso.
- En 4,729 inscripciones (18.92 %), el estudiante fue dado de alta después de que el
  semestre relacionado ya había terminado.
- 12,797 de 60,000 notas (21.33 %) son anteriores al alta del estudiante.
- Solo 5,745 notas (9.58 %) caen dentro del semestre asociado; 27,427 son anteriores y
  26,828 posteriores.
- Las 5,035 inscripciones con estado `active` pertenecen a semestres terminados antes de
  la fecha de corte. El status académico también está congelado.

### El status no describe el resultado académico

- La media de nota normalizada es prácticamente igual: `active` 75.06, `completed` 74.90,
  `dropped` 74.94 y `failed` 74.55.
- La asociación entre status y decil de nota es casi nula (Cramér V = 0.0225).
- 1,303 inscripciones `completed` no tienen ninguna nota.
- Solo 5,690 de 14,931 inscripciones `completed` tienen assessment `final`.

Por tanto, `failed`, `completed` y `dropped` no deben interpretarse como resultados
derivados de las calificaciones. Son atributos descriptivos independientes.

## Hallazgos nuevos — Billing

### Catálogo, suscripción y línea de factura no forman una cadena económica

- Solo 16 de 150,000 precios unitarios coinciden con el precio mensual del producto.
- Solo 1,112 (0.74 %) quedan siquiera dentro de ±1 % del precio de catálogo; el error
  relativo mediano es 63.53 %.
- La correlación entre ambos precios es 0.0024.
- Solo 1,134 líneas (0.76 %) pertenecen a un producto que el cliente haya suscrito alguna
  vez.
- Solo 646 líneas (0.43 %) coinciden además con una suscripción vigente en la fecha de la
  factura.
- Las categorías tampoco ordenan el precio: la mediana `enterprise` es 28.77 y la mediana
  `basic` es 32.27.

Esto invalida una interpretación SaaS directa de `invoice_items` como cargos derivados de
`subscriptions`.

### Pagos: lógica individual válida, reconciliación acumulada inválida

- Todos los pagos pertenecen a facturas `paid`.
- Ningún pago ocurre antes de la emisión y ninguno supera individualmente el total.
- Sin embargo, 19,809 pagos (24.76 %) ocurrieron antes de la creación del customer
  asociado a la invoice.
- El pago individual mediano equivale al 60.10 % del total; el rango es 20 %–100 %.
- 23,989 pagos (29.99 %) ocurren después del vencimiento.
- La demora va de 1 a 44 días, con mediana de 23.
- La sobreaplicación aparece cuando una factura recibe varios pagos parciales generados
  independientemente.

La suma de pagos puede usarse como flujo de caja registrado, pero no como saldo correcto
sin una regla de aplicación, reversos y tolerancias.

Además, las 10,048 invoices `pending` ya habían superado su `due_at` al 2026-07-21.
`pending` y `overdue` no representan estados vigentes sin conocer el proceso de
actualización del sistema fuente.

### Moneda

- Solo 8,868 de 50,000 facturas (17.74 %) usan la moneda natural del país del cliente.
- Si país y moneda fueran independientes, se esperarían 17.48 %. El resultado observado
  es prácticamente ese baseline.
- 55,742 de 80,000 payments (69.68 %) pertenecen a invoices no USD. `payments` no guarda
  currency y sus medianas nominales son casi iguales entre monedas (47.68–52.06),
  incluyendo CLP y COP.
- No existe tipo de cambio ni moneda en `payments` o `invoice_items`; estos heredan la
  moneda de la factura únicamente por contexto.

No se deben sumar importes entre monedas ni inferir moneda por país.

## Hallazgos nuevos — CRM

### La actividad no respeta el puente oficial

- De 7,020 actividades con contacto y oportunidad, solo 4 pares aparecen también en
  `opportunity_contacts` (0.057 %).
- Solo 1 de esas 7,020 combina entidades de la misma cuenta.

No basta con flaggear `account_mismatch`: `activities` y `opportunity_contacts` parecen
dos asignaciones independientes. Gold debe mantener actividad por contacto y actividad
por oportunidad como alcances separados.

### Cronología de entidades

- 7,456 de 15,000 contactos (49.71 %) fueron creados antes que su cuenta.
- 757 de 3,000 oportunidades (25.23 %) fueron creadas antes que su cuenta.
- Las 2,221 oportunidades abiertas tienen fecha proyectada de cierre vencida al
  2026-07-21.

### Variables comerciales con poca señal

- `annual_revenue` y `employees` no se relacionan: correlación Pearson -0.0004 y Spearman
  0.0049.
- `opportunity.amount` tampoco se relaciona con el revenue anual de la cuenta: Pearson
  -0.0352 y Spearman -0.0039.
- 94 oportunidades, incluidas 20 `won`, tienen monto superior al revenue anual completo
  de la cuenta.
- Stage y decil de amount tienen asociación muy débil (Cramér V = 0.0521).
- Status de lead y decil de score también tienen asociación débil (Cramér V = 0.0779);
  el score medio de convertidos es 50.84, prácticamente igual al resto.
- La conversión es 97/1,004 (9.66 %) con score menor a 50 y 108/996 (10.84 %) con score
  igual o superior a 50; el umbral apenas discrimina.

El score no sirve como modelo de conversión y los montos CRM deben verse como atributos
sintéticos, no como una jerarquía económica consistente.

## Hallazgos nuevos — Cross-domain

- El puente es exactamente posicional: los 5,000 pares cumplen `CUS-n → STU-n`.
- Esos enlaces corresponden exactamente al primer bloque de customer IDs; usar el ID o
  su orden como feature introduciría fuga de etiqueta.
- Las fechas de alta customer-student tienen correlación -0.0213.
- 2,901 de 7,573 subscriptions vinculadas (38.31 %) empiezan antes del alta del student.
- 5,512 de 25,071 invoices vinculadas (21.99 %) se emiten antes del alta del student.
- 8,573 de 40,264 payments vinculados (21.29 %) ocurren antes del alta del student.
- Coinciden en país 1,072 pares; el valor esperado por emparejamiento aleatorio es 1,076.1.
- La correlación entre nota académica e invoice count es -0.0132.
- La correlación entre nota y subscription count es 0.0000.
- Clientes con referencia y sin referencia presentan casi el mismo volumen medio:
  5.014 vs. 4.986 facturas y 1.515 vs. 1.485 suscripciones.
- También tienen cobertura de pago casi idéntica: 4,798/5,000 (95.96 %) vs.
  4,784/5,000 (95.68 %).

El enlace es utilizable como FK técnica porque está declarado y completo, pero el
comportamiento y los atributos de ambas filas se generaron de manera independiente. Los
análisis student-customer son posibles como ejercicio técnico, no como evidencia causal
realista.

## Evidencia de asignación aleatoria

El número de padres nunca referenciados coincide de forma muy cercana con el esperado al
repartir hijos uniformemente al azar:

- Grades sin enrollment cubierto: 2,214 observados vs. 2,267.84 esperados.
- Customers sin subscription: 2,224 vs. 2,231.13.
- Customers sin invoice: 67 vs. 67.36.
- Invoices sin item: 2,502 vs. 2,489.28.
- Accounts sin contact: 251 vs. 248.86.
- Accounts sin opportunity: 2,738 vs. 2,743.89.

Además, los nulos de las dos FK de activities se comportan como eventos independientes:
se observan 2,981 filas con ambas nulas frente a 2,983.52 esperadas por multiplicar sus
tasas marginales.

Esta evidencia explica por qué la integridad referencial es perfecta mientras la
coherencia de negocio es baja: el generador seleccionó IDs existentes, pero normalmente
sin coordinar atributos o eventos relacionados.

## Qué puede publicarse y qué no

### Publicable con controles

- Conteos, cobertura y distribuciones de entidades.
- Estados declarados, identificándolos como snapshot y no como estados derivados.
- Notas normalizadas, siempre acompañadas por flags de pesos, fechas y cobertura.
- Facturas, líneas y pagos como tres medidas distintas, segmentadas por moneda.
- Pipeline CRM por stage y cuenta desde la FK directa de opportunities.
- Actividad por contacto y por oportunidad en análisis separados.
- Cruce student-customer mediante `external_ref`, sin fusionar PII.

### No publicable como verdad de negocio

- Revenue único calculado desde header, líneas o pagos.
- MRR derivado de invoice items como si proviniera de subscriptions.
- Deuda = invoice total - payments sin política de aplicación de pagos.
- Resultado académico inferido directamente del status.
- Buying committees o actividad por cuenta usando los puentes CRM inconsistentes.
- Conversión real de leads.
- Identity resolution por nombre, email o país.
- Agregados monetarios mezclando currencies.

## Implicaciones para el modelado

### Bronze

Persistir los 18 CSV sin corregir, con `_batch_id`, `_source_file`, `_source_domain`,
`_ingested_at` y hash de fila.

### Silver

Conservar los valores reportados y añadir, como mínimo:

- `is_temporally_consistent`
- `is_account_consistent`
- `activity_scope`
- `activity_pair_exists_in_bridge`
- `has_student_reference`
- `invoice_line_reconciliation_status`
- `payment_reconciliation_status`
- `item_subscription_match_status`
- `country_currency_match`
- `grade_weight_status`
- `has_final_assessment`
- `is_effectively_expired`

Los fallos deben permanecer en la tabla o en cuarentena; ninguna regla encontrada permite
corregir el valor original con certeza.

### Gold

- Separar hechos académicos, de facturación, pagos, suscripciones, oportunidades y
  actividades.
- Exponer `invoice_total_reported`, `invoice_line_sum` y `payment_sum` sin sustituir una
  por otra.
- Publicar métricas de calidad junto con cada hecho.
- No combinar actividad por contacto y por oportunidad salvo que el par y la cuenta sean
  coherentes.
- Mantener student y customer como dimensiones separadas unidas por un bridge técnico.
- Exigir `currency_key` en todos los hechos financieros y evitar totales cross-currency.

## Reproducibilidad

Ejecutar:

```powershell
python src/comprehensive_data_audit.py --output docs/analisis-datos-resultados.json
```

La fecha de corte puede modificarse con `--as-of YYYY-MM-DD`; esto es obligatorio para
reproducir métricas de vigencia.
