-- ============================================
-- Inicialización de schemas en PostgreSQL
-- Se ejecuta automáticamente solo la primera vez
-- que se crea el volumen de datos.
-- ============================================

-- Capa Bronze: datos crudos tal cual vienen del CSV,
-- con metadatos de ingesta (fecha, archivo de origen).
CREATE SCHEMA IF NOT EXISTS bronze;

-- Capa Silver: datos limpios, tipados, estandarizados
-- y deduplicados. Reglas de calidad aplicadas.
CREATE SCHEMA IF NOT EXISTS silver;

-- Capa Gold: modelo dimensional / analítico orientado
-- al negocio (hechos, dimensiones, tablas agregadas).
CREATE SCHEMA IF NOT EXISTS gold;

-- Staging: tablas temporales de trabajo usadas durante
-- las transformaciones entre capas.
CREATE SCHEMA IF NOT EXISTS staging;

-- Confirmar creación
DO $$
BEGIN
    RAISE NOTICE '✅ Schemas creados: bronze, silver, gold, staging';
END
$$;
