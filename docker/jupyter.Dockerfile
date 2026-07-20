# ============================================
# Dockerfile para Jupyter Notebook
# Basado en jupyter/scipy-notebook
# Agrega las dependencias de Python del proyecto
# ============================================
FROM jupyter/scipy-notebook:latest

USER ${NB_UID}

# Copiar e instalar dependencias
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
