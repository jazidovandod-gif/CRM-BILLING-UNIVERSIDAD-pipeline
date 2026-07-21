# Capa Bronze

Estado verificado al 2026-07-21: **implementada, cargada e idempotente**.

## Objetivo

Bronze conserva los 18 CSV sin aplicar reglas de negocio. Las columnas fuente se
almacenan como `TEXT` para evitar que una conversión, deduplicación o constraint elimine
evidencia que Silver deberá evaluar posteriormente.

PostgreSQL contiene:

- 6 tablas `bronze.university_*`
- 6 tablas `bronze.billing_*`
- 6 tablas `bronze.crm_*`
- `bronze.ingestion_batches` como tabla de control

El DDL se encuentra en `sql/bronze/ddl.sql`.

## Metadatos por fila

Cada tabla fuente incorpora:

- `_bronze_id`: identificador técnico de la fila.
- `_batch_id`: lote que cargó el archivo.
- `_source_file`: ruta relativa del CSV.
- `_source_domain`: `university`, `billing` o `crm`.
- `_source_row_number`: posición de la fila dentro del archivo.
- `_row_hash`: SHA-256 de los valores fuente.
- `_ingested_at`: fecha y hora de persistencia.

Las PK y FK del sistema fuente no se imponen como constraints en Bronze. Su existencia se
audita, pero Bronze debe poder conservar también registros defectuosos.

## Control de batches e idempotencia

`bronze.ingestion_batches` registra dominio, tabla, archivo, checksum SHA-256, conteos,
estado y posible error.

La identidad de una carga es `(source_domain, source_table, source_checksum)`:

1. Si el checksum no existe, se crea un batch y se carga el archivo.
2. Si el mismo archivo ya terminó con éxito y sus conteos siguen correctos, se omite.
3. Si un batch quedó fallido o incompleto, sus filas se limpian y el mismo batch se
   reintenta.
4. Un error revierte todas las filas de ese archivo y registra el batch como `failed`.

Esto evita duplicados por reejecución sin impedir que una versión realmente nueva de un
CSV genere un batch adicional.

## Ejecución

Crear `.env` a partir del ejemplo y ajustar los valores locales:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Cargar los 18 archivos desde el contenedor Jupyter:

```powershell
docker exec bootcamp-jupyter python /home/jovyan/src/ingest/bronze_loader.py
```

También puede limitarse la carga:

```powershell
docker exec bootcamp-jupyter python /home/jovyan/src/ingest/bronze_loader.py --domain billing
docker exec bootcamp-jupyter python /home/jovyan/src/ingest/bronze_loader.py --domain crm --table activities
```

## Validación

Ejecutar:

```powershell
docker exec bootcamp-jupyter python /home/jovyan/src/validate_bronze.py
```

La validación no se limita a `COUNT(*)`. Para cada archivo comprueba:

- Batch actual en estado `success`.
- Conteo manifest = batch = tabla Bronze.
- Metadatos obligatorios completos.
- Números de fila únicos dentro del batch.
- Digest ordenado de `_row_hash` idéntico al contenido del CSV.
- Ausencia de batches fallidos.

Resultado de la ejecución del 2026-07-21:

```text
Tablas validadas: 18/18
Filas: 446,708/446,708
Batches success: 18
Batches failed: 0
Metadata NULL: 0
Contenido: 18/18 OK
```

La segunda ejecución del cargador produjo:

```text
Filas cargadas: 0
Filas omitidas por idempotencia: 446,708
```

## Archivos principales

- `sql/bronze/ddl.sql`
- `src/config.py`
- `src/ingest/bronze_loader.py`
- `src/validate_bronze.py`
- `manifest.json`

## Fuera del alcance de Bronze

Bronze no corrige fechas, no reconcilia dinero, no fusiona personas, no elimina
duplicados lógicos y no atribuye actividades CRM. Esos tratamientos se diseñarán e
implementarán en Silver con las decisiones registradas en `docs/decisiones.md`.
