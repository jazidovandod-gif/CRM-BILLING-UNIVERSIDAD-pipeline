# ============================================
# Dockerfile para Apache Airflow
# Basado en la imagen oficial de Airflow 2.8.1
# Agrega las dependencias de Python del proyecto
# ============================================
FROM apache/airflow:2.8.1-python3.11

USER airflow

# Copiar e instalar dependencias, respetando el constraints file oficial
# de Airflow 2.8.1 para no romper las versiones que Airflow ya requiere
# (p.ej. SQLAlchemy <2.0)
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-2.8.1/constraints-3.11.txt" \
    -r /tmp/requirements.txt
