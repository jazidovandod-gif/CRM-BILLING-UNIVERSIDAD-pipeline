# Proyecto de Evaluación — Ingeniería de Datos: CRM + Billing + Universidad

Guía para estudiantes: qué se entrega, qué hay que construir, con qué tecnologías y cómo se evalúa.

---

## 1. Objetivo

Se te entrega un set de datos crudos (CSV) de tres dominios de negocio distintos. Debes construir, de principio a fin, un pipeline de datos que transforme esos datos crudos en información útil para el negocio.

**Qué se observa:**

- Cómo abordas un problema de datos de extremo a extremo.
- Qué decisiones tomas en cada etapa (modelado, limpieza, particionamiento, orquestación).
- **Cómo justificas esas decisiones** — el razonamiento pesa tanto como el resultado.
- Qué criterio profesional aplicas al transformar datos crudos en información accionable.

No existe una única solución correcta. Se evalúa el criterio, la trazabilidad y la calidad de la ejecución.

---

## Estado actual del proyecto

Avance verificado al 2026-07-21:

- Infraestructura Docker operativa: PostgreSQL, Airflow y Jupyter.
- Discovery ejecutado sobre los 18 CSV y 446,708 filas.
- Auditoría reproducible de PK, FK, calidad semántica y relaciones cross-domain.
- Capa Bronze implementada en PostgreSQL: 18 tablas fuente y una tabla de control.
- Primera carga reconciliada: 446,708/446,708 filas.
- Reejecución idempotente: 0 filas duplicadas.
- Silver, Gold, DAG de Airflow y exportación Parquet todavía pendientes.

Documentación principal:

- [`docs/calidad-datos.md`](./docs/calidad-datos.md)
- [`docs/analisis-datos-completo.md`](./docs/analisis-datos-completo.md)
- [`docs/bronze.md`](./docs/bronze.md)
- [`docs/decisiones.md`](./docs/decisiones.md)

### Ejecutar Bronze

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker exec bootcamp-jupyter python /home/jovyan/src/ingest/bronze_loader.py
docker exec bootcamp-jupyter python /home/jovyan/src/validate_bronze.py
```

La misma versión de un archivo se omite mediante checksum. Una versión distinta crea un
nuevo batch sin sobrescribir la evidencia anterior.

---

## 2. Datos disponibles

Los datos simulan tres sistemas de origen distintos sobre el mismo negocio (una institución que ofrece cursos y factura suscripciones). El esquema completo de cada archivo (columnas y filas) está documentado en [`manifest.json`](./manifest.json).

### `university/`
| Archivo | Filas | Contenido |
|---|---|---|
| `semesters.csv` | 8 | Semestres académicos |
| `professors.csv` | 200 | Profesores |
| `students.csv` | 5,000 | Estudiantes |
| `courses.csv` | 300 | Cursos, vinculados a un profesor |
| `enrollments.csv` | 25,000 | Inscripciones de estudiantes a cursos por semestre |
| `grades.csv` | 60,000 | Calificaciones por inscripción |

### `billing/`
| Archivo | Filas | Contenido |
|---|---|---|
| `customers.csv` | 10,000 | Clientes |
| `products.csv` | 200 | Productos/planes facturables |
| `subscriptions.csv` | 15,000 | Suscripciones de clientes a productos |
| `invoices.csv` | 50,000 | Facturas |
| `invoice_items.csv` | 150,000 | Líneas de factura |
| `payments.csv` | 80,000 | Pagos asociados a facturas |

### `crm/`
| Archivo | Filas | Contenido |
|---|---|---|
| `accounts.csv` | 5,000 | Cuentas (empresas/organizaciones) |
| `contacts.csv` | 15,000 | Contactos, vinculados a una cuenta |
| `leads.csv` | 2,000 | Leads comerciales |
| `opportunities.csv` | 3,000 | Oportunidades de venta, vinculadas a una cuenta |
| `opportunity_contacts.csv` | 6,000 | Relación N:N entre oportunidades y contactos |
| `activities.csv` | 20,000 | Actividades (llamadas, reuniones, etc.) sobre contactos/oportunidades |

No hay un diagrama ER formal: las relaciones se infieren de las columnas `*_id` compartidas entre archivos (por ejemplo, `students.student_id` ↔ `enrollments.student_id`, `customers.customer_id` ↔ `invoices.customer_id`).

**Importante:** el campo `path` dentro de `manifest.json` apunta al directorio original del generador de datos, no a este repositorio. Usa `manifest.json` solo como referencia de esquema (columnas, cantidad de filas), no como ruta de archivo — los CSV reales están en `university/`, `billing/` y `crm/` dentro de este mismo directorio.

---

## 3. Stack tecnológico obligatorio

| Herramienta | Uso esperado |
|---|---|
| **Docker** | Levantar todo el ambiente (Postgres, Airflow, Jupyter) de forma reproducible |
| **PostgreSQL** | Motor de base de datos para las capas Bronze, Silver y Gold |
| **Apache Airflow** | Orquestación y automatización del pipeline |
| **Python** | Ingesta, transformaciones, validaciones |
| **Jupyter Notebook** | Discovery, perfilado y análisis exploratorio |
| **SQL** | Modelado y transformaciones de negocio |
| **CSV** | Formato de los datos de origen |
| **Parquet** | Formato de exportación de las capas finales |
| **Git** | Control de versiones y evidencia del proceso de trabajo |

**Visualización:** libre elección (Matplotlib, Seaborn, Plotly, Superset, Metabase, Power BI, etc.). Lo importante es que el gráfico comunique el insight, no la herramienta.

---

## 4. Fases del proyecto

Debes cumplir las siguientes etapas, en orden:

1. **Preparación del ambiente** — Docker Compose con los servicios necesarios.
2. **Configuración de herramientas** — Conexiones, variables, credenciales, dependencias.
3. **Ingesta de datos (CSV)** — Carga de los archivos fuente sin transformar.
4. **Discovery y perfilado de datos** — Entender qué hay: volúmenes, tipos, cardinalidades, distribuciones.
5. **Análisis de calidad de datos** — Nulos, duplicados, formatos inconsistentes, llaves huérfanas, outliers. Documentar hallazgos.
6. **Construcción de Bronze** — Datos crudos persistidos, con metadatos de ingesta (fecha, origen, archivo).
7. **Construcción de Silver** — Datos limpios, tipados, estandarizados y deduplicados. Reglas de calidad aplicadas y registradas.
8. **Modelado Gold** — Modelo dimensional o analítico orientado al negocio (hechos y dimensiones, o tablas agregadas).
9. **Transformaciones de negocio** — Métricas, KPIs y lógica de dominio.
10. **Automatización con Airflow** — DAG que ejecute el pipeline completo, idempotente y con dependencias explícitas.
11. **Exportación a Parquet** — Persistencia de las capas finales en formato columnar.
12. **Validación del pipeline** — Pruebas de integridad, conteos, reconciliación origen vs. destino.
13. **Notebook de análisis** — Exploración sobre la capa Gold.
14. **Generación de insights** — Hallazgos concretos y accionables para el negocio.
15. **Presentación ejecutiva** — Comunicación de resultados a una audiencia no técnica.

---

## 5. Entregables

- **Repositorio Git** — con historial de commits que refleje el proceso de trabajo.
- **Pipeline automatizado** — DAG de Airflow funcional y ejecutable.
- **Modelo Bronze, Silver y Gold** — implementado en PostgreSQL.
- **Scripts SQL y Python** — organizados y versionados.
- **Archivos Parquet** — capas exportadas.
- **Notebook de análisis** — con el razonamiento visible.
- **Presentación ejecutiva** — resultados e insights.

---

## 6. Estructura sugerida del repositorio

```
.
├── docker/                 # Dockerfile, docker-compose.yml
├── data/
│   ├── raw/                # CSV de origen
│   └── parquet/            # Exportaciones finales
├── dags/                   # DAGs de Airflow
├── sql/
│   ├── bronze/
│   ├── silver/
│   └── gold/
├── src/                    # Código Python (ingesta, utils, validaciones)
├── notebooks/              # Discovery, perfilado, análisis
├── docs/                   # Decisiones, hallazgos de calidad, presentación
└── README.md
```

---

## 7. Criterios de evaluación

| Criterio | Qué se observa |
|---|---|
| **Criterio técnico** | Coherencia del modelo, correctitud de las transformaciones |
| **Calidad de datos** | Detección y tratamiento explícito de los problemas del dataset |
| **Justificación** | Cada decisión relevante está documentada y argumentada |
| **Reproducibilidad** | El proyecto se levanta y ejecuta desde cero sin intervención manual |
| **Automatización** | Pipeline idempotente, con manejo de errores |
| **Comunicación** | Los insights son claros, relevantes y entendibles por el negocio |

---

## 8. Reglas de trabajo

- Documenta **toda decisión no obvia** en `docs/decisiones.md` (qué se decidió, por qué, qué alternativas se descartaron).
- Los problemas de calidad **no se ocultan**: se detectan, se registran y se tratan explícitamente.
- El pipeline debe poder re-ejecutarse sin duplicar datos.
- Commits pequeños y descriptivos: el historial es parte de la evaluación.
