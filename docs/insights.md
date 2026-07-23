# Insights de negocio — capa Gold

Hallazgos accionables obtenidos consultando el modelo Gold. **Método:** cada insight fue minado con SQL sobre `gold`/`silver`, **re-verificado de forma independiente** (queries reescritas desde cero) y sometido a una **tercera pasada de QA contra los CSV crudos** (`data/raw/`, sin pasar por la base). Solo se publican números confirmados. Fecha de análisis: 2026-07-20 (snapshot); datos operativos 2022–2025.

> **Nota de honestidad metodológica:** el dataset es sintético. Cuando un patrón delata al generador de datos (p. ej. uniformidades imposibles en un negocio real), el insight se marca con 🎲 y se reporta igual — saber que un dato *no discrimina* también es un hallazgo, y en producción sería una señal de alerta de calidad.

---

## Resumen ejecutivo — los 6 titulares

| # | Insight | Número clave |
|---|---------|--------------|
| 0 | **No hay una medida de revenue confiable** — cabecera ≈ pagos, pero items 5× | 6,79M ≈ 6,49M vs 34,93M |
| 1 | **El MRR real es un tercio del reportado** — 63% de las suscripciones "activas" ya venció | MRR real **194,7K** vs 532,5K nominal |
| 2 | **30% de lo facturado está en la calle**, con ~900 días de mora promedio | 15.034 facturas (30,1%) |
| 3 | **El tier más barato sostiene el negocio** — basic 43% del revenue, enterprise 9% | Mismo orden en las 8 monedas |
| 4 | **Cold call convierte 1,7× mejor que web** y el lead score no discrimina (50,8 vs 50,0) | 14,7% vs 8,5% de conversión |
| 5 | **5.859 facturas sin respaldo documental** (sin items o "pagadas" sin pago) | Riesgo de auditoría directo |

*(Nota: las cifras absolutas de revenue usan la medida de items; ver la nota crítica al inicio de la sección 1. En escala cabecera/pagos son ~5× menores. Las conclusiones cualitativas y de tendencia no cambian.)*

---

## 1. Revenue y facturación

> ### ⚠️ Nota crítica sobre la medida de revenue — leer antes de esta sección
>
> El dataset tiene **tres medidas de dinero que no concilian entre sí** (verificado contra los CSV crudos):
>
> | Medida | Total (todas las monedas) | Ratio vs header |
> |---|---|---|
> | `invoices.total` (header/cabecera crudo) | **6.791.850** | 1,00× |
> | `Σ payments.amount` (pagos) | **6.493.685** | **0,96×** |
> | `Σ invoice_items.line_total` (items) | **34.931.806** | **5,14×** |
>
> **Header y pagos casi coinciden (0,96×); los items son 5,14× más grandes.** No hay una fuente de verdad única de revenue (esto es *el* hallazgo, ver 1.0). Nuestro modelo Gold definió `invoiced_amount` = **suma de items** (decisión documentada en `decisiones.md`: los items son internamente consistentes, `line_total = qty·unit` en 150.000/150.000). **Por lo tanto, todas las cifras de revenue de esta sección usan la medida de items** y son ~5× las del header/pagos. Donde el header importa (ticket facturado, cartera cobrable real), se indica explícitamente. Las conclusiones de **tendencia y mix son proporcionales**: no dependen de qué medida se elija.

### 1.0 ⭐ No existe una medida de revenue confiable: las tres difieren hasta 5×
- **Evidencia:** header `Σ invoices.total` = 6.791.850; `Σ payments` = 6.493.685 (0,96× del header); `Σ items line_total` = 34.931.806 (5,14×). Header y pagos concuerdan a nivel agregado; los items quintuplican a ambos. Por factura, además, el header está descorrelacionado de los items (corr ≈ 0).
- **Interpretación:** en un ERP sano, cabecera = suma de líneas = lo pagado. Acá las tres divergen radicalmente. La coincidencia header ≈ pagos sugiere que **~6,8M es la escala de dinero "facturado/cobrado"** y que los items (34,9M) son un detalle inflado o generado aparte. No se puede afirmar un número único de revenue.
- **Acción:** Gold ya publica las tres por separado (`total_reported`, `invoiced_amount`/items, y pagos vía `fact_payment`). Presentar las tres en la ejecutiva como evidencia de por qué el revenue no es auditable con una sola cifra; en producción, reconciliar cabecera↔líneas↔pagos en origen.

### 1.1 Revenue estancado 4 años, sin estacionalidad 🎲
- **Evidencia (medida items):** USD: 2.620.555 (2022) → 2.715.133 (2023) → 2.770.977 (2024) → 2.587.455 (2025): −6,6% vs pico 2024, −1,3% vs 2022. CLP −6,7% en el período. EUR +2,7%, MXN +6,6%. Rango mensual USD 178K–264K (en escala header: USD ~520K/año, ~35K–58K/mes — misma tendencia, ÷5).
- **Interpretación:** el negocio no crece; las dos plazas principales (USD y CLP, 60,5% de las facturas) cierran 2025 por debajo de 2022. La **tendencia plana es idéntica en cualquiera de las tres medidas** (es proporcional).
- **Acción:** priorizar iniciativas de crecimiento (upsell de tiers) sobre optimización estacional, que no aplica.

### 1.2 30% de lo facturado sin cobrar, mora promedio ~900 días 🎲
- **Evidencia:** 15.034 facturas abiertas (10.048 pending + 4.986 overdue) = **30,1% de 50.000** (el % es el hallazgo robusto, no depende de la medida). Monto sin cobrar: en escala **items** USD 3.206.972 / CLP 3.114.777; en escala **header** (cartera facturada real) USD ~615K / CLP ~636K. Antigüedad media desde `due_at`: ~885–916 días; **3.724 facturas de 2022 siguen abiertas**.
- **Interpretación:** no existe proceso de cobranza ni política de castigo — cuentas por cobrar de 2,5 años inflan el activo. (La uniformidad del 30% delata al generador, pero la ausencia de aging es el mensaje operativo.)
- **Acción:** dunning automático 30/60/90 días; provisión/castigo de todo lo vencido >365 días; KPI de cobranza por cohorte de emisión.

### 1.3 La pirámide de revenue está invertida: basic 43%, enterprise 9%
- **Evidencia:** por categoría de producto (Σ items, USD): basic 4.545.182 (42,9%) > standard 3.073.305 (29,0%) > premium 1.990.751 (18,8%) > enterprise 980.565 (9,3%). **El mismo orden se repite en las 8 monedas.** (Al ser proporciones, el ranking no depende de la medida.)
- **Interpretación:** el tier más barato sostiene la facturación; los tiers de valor no despegan — pricing no competitivo o fuerza comercial que no migra clientes hacia arriba.
- **Acción:** playbook global de upsell basic→standard/premium (el patrón es idéntico en todas las plazas) y revisión del empaquetado enterprise.

### 1.4 El segmento "enterprise" no paga ticket premium 🎲
- **Evidencia:** ticket promedio por factura, plano entre segmentos. En escala **items**: retail 706,58 / smb 712,00 / enterprise 675,54. En escala **header** (ticket facturado, más intuitivo): retail ~138 / smb ~132 / enterprise ~137. En ambas escalas la banda es plana y enterprise ≤ retail. Retail genera 69,9% del revenue.
- **Interpretación:** la segmentación no se traduce en monetización — el revenue depende del volumen retail, no de un ticket premium por segmento.
- **Acción:** auditar la política de precios por segmento o sincerar la segmentación.

### 1.5 Riesgo de auditoría: 5.859 facturas sin respaldo 🎲
- **Evidencia:** 2.502 facturas **sin ningún item** (USD 104.317; CLP 112.646; resto ~129K) + 3.533 facturas `paid` **sin ningún pago registrado** (USD 763.741; CLP 736.506; resto ~1,04M). Los dos conjuntos se solapan en 176 facturas → **5.859 facturas únicas** afectadas. Además, de las 34.966 facturas marcadas `paid`, **solo 8 (0,023%) cuadran exacto** con sus pagos: 20.482 están sobrepagadas, 10.943 pagadas de menos y 3.533 sin ningún pago.
- **Interpretación:** 5% de las facturas no puede probar qué se vendió y 10% de las "cobradas" no puede probar que se cobró; y de las que sí tienen pago, prácticamente ninguna concilia con el monto facturado.
- **Acción:** cuarentenar en reporte de excepciones y excluir del revenue "confirmado"; en origen, bloquear facturas sin líneas y derivar `paid` solo de pagos registrados (el modelo ya expone `payment_status_derived`).

---

## 2. Suscripciones y revenue recurrente

### 2.1 ⭐ El MRR real es 194,7K, no 532,5K: el 63% del MRR "activo" ya venció
- **Evidencia:** de 11.272 suscripciones `active` (MRR nominal 532.490), 7.146 tienen `end_date` vencida y aportan 337.817 (63,4%). Solo 4.126 están vigentes: **MRR real 194.674**. Del vencido: 2.229 contratos vencieron en 2024, 2.809 en 2025, 1.525 en 2026 y 583 tienen rango de fechas inválido (`end_date` anulada en Silver) — total 7.146.
- **Interpretación:** cualquier dashboard que sume por status reporta un MRR ~3× inflado; 3.745 contratos llevan más de un año vencidos sin cerrar ni renovar (5.038 vencieron durante 2024–2025).
- **Acción:** KPI oficial de MRR = `active AND NOT is_effectively_expired`. Campaña de renovación empezando por los 1.525 vencidos en 2026 (73.053 de MRR recuperable, vencimiento reciente).

### 2.2 14,3% del MRR vigente corre sobre productos descontinuados
- **Evidencia:** 30 de 200 productos tienen `active=false`, pero soportan 674 suscripciones vigentes con MRR 27.757 (14,3% del MRR real).
- **Interpretación:** revenue legacy sin roadmap — primeras candidatas a churn al vencer el contrato.
- **Acción:** plan de migración dirigido hacia el catálogo activo, empezando por mayor `monthly_price`, con fecha de end-of-support.

### 2.3 El libro perdido casi iguala al MRR vivo: 173,1K vs 194,7K
- **Evidencia:** 2.242 cancelled (102.305 de MRR) + 1.486 paused (70.829) = 24,9% de la base y el 89% del MRR vigente.
- **Interpretación:** por cada peso vivo hay casi un peso caído o congelado. Las pausadas son el objetivo más rentable: el cliente no se fue.
- **Acción:** playbook de reactivación sobre las 1.486 pausadas (70,8K de MRR potencial); análisis de causa-raíz sobre las cancelled.

### 2.4 El contrato típico dura ~41 meses: la renovación es anticipable 🎲
- **Evidencia:** sobre 14.217 suscripciones con fechas válidas: mediana 1.243 días, promedio 1.261 (distribución estable).
- **Interpretación:** el vencimiento es predecible con meses de anticipación — exactamente lo que hoy no se gestiona (ver 2.1).
- **Acción:** alertas de renovación a 90/60/30 días del `end_date`.

### 2.5 Concentración: basic = 49% del MRR y un solo SKU = 7,6% 🎲
- **Evidencia:** MRR vigente por categoría: basic 96.181 (49,4%) > standard 51.811 > premium 31.465 > enterprise 15.216. El producto top (SKU-00177, "basic", 491,47/mes) concentra 14.744 = 7,6% del MRR en 30 clientes. Precio promedio de catálogo *invertido*: enterprise 36,76 < standard 43,05 < premium 43,97 < basic 51,48.
- **Interpretación:** catálogo sin arquitectura de precios (artefacto del generador, pero en un negocio real sería crítico) y riesgo de concentración en un SKU.
- **Acción:** monitorear el SKU top con plan de retención dedicado; auditar pricing por tier.

---

## 3. Rendimiento académico

### 3.1 Las notas no discriminan: todo promedio converge a ~75 🎲
- **Evidencia:** promedio por departamento 74,68–75,15 (stddev ~8,5–8,9 en todos); por semestre 74,76–75,08; por país brecha máxima 0,78 puntos; mejor curso 77,69, peor 71,74 (n≥30).
- **Interpretación:** las notas provienen de una única distribución ~N(75; 8,7) independiente de departamento, curso o país. **Ningún ranking académico sobre estos datos es informativo** — y detectarlo es evidencia de la calidad del pipeline.
- **Acción:** no construir rankings; en producción, monitorear la dispersión entre cursos como señal de salud del dato.

### 3.2 ⭐ 1.303 inscripciones "completed" sin ninguna nota (8,7%)
- **Evidencia:** de 14.931 completed en `silver.university_enrollments`, 1.303 no tienen ninguna evaluación registrada (8,73%). Rango por semestre: 7,99%–9,31% — estructural en los 8 semestres, con leve mejora en 2025. (En `gold.fact_enrollment`, tras el dedupe, hay 14.924 completed; el conteo de actas sin nota no cambia.)
- **Interpretación:** cierre de actas incompleto: 1 de cada 11 cursos "aprobados" no tiene respaldo académico.
- **Acción:** regla de negocio en origen: no cerrar como `completed` sin al menos una nota; regularizar el backlog de 1.303 actas.

### 3.3 Pérdida académica estancada en ~20% durante 4 años
- **Evidencia:** dropped+failed por año: 20,30% (2022) → 20,24% → 20,08% → 19,88% (2025). 2.500 dropped + 2.526 failed sobre 24.977.
- **Interpretación:** 1 de cada 5 inscripciones se pierde y nada movió la aguja en 4 años; mitad abandono, mitad reprobación.
- **Acción:** fijar 20% como línea base con meta (−2 pts en 2 semestres); alerta temprana sobre las ~5.000 `active` del semestre en curso.

### 3.4 El status está desacoplado de las notas 🎲
- **Evidencia:** promedio de nota final por status: completed 74,90 / **failed 74,55** / dropped 74,94. El 91% de los dropped tiene nota final completa. Más contundente aún: de los 2.526 `failed`, **2.179 (94,5% de los que tienen nota) tienen nota final ≥ 60**, es decir aprobatoria.
- **Interpretación:** un "reprobado" no solo rinde igual que un "aprobado" — el 94,5% directamente aprobó por nota. Status y nota cuentan historias contradictorias (artefacto), y no pueden usarse juntos sin regla de precedencia.
- **Acción:** contrato de datos: `status` es la fuente de verdad para retención; check de consistencia (failed ⇒ nota < umbral) en el validador de Silver para producción.

### 3.5 Sin saturación de cursos: carga uniforme (~10 alumnos/sección)
- **Evidencia:** alumnos por curso-semestre: 10,2–10,8 según departamento; máximo absoluto 22.
- **Interpretación:** la oferta está bien dimensionada; no hay caso de negocio para abrir secciones por congestión — sí, quizás, para consolidar secciones chicas.
- **Acción:** descartar "ampliar oferta"; evaluar consolidación de secciones pequeñas recurrentes.

### 3.6 Solo el 38% de los cursos aprobados tuvo examen "final"
- **Evidencia:** de 14.931 inscripciones `completed`, solo **5.690 (38,1%)** tienen una evaluación de tipo `final`. Combinado con las 1.303 (8,7%) sin ninguna nota, la cobertura de evaluación es parcial.
- **Interpretación:** el 62% de los cursos "aprobados" se cerró sin examen final registrado — o el final no es obligatorio, o hay subregistro de evaluaciones.
- **Acción:** definir en la regla de negocio si `final` es obligatorio para cerrar como `completed`.

### 3.7 38 estudiantes "fantasma" sin ninguna inscripción
- **Evidencia:** 38 de 5.000 estudiantes (0,76%) nunca se inscribieron en ningún curso.
- **Interpretación:** existen en el sistema pero sin actividad académica — registros sin uso.
- **Acción:** flag `has_enrollment` en `dim_student`; depurar o investigar altas sin matrícula.

*(Nota técnica: el 98,2% de las inscripciones con notas tiene pesos que no suman 100% — el `final_score` se calcula con pesos renormalizados, supuesto declarado en `decisiones.md`.)*

---

## 4. CRM y visión cross-dominio

### 4.1 Finance gana más; las cuentas grandes, menos — y el tamaño del deal no decide
- **Evidencia:** win rate global 61,1% (476/779 cerradas). Finance 68,9% (n=90) vs education 57,0% y health 58,7%. Por tamaño: small 64,6% / mid 58,5% / large 50,0% (n=22, muestra chica). Deal promedio: won 38.573 vs lost 39.409 — los perdidos son *ligeramente más grandes*.
- **Interpretación:** no se pierde por perseguir deals chicos: se pierde parejo en todos los tamaños, con más fricción en cuentas mid/large. (n chicos en finance/large: brecha sugestiva, no significativa.)
- **Acción:** replicar el playbook de finance en education/health; recursos senior a cuentas mid/large; no priorizar pipeline por monto.

### 4.2 El ciclo de venta no es reportable: 1 de cada 3 cierres tiene fechas rotas 🎲
- **Evidencia:** 270 de 779 cerradas (34,7%) con `close_date < created_at`. Entre las 509 coherentes: mediana 542 días, IQR 269–860.
- **Interpretación:** un tercio del pipeline queda fuera de cualquier métrica de velocidad, y el resto no describe un proceso real. Hoy **no se puede afirmar cuánto tarda un deal**.
- **Acción:** bloquear el KPI de ciclo en el dashboard hasta corregir la captura en origen (validación `close_date >= created_at`); usar `is_close_before_created` como KPI de calidad.

### 4.2b ⭐ El pipeline está congelado: el 100% de las oportunidades abiertas ya venció
- **Evidencia:** las **2.221 oportunidades abiertas** (stage ≠ won/lost) tienen `close_date` anterior a hoy (2026-07-21). **Absolutamente todas** — ni una sola con fecha de cierre futura.
- **Interpretación:** el "pipeline" comercial no es un embudo activo sino un **registro histórico**: no hay oportunidades vivas proyectadas a futuro. Cualquier forecast de ventas sobre estos datos es inválido.
- **Acción:** tratar el pipeline como histórico; en producción, exigir `close_date` futura para oportunidades abiertas y alertar sobre las vencidas sin cerrar.

### 4.3 15% del esfuerzo comercial es invisible y el volumen de toques no predice nada 🎲
- **Evidencia:** 2.981 de 20.000 actividades (14,9%) son huérfanas (sin contacto ni oportunidad). Actividades por oportunidad: won 3,27 / lost 3,29 / open 3,36 — idénticas.
- **Interpretación:** ~3.000 interacciones no atribuibles, y "más actividades" no mueve la aguja.
- **Acción:** vinculación obligatoria de actividades en el CRM; medir calidad/tipo de actividad, no cantidad.

### 4.4 Ser estudiante no cambia el comportamiento de facturación 🎲
- **Evidencia:** revenue por cliente: estudiantes 3.534,79 vs externos 3.520,85 (+0,4%); mismo patrón dentro de cada segmento (retail/smb/enterprise).
- **Interpretación:** no hay diferencia que monetizar entre ambos grupos — conclusión honesta habilitada por el único puente cross-dominio confiable (`external_ref`).
- **Acción:** no invertir en propuestas diferenciadas estudiante/externo.

### 4.5 ⭐ Cold call convierte 1,7× mejor que web — y el lead score es ruido
- **Evidencia:** conversión global 10,3% (205/2.000). Por canal: cold_call 14,7% > referral 11,4% > event 10,6% > ads 9,9% > **web 8,5%** (que aporta el 40% del volumen). Score promedio: convertidos 50,8 vs no convertidos 50,0.
- **Interpretación:** el canal de mayor volumen es el que peor convierte, y el modelo de scoring no discrimina en absoluto: priorizar por canal es hoy más efectivo que priorizar por score. (n de cold_call = 204: ventaja direccional.)
- **Acción:** reasignar presupuesto hacia contacto directo o mejorar la calificación del tráfico web; reconstruir el lead scoring.

### 4.6 Inconsistencia entre módulos: 2.207 clientes facturan sin tener suscripción
- **Evidencia:** 2.224 de 10.000 clientes (22,2%) no tienen ninguna suscripción; de ellos **2.207 sí tienen facturas**. Solo 67 clientes no tienen ni suscripción ni factura.
- **Interpretación:** casi 1 de cada 4 clientes se factura sin un producto contratado en el módulo de suscripciones — los dos submódulos de billing (suscripciones ↔ facturas) no concilian a nivel de cliente.
- **Acción:** flags `has_subscription`/`has_invoice` en `dim_customer`; reconciliar el origen de las facturas sin suscripción (¿compras puntuales? ¿datos huérfanos?).

### 4.7 Cronología invertida: la mitad de los contactos se crearon antes que su cuenta 🎲
- **Evidencia:** 7.456 de 15.000 contactos (49,7%) tienen `created_at` anterior al de su propia cuenta.
- **Interpretación:** imposible en un CRM real (un contacto pertenece a una cuenta que ya debe existir). Artefacto de generación, pero muestra que las marcas de tiempo del CRM no son confiables para secuenciar eventos.
- **Acción:** flag `is_contact_before_account`; no usar timestamps del CRM para análisis de cronología sin depurar.

---

## Anexo — hallazgos de calidad de datos (verificados)

Estos no son insights de negocio *per se*, pero cuantifican la magnitud de la ruptura semántica del dataset y sostienen la tesis "flaggear en vez de borrar". Todos verificados contra la base:

| Hallazgo | Magnitud |
|---|---|
| Facturas cuyo `total` de cabecera ≠ suma de líneas | **47.497 de 47.498** con items (~100%) |
| Relaciones `opportunity_contacts` con contacto de otra cuenta | **5.995 de 6.000** (99,9%) — la tabla es inutilizable para atribución |
| Actividades comerciales huérfanas (sin contacto ni oportunidad) | **2.981 de 20.000** (14,9%) |
| Cursos con profesor de otro departamento | **264 de 300** (88%) |
| Inscripciones (supervivientes) con `enrolled_at` fuera del semestre | **22.708 de 24.977** (90,9%) |
| Estudiantes con < 15 años al matricularse | **636** (edad mínima 10,2) |
| Oportunidades con `close_date` anterior a `created_at` | **1.029 de 3.000** (34,3%) |

**Lectura para la presentación:** cada fila es una regla de validación que hoy el pipeline aplica *a posteriori* (flag) y que en producción debería impedirse *a priori* (validación en origen). El valor del proyecto no fue "limpiar" estos datos sino **hacerlos auditables sin perder la evidencia**.

---

## Cómo leer estos insights en la presentación

1. **Los ⭐ son los titulares** (MRR inflado, actas sin notas, cold call): concretos, cuantificados y con acción clara.
2. **Los 🎲 se presentan con la honestidad como fortaleza**: "el pipeline detectó que este dato no discrimina / está roto — en producción esto sería una alerta de calidad automática". Eso demuestra criterio, que es lo que la rúbrica pondera.
3. **La medida de revenue es un tema en sí mismo** (ver 1.0): abrir la sección de revenue explicando que hay tres cifras que no concilian (cabecera ≈ pagos ≈ 6,8M, items 34,9M) desactiva de entrada cualquier objeción sobre "por qué tus números no cuadran con `invoices.total`" — y convierte una debilidad del dato en una demostración de criterio.
4. Todo número de este documento fue verificado tres veces (minería + re-ejecución independiente + QA contra CSV crudos); las queries viven en `notebooks/02_pipeline_y_kpis.ipynb`, reproducibles.
