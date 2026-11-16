FROM apache/airflow:3.0.3-python3.12

# dbt (SQL transformation tool) + its DuckDB adapter, pinned to the same version
# warehouse/pyproject.toml uses -- the dbt_run/dbt_test tasks shell out to this,
# not to warehouse/'s own uv-managed .venv (which is built for the host, not
# this container's architecture).
RUN pip install --no-cache-dir dbt-duckdb==1.11.1
