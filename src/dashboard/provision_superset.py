"""Aprovisiona el dashboard de Superset desde cero, de forma reproducible.

Crea (o reutiliza si ya existen — es idempotente):
  1. La conexión a la base de datos hacia la capa Gold.
  2. Un dataset por cada vista KPI de `gold`.
  3. Nueve gráficos de negocio, organizados en cuatro secciones temáticas.
  4. El dashboard "KPIs — CRM · Billing · Universidad" con su layout.

Sin este script el dashboard vive solo dentro del volumen del contenedor y se
pierde al recrearlo: esto lo hace parte del repositorio y del arranque desde cero.

Uso (desde un contenedor de la misma red, p. ej. jupyter):
    docker exec bootcamp-jupyter python /home/jovyan/src/dashboard/provision_superset.py

Variables de entorno (con defaults):
    SUPERSET_URL         (http://superset:8088)
    SUPERSET_ADMIN_USER  (admin)
    SUPERSET_ADMIN_PASSWORD (admin)
    POSTGRES_USER/PASSWORD/HOST/PORT/DB  (para la cadena de conexión a Gold)
"""

from __future__ import annotations

import json
import os
import sys

import requests

SUPERSET_URL = os.environ.get("SUPERSET_URL", "http://superset:8088").rstrip("/")
ADMIN_USER = os.environ.get("SUPERSET_ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("SUPERSET_ADMIN_PASSWORD", "admin")

PG_USER = os.environ.get("POSTGRES_USER", "bootcamp")
PG_PASSWORD = os.environ.get("POSTGRES_PASSWORD", "bootcamp2024")
PG_HOST = os.environ.get("POSTGRES_HOST", "postgres")
PG_PORT = os.environ.get("POSTGRES_PORT", "5432")
PG_DB = os.environ.get("POSTGRES_DB", "datawarehouse")

DATABASE_NAME = "DataWarehouse (Gold)"
DASHBOARD_TITLE = "KPIs — CRM · Billing · Universidad"
SQLALCHEMY_URI = (
    f"postgresql+psycopg2://{PG_USER}:{PG_PASSWORD}@{PG_HOST}:{PG_PORT}/{PG_DB}"
)

# Datasets a materializar (todos vistas del schema gold).
KPI_VIEWS = [
    "kpi_revenue_monthly",
    "kpi_collection_by_currency",
    "kpi_academic_by_department",
    "kpi_subscription_status",
    "kpi_sales_pipeline",
    "kpi_lead_funnel",
    "kpi_student_vs_external",
    "kpi_mrr_breakdown",
    "kpi_lead_by_source",
    "kpi_headline",
]


def _metric(column, label, aggregate="SUM"):
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": column},
        "aggregate": aggregate,
        "label": label,
    }


def _big_number(ds_id, column, subheader, fmt):
    return {
        "dataset": ds_id, "viz_type": "big_number_total",
        "params": {
            "metric": _metric(column, column, "MAX"),
            "subheader": subheader, "y_axis_format": fmt,
            "header_font_size": 0.4, "subheader_font_size": 0.15,
        },
    }


def big_number_specs(ds):
    """Cuatro 'big numbers' con los insights titulares, sobre gold.kpi_headline."""
    h = ds["kpi_headline"]
    return {
        "bn_mrr": {"name": "MRR real vigente", **_big_number(
            h, "mrr_real", "MRR real · nominal 532K (63% ya venció)", "$,.0f")},
        "bn_sin_cobrar": {"name": "% facturado sin cobrar", **_big_number(
            h, "pct_sin_cobrar", "% de facturas sin cobrar · ~900 días de mora", ".1f")},
        "bn_winrate": {"name": "Win rate comercial", **_big_number(
            h, "win_rate_pct", "% de deals ganados sobre cerrados", ".1f")},
        "bn_lead_conv": {"name": "Conversión de leads", **_big_number(
            h, "lead_conversion_pct", "% conversión · cold call 14,7% vs web 8,5%", ".1f")},
    }


def chart_specs(ds):
    """Nueve gráficos. Las medidas ya-agregadas por fila (pct) usan MAX
    (una fila por categoría), no SUM, para no sumar porcentajes."""
    return {
        # -------- Revenue y cobranza --------
        "revenue_mensual": {
            "name": "Revenue mensual por moneda (medida: items)",
            "dataset": ds["kpi_revenue_monthly"], "viz_type": "echarts_timeseries_bar",
            "params": {
                "x_axis": "month", "time_grain_sqla": "P1M",
                "metrics": [_metric("revenue", "Revenue")],
                "groupby": ["currency"], "row_limit": 10000,
                "color_scheme": "supersetColors",
            },
        },
        "cobranza_moneda": {
            "name": "Cobranza: % de facturas pagadas por moneda",
            "dataset": ds["kpi_collection_by_currency"], "viz_type": "echarts_timeseries_bar",
            "params": {
                "x_axis": "currency",
                "metrics": [_metric("paid_pct", "% pagadas", "MAX")],
                "row_limit": 100, "color_scheme": "supersetColors",
            },
        },
        # -------- Suscripciones (MRR) --------
        "mrr_breakdown": {
            "name": "MRR real vs. en riesgo (63% del MRR activo ya venció)",
            "dataset": ds["kpi_mrr_breakdown"], "viz_type": "echarts_timeseries_bar",
            "params": {
                "x_axis": "segmento",
                "metrics": [_metric("mrr", "MRR", "MAX")],
                "row_limit": 100, "color_scheme": "supersetColors",
            },
        },
        "subs_estado": {
            "name": "Suscripciones por estado",
            "dataset": ds["kpi_subscription_status"], "viz_type": "pie",
            "params": {
                "metric": _metric("subscriptions", "Suscripciones", "MAX"),
                "groupby": ["status"], "row_limit": 100,
                "color_scheme": "supersetColors",
            },
        },
        # -------- Académico --------
        "aprobacion_depto": {
            "name": "Tasa de aprobación por departamento (%)",
            "dataset": ds["kpi_academic_by_department"], "viz_type": "echarts_timeseries_bar",
            "params": {
                "x_axis": "department",
                "metrics": [_metric("pass_rate_pct", "% aprobación", "MAX")],
                "row_limit": 100, "color_scheme": "supersetColors",
            },
        },
        "academico_tabla": {
            "name": "Rendimiento académico por departamento",
            "dataset": ds["kpi_academic_by_department"], "viz_type": "table",
            "params": {
                "query_mode": "raw",
                "all_columns": ["department", "enrollments", "with_grades",
                                "avg_final_score", "pass_rate_pct"],
                "order_by_cols": [], "row_limit": 100,
            },
        },
        # -------- CRM y cross-dominio --------
        "pipeline_etapa": {
            "name": "Pipeline comercial por etapa (monto)",
            "dataset": ds["kpi_sales_pipeline"], "viz_type": "echarts_timeseries_bar",
            "params": {
                "x_axis": "stage",
                "metrics": [_metric("total_amount", "Monto total", "MAX")],
                "row_limit": 100, "color_scheme": "supersetColors",
            },
        },
        "leads_canal": {
            "name": "Conversión de leads por canal (cold call gana)",
            "dataset": ds["kpi_lead_by_source"], "viz_type": "echarts_timeseries_bar",
            "params": {
                "x_axis": "source",
                "metrics": [_metric("conversion_pct", "% conversión", "MAX")],
                "row_limit": 100, "color_scheme": "supersetColors",
            },
        },
        "estudiante_externo": {
            "name": "Facturación: estudiantes vs. externos",
            "dataset": ds["kpi_student_vs_external"], "viz_type": "table",
            "params": {
                "query_mode": "raw",
                "all_columns": ["customer_type", "customers", "invoices",
                                "invoices_per_customer", "revenue_per_customer"],
                "order_by_cols": [], "row_limit": 100,
            },
        },
    }


# Estructura del dashboard: (título de sección, [claves de gráficos]).
SECTIONS = [
    ("Revenue y cobranza", ["revenue_mensual", "cobranza_moneda"]),
    ("Suscripciones — MRR", ["mrr_breakdown", "subs_estado"]),
    ("Rendimiento académico", ["aprobacion_depto", "academico_tabla"]),
    ("CRM y visión cross-dominio", ["pipeline_etapa", "leads_canal", "estudiante_externo"]),
]

INTRO_MD = (
    "## KPIs — CRM · Billing · Universidad\n"
    "Tablero sobre la capa **Gold** del pipeline medallion. "
    "**Nota de medida:** el *revenue* usa la suma de items (`Σ line_total`); "
    "el header (`invoices.total`) y los pagos suman ~1/5 — ver `docs/insights.md`."
)

INSIGHTS_MD = (
    "### Hallazgos accionables\n"
    "- **MRR inflado 2,7×:** el 63% de las suscripciones \"activas\" ya venció → MRR real **194.674**, no 532.490.\n"
    "- **30% de lo facturado sin cobrar** con ~900 días de mora: no hay proceso de cobranza ni castigo.\n"
    "- **Revenue sin fuente única:** cabecera 6,79M ≈ pagos 6,49M, pero items 34,93M (**5,14×**).\n"
    "- **Cold call convierte 1,7× mejor que web** (14,7% vs 8,5%); el lead score no discrimina.\n"
    "- **Pirámide invertida:** el tier *basic* aporta el 43% del revenue; *enterprise* solo el 9%.\n"
    "- **Calidad:** 1.303 actas \"aprobadas\" sin nota; 100% de las oportunidades abiertas ya vencidas."
)


class Superset:
    def __init__(self):
        self.s = requests.Session()

    def login(self):
        r = self.s.post(f"{SUPERSET_URL}/api/v1/security/login", json={
            "username": ADMIN_USER, "password": ADMIN_PASSWORD,
            "provider": "db", "refresh": True,
        })
        r.raise_for_status()
        self.s.headers["Authorization"] = f"Bearer {r.json()['access_token']}"
        self.s.headers["X-CSRFToken"] = self.s.get(
            f"{SUPERSET_URL}/api/v1/security/csrf_token/").json()["result"]
        self.s.headers["Referer"] = SUPERSET_URL

    def _find(self, resource, col, value):
        q = json.dumps({"filters": [{"col": col, "opr": "eq", "value": value}]})
        r = self.s.get(f"{SUPERSET_URL}/api/v1/{resource}/", params={"q": q})
        r.raise_for_status()
        results = r.json().get("result", [])
        return results[0]["id"] if results else None

    def find_or_create_database(self):
        existing = self._find("database", "database_name", DATABASE_NAME)
        if existing:
            print(f"database  reutilizada  id={existing}")
            return existing
        r = self.s.post(f"{SUPERSET_URL}/api/v1/database/", json={
            "database_name": DATABASE_NAME, "sqlalchemy_uri": SQLALCHEMY_URI,
            "expose_in_sqllab": True,
        })
        r.raise_for_status()
        db_id = r.json()["id"]
        print(f"database  creada       id={db_id}")
        return db_id

    def find_or_create_dataset(self, db_id, table):
        existing = self._find("dataset", "table_name", table)
        if existing:
            return existing
        r = self.s.post(f"{SUPERSET_URL}/api/v1/dataset/", json={
            "database": db_id, "schema": "gold", "table_name": table,
        })
        r.raise_for_status()
        return r.json()["id"]

    def find_or_create_chart(self, key, spec):
        existing = self._find("chart", "slice_name", spec["name"])
        params = {"datasource": f"{spec['dataset']}__table",
                  "viz_type": spec["viz_type"], **spec["params"]}
        payload = {
            "slice_name": spec["name"], "viz_type": spec["viz_type"],
            "datasource_id": spec["dataset"], "datasource_type": "table",
            "params": json.dumps(params),
        }
        if existing:
            self.s.put(f"{SUPERSET_URL}/api/v1/chart/{existing}", json=payload).raise_for_status()
            print(f"chart     actualizado  '{spec['name']}'")
            return existing
        r = self.s.post(f"{SUPERSET_URL}/api/v1/chart/", json=payload)
        r.raise_for_status()
        print(f"chart     creado       '{spec['name']}'")
        return r.json()["id"]

    def upsert_dashboard(self, chart_ids, position_json):
        existing = self._find("dashboard", "dashboard_title", DASHBOARD_TITLE)
        payload = {
            "dashboard_title": DASHBOARD_TITLE, "published": True,
            "position_json": json.dumps(position_json),
        }
        if existing:
            self.s.put(f"{SUPERSET_URL}/api/v1/dashboard/{existing}", json=payload).raise_for_status()
            dash_id = existing
            print(f"dashboard actualizado  id={dash_id}")
        else:
            r = self.s.post(f"{SUPERSET_URL}/api/v1/dashboard/", json=payload)
            r.raise_for_status()
            dash_id = r.json()["id"]
            print(f"dashboard creado       id={dash_id}")
        for cid in chart_ids:
            self.s.put(f"{SUPERSET_URL}/api/v1/chart/{cid}", json={"dashboards": [dash_id]})
        return dash_id


def build_position(charts, big_numbers, specs, bn_specs):
    """Layout: intro + sección de Insights (big numbers + callout) + secciones KPI."""
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"], "children": []},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID", "meta": {"text": DASHBOARD_TITLE}},
    }
    grid = pos["GRID_ID"]["children"]

    def add_markdown(node_id, code, height):
        pos[node_id] = {
            "type": "MARKDOWN", "id": node_id, "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"code": code, "width": 12, "height": height},
        }
        grid.append(node_id)

    def add_header(node_id, text):
        pos[node_id] = {
            "type": "HEADER", "id": node_id, "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"text": text, "headerSize": "MEDIUM_HEADER",
                     "background": "BACKGROUND_TRANSPARENT"},
        }
        grid.append(node_id)

    # Intro
    add_markdown("MD-intro", INTRO_MD, 22)

    # ---- Sección de Insights: 4 big numbers + callout de texto ----
    add_header("HEAD-insights", "Insights clave")
    row_id = "ROW-bignum"
    children = []
    for k in ["bn_mrr", "bn_sin_cobrar", "bn_winrate", "bn_lead_conv"]:
        cid = big_numbers[k]
        node = f"CHART-{cid}"
        children.append(node)
        pos[node] = {
            "type": "CHART", "id": node, "children": [],
            "parents": ["ROOT_ID", "GRID_ID", row_id],
            "meta": {"chartId": cid, "width": 3, "height": 40, "sliceName": bn_specs[k]["name"]},
        }
    pos[row_id] = {
        "type": "ROW", "id": row_id, "children": children,
        "parents": ["ROOT_ID", "GRID_ID"],
        "meta": {"background": "BACKGROUND_TRANSPARENT"},
    }
    grid.append(row_id)
    add_markdown("MD-insights", INSIGHTS_MD, 34)

    # ---- Secciones de KPIs ----
    for si, (title, keys) in enumerate(SECTIONS):
        head_id = f"HEAD-{si}"
        pos[head_id] = {
            "type": "HEADER", "id": head_id, "children": [],
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"text": title, "headerSize": "MEDIUM_HEADER",
                     "background": "BACKGROUND_TRANSPARENT"},
        }
        grid.append(head_id)

        # gráficos de la sección en filas de a 2
        for ri in range(0, len(keys), 2):
            row_keys = keys[ri:ri + 2]
            row_id = f"ROW-{si}-{ri}"
            width = 12 // len(row_keys)
            children = []
            for k in row_keys:
                cid = charts[k]
                node = f"CHART-{cid}"
                children.append(node)
                pos[node] = {
                    "type": "CHART", "id": node, "children": [],
                    "parents": ["ROOT_ID", "GRID_ID", row_id],
                    "meta": {"chartId": cid, "width": width, "height": 50,
                             "sliceName": specs[k]["name"]},
                }
            pos[row_id] = {
                "type": "ROW", "id": row_id, "children": children,
                "parents": ["ROOT_ID", "GRID_ID"],
                "meta": {"background": "BACKGROUND_TRANSPARENT"},
            }
            grid.append(row_id)
    return pos


def main():
    api = Superset()
    api.login()

    db_id = api.find_or_create_database()
    ds = {v: api.find_or_create_dataset(db_id, v) for v in KPI_VIEWS}
    print(f"datasets  {len(ds)} listos")

    specs = chart_specs(ds)
    charts = {key: api.find_or_create_chart(key, spec) for key, spec in specs.items()}

    bn_specs = big_number_specs(ds)
    big_numbers = {key: api.find_or_create_chart(key, spec) for key, spec in bn_specs.items()}

    position = build_position(charts, big_numbers, specs, bn_specs)
    all_ids = list(charts.values()) + list(big_numbers.values())
    dash_id = api.upsert_dashboard(all_ids, position)

    print(f"\nDashboard listo: {SUPERSET_URL}/superset/dashboard/{dash_id}/")
    print(f"({len(ds)} datasets, {len(charts)} gráficos + {len(big_numbers)} big numbers, "
          f"{len(SECTIONS) + 1} secciones)")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as exc:
        print(f"ERROR HTTP: {exc}\n{exc.response.text[:400]}", file=sys.stderr)
        sys.exit(1)
