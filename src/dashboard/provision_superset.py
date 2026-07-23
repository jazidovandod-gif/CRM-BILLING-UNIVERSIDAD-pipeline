"""Aprovisiona el dashboard de Superset desde cero, de forma reproducible.

Crea (o reutiliza si ya existen — es idempotente):
  1. La conexión a la base de datos hacia la capa Gold.
  2. Un dataset por cada vista KPI de `gold`.
  3. Los gráficos de negocio.
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

# Datasets a materializar (todos en el schema gold).
KPI_VIEWS = [
    "kpi_revenue_monthly",
    "kpi_collection_by_currency",
    "kpi_academic_by_department",
    "kpi_subscription_status",
    "kpi_sales_pipeline",
    "kpi_lead_funnel",
    "kpi_student_vs_external",
]


def _metric(column, label, aggregate="SUM"):
    return {
        "expressionType": "SIMPLE",
        "column": {"column_name": column},
        "aggregate": aggregate,
        "label": label,
    }


# Gráficos: (nombre, vista KPI, viz_type, params). El layout los ubica 2x2.
def chart_specs(ds):
    return [
        {
            "name": "Revenue mensual por moneda",
            "dataset": ds["kpi_revenue_monthly"],
            "viz_type": "echarts_timeseries_bar",
            "params": {
                "x_axis": "month", "time_grain_sqla": "P1M",
                "metrics": [_metric("revenue", "Revenue")],
                "groupby": ["currency"], "row_limit": 10000,
                "color_scheme": "supersetColors",
            },
        },
        {
            "name": "Suscripciones por estado",
            "dataset": ds["kpi_subscription_status"],
            "viz_type": "pie",
            "params": {
                "metric": _metric("subscriptions", "Suscripciones"),
                "groupby": ["status"], "row_limit": 100,
                "color_scheme": "supersetColors",
            },
        },
        {
            "name": "Rendimiento académico por departamento",
            "dataset": ds["kpi_academic_by_department"],
            "viz_type": "table",
            "params": {
                "query_mode": "raw",
                "all_columns": ["department", "enrollments", "with_grades",
                                "avg_final_score", "pass_rate_pct"],
                "order_by_cols": [], "row_limit": 100,
            },
        },
        {
            "name": "Pipeline comercial por etapa",
            "dataset": ds["kpi_sales_pipeline"],
            "viz_type": "echarts_timeseries_bar",
            "params": {
                "x_axis": "stage",
                "metrics": [_metric("total_amount", "Monto total")],
                "row_limit": 100, "color_scheme": "supersetColors",
            },
        },
    ]


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
        import json
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
            print(f"dataset   reutilizado  {table} id={existing}")
            return existing
        r = self.s.post(f"{SUPERSET_URL}/api/v1/dataset/", json={
            "database": db_id, "schema": "gold", "table_name": table,
        })
        r.raise_for_status()
        ds_id = r.json()["id"]
        print(f"dataset   creado       {table} id={ds_id}")
        return ds_id

    def find_or_create_chart(self, spec):
        import json
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
            print(f"chart     actualizado  '{spec['name']}' id={existing}")
            return existing
        r = self.s.post(f"{SUPERSET_URL}/api/v1/chart/", json=payload)
        r.raise_for_status()
        cid = r.json()["id"]
        print(f"chart     creado       '{spec['name']}' id={cid}")
        return cid

    def upsert_dashboard(self, chart_ids, position_json):
        import json
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
        # asegurar la asociación chart -> dashboard
        for cid in chart_ids:
            self.s.put(f"{SUPERSET_URL}/api/v1/chart/{cid}", json={"dashboards": [dash_id]})
        return dash_id


def build_position(chart_ids, names):
    """Layout 2x2: dos filas de dos gráficos (ancho 6, alto 50)."""
    pos = {
        "DASHBOARD_VERSION_KEY": "v2",
        "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
        "GRID_ID": {"type": "GRID", "id": "GRID_ID", "parents": ["ROOT_ID"], "children": []},
        "HEADER_ID": {"type": "HEADER", "id": "HEADER_ID",
                      "meta": {"text": DASHBOARD_TITLE}},
    }
    for row in range(0, len(chart_ids), 2):
        row_id = f"ROW-{row // 2}"
        pos["GRID_ID"]["children"].append(row_id)
        children = []
        for cid, name in zip(chart_ids[row:row + 2], names[row:row + 2]):
            node_id = f"CHART-{cid}"
            children.append(node_id)
            pos[node_id] = {
                "type": "CHART", "id": node_id, "children": [],
                "parents": ["ROOT_ID", "GRID_ID", row_id],
                "meta": {"chartId": cid, "width": 6, "height": 50, "sliceName": name},
            }
        pos[row_id] = {
            "type": "ROW", "id": row_id, "children": children,
            "parents": ["ROOT_ID", "GRID_ID"],
            "meta": {"background": "BACKGROUND_TRANSPARENT"},
        }
    return pos


def main():
    api = Superset()
    api.login()

    db_id = api.find_or_create_database()
    ds = {v: api.find_or_create_dataset(db_id, v) for v in KPI_VIEWS}

    specs = chart_specs(ds)
    chart_ids = [api.find_or_create_chart(spec) for spec in specs]
    names = [spec["name"] for spec in specs]

    position = build_position(chart_ids, names)
    dash_id = api.upsert_dashboard(chart_ids, position)

    print(f"\nDashboard listo: {SUPERSET_URL}/superset/dashboard/{dash_id}/")
    print(f"({len(ds)} datasets, {len(chart_ids)} gráficos)")


if __name__ == "__main__":
    try:
        main()
    except requests.HTTPError as exc:
        print(f"ERROR HTTP: {exc}\n{exc.response.text[:300]}", file=sys.stderr)
        sys.exit(1)
