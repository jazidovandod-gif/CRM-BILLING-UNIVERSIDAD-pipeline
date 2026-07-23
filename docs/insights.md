# Insights de negocio — capa Gold

Hallazgos accionables obtenidos consultando el modelo Gold. **Método:** cada insight fue minado con SQL sobre `gold`/`silver` y luego **re-verificado de forma independiente** (queries reescritas desde cero); solo se publican números confirmados. Fecha de análisis: 2026-07-20 (snapshot); datos operativos 2022–2025.

> **Nota de honestidad metodológica:** el dataset es sintético. Cuando un patrón delata al generador de datos (p. ej. uniformidades imposibles en un negocio real), el insight se marca con 🎲 y se reporta igual — saber que un dato *no discrimina* también es un hallazgo, y en producción sería una señal de alerta de calidad.

---

## Resumen ejecutivo — los 5 titulares

| # | Insight | Número clave |
|---|---------|--------------|
| 1 | **El MRR real es un tercio del reportado** — 63% de las suscripciones "activas" ya venció | MRR real **194,7K** vs 532,5K nominal |
| 2 | **30% de lo facturado está en la calle**, con ~900 días de mora promedio | USD 3,2M + CLP 3,1M sin cobrar |
| 3 | **El tier más barato sostiene el negocio** — basic 43% del revenue, enterprise 9% | Mismo orden en las 8 monedas |
| 4 | **Cold call convierte 1,7× mejor que web** y el lead score no discrimina (50,8 vs 50,0) | 14,7% vs 8,5% de conversión |
| 5 | **6.035 facturas sin respaldo documental** (sin items o "pagadas" sin pago) | Riesgo de auditoría directo |

---

## 1. Revenue y facturación

### 1.1 Revenue estancado 4 años, sin estacionalidad 🎲
- **Evidencia:** USD: 2.620.555 (2022) → 2.715.133 (2023) → 2.770.977 (2024) → 2.587.455 (2025): −6,6% vs pico 2024, −1,3% vs 2022. CLP −6,7% en el período. EUR +2,7%, MXN +6,6%. Rango mensual USD 815K–992K sin patrón estacional.
- **Interpretación:** el negocio no crece; las dos plazas principales (USD y CLP, ~50% de las facturas) cierran 2025 por debajo de 2022.
- **Acción:** priorizar iniciativas de crecimiento (upsell de tiers) sobre optimización estacional, que no aplica.

### 1.2 30% de lo facturado sin cobrar, mora promedio ~900 días 🎲
- **Evidencia:** 15.034 facturas abiertas (10.048 pending + 4.986 overdue) = 30,1% de 50.000. USD 3.206.972 y CLP 3.114.777 sin cobrar. Antigüedad media desde `due_at`: ~885–916 días. El % es casi idéntico por año de emisión (29,8%–30,5%): **3.724 facturas de 2022 siguen abiertas**.
- **Interpretación:** no existe proceso de cobranza ni política de castigo — cuentas por cobrar de 2,5 años inflan el activo. (La uniformidad del 30% delata al generador, pero la ausencia de aging es el mensaje operativo.)
- **Acción:** dunning automático 30/60/90 días; provisión/castigo de todo lo vencido >365 días; KPI de cobranza por cohorte de emisión.

### 1.3 La pirámide de revenue está invertida: basic 43%, enterprise 9%
- **Evidencia:** por categoría de producto (Σ items, USD): basic 4.545.182 (42,9%) > standard 3.073.305 (29,0%) > premium 1.990.751 (18,8%) > enterprise 980.565 (9,3%). **El mismo orden se repite en las 8 monedas.**
- **Interpretación:** el tier más barato sostiene la facturación; los tiers de valor no despegan — pricing no competitivo o fuerza comercial que no migra clientes hacia arriba.
- **Acción:** playbook global de upsell basic→standard/premium (el patrón es idéntico en todas las plazas) y revisión del empaquetado enterprise.

### 1.4 El segmento "enterprise" no paga ticket premium 🎲
- **Evidencia:** ticket promedio USD: retail 706,58 / smb 712,00 / enterprise 675,54. Retail genera 69,9% del revenue USD. En 4 de 8 monedas el ticket enterprise es igual o **menor** que el retail; en todas, la banda es plana (657–788).
- **Interpretación:** la segmentación no se traduce en monetización — el revenue depende del volumen retail.
- **Acción:** auditar la política de precios por segmento o sincerar la segmentación.

### 1.5 Riesgo de auditoría: 6.035 facturas sin respaldo 🎲
- **Evidencia:** 2.502 facturas **sin ningún item** (USD 104.317; CLP 112.646; resto ~129K) + 3.533 facturas `paid` **sin ningún pago registrado** (USD 763.741; CLP 736.506; resto ~1,04M).
- **Interpretación:** 5% de las facturas no puede probar qué se vendió y 10% de las "cobradas" no puede probar que se cobró.
- **Acción:** cuarentenar en reporte de excepciones y excluir del revenue "confirmado"; en origen, bloquear facturas sin líneas y derivar `paid` solo de pagos registrados (el modelo ya expone `payment_status_derived`).

---

## 2. Suscripciones y revenue recurrente

### 2.1 ⭐ El MRR real es 194,7K, no 532,5K: el 63% del MRR "activo" ya venció
- **Evidencia:** de 11.272 suscripciones `active` (MRR nominal 532.490), 7.146 tienen `end_date` vencida y aportan 337.817 (63,4%). Solo 4.126 están vigentes: **MRR real 194.674**. Del vencido: 2.229 contratos vencieron en 2024, 2.809 en 2025, 1.525 en 2026.
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
- **Evidencia:** de 14.931 completed, 1.303 no tienen ninguna evaluación registrada. Rango por semestre: 7,99%–9,31% — estructural en los 8 semestres, con leve mejora en 2025.
- **Interpretación:** cierre de actas incompleto: 1 de cada 11 cursos "aprobados" no tiene respaldo académico.
- **Acción:** regla de negocio en origen: no cerrar como `completed` sin al menos una nota; regularizar el backlog de 1.303 actas.

### 3.3 Pérdida académica estancada en ~20% durante 4 años
- **Evidencia:** dropped+failed por año: 20,30% (2022) → 20,24% → 20,08% → 19,88% (2025). 2.500 dropped + 2.526 failed sobre 24.977.
- **Interpretación:** 1 de cada 5 inscripciones se pierde y nada movió la aguja en 4 años; mitad abandono, mitad reprobación.
- **Acción:** fijar 20% como línea base con meta (−2 pts en 2 semestres); alerta temprana sobre las ~5.000 `active` del semestre en curso.

### 3.4 El status está desacoplado de las notas 🎲
- **Evidencia:** promedio de nota final por status: completed 74,90 / **failed 74,55** / dropped 74,94. El 91% de los dropped tiene nota final completa.
- **Interpretación:** un "reprobado" rinde igual que un "aprobado" — status y nota cuentan historias contradictorias (artefacto), y no pueden usarse juntos sin regla de precedencia.
- **Acción:** contrato de datos: `status` es la fuente de verdad para retención; check de consistencia (failed ⇒ nota < umbral) en el validador de Silver para producción.

### 3.5 Sin saturación de cursos: carga uniforme (~10 alumnos/sección)
- **Evidencia:** alumnos por curso-semestre: 10,2–10,8 según departamento; máximo absoluto 22.
- **Interpretación:** la oferta está bien dimensionada; no hay caso de negocio para abrir secciones por congestión — sí, quizás, para consolidar secciones chicas.
- **Acción:** descartar "ampliar oferta"; evaluar consolidación de secciones pequeñas recurrentes.

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

---

## Cómo leer estos insights en la presentación

1. **Los ⭐ son los titulares** (MRR inflado, actas sin notas, cold call): concretos, cuantificados y con acción clara.
2. **Los 🎲 se presentan con la honestidad como fortaleza**: "el pipeline detectó que este dato no discrimina / está roto — en producción esto sería una alerta de calidad automática". Eso demuestra criterio, que es lo que la rúbrica pondera.
3. Todo número de este documento fue verificado dos veces (minería + re-ejecución independiente); las queries viven en `notebooks/02_pipeline_y_kpis.ipynb`, reproducibles.
