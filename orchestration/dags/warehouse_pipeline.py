"""Rebuild warehouse/'s silver+gold layer from whatever's currently in bronze
Parquet + store_db's Postgres.

Manually triggered only (schedule=None) -- store_db is a static, already fully
generated year, so there's no new data arriving on a timer for this DAG
(Directed Acyclic Graph, Airflow's term for an ordered set of tasks) to react
to. The point is learning Airflow's mechanics against a job that's honestly
repeatable, not pretending there's live data that isn't there.
"""

from datetime import datetime

from airflow import DAG
from airflow.providers.standard.operators.bash import BashOperator

WAREHOUSE_DIR = "/opt/airflow/project/warehouse"

# store_db's Postgres isn't on this Compose stack's network -- reached via
# Docker Desktop's host.docker.internal, at the same port the host itself uses
# (see store_db/docker-compose.yml's "5438:5432").
ENV = {
    "POSTGRES_HOST": "host.docker.internal",
    "POSTGRES_PORT": "5438",
    "POSTGRES_DB": "store_db",
    "POSTGRES_USER": "store_admin",
    # Set via Admin -> Variables in the Airflow UI, not hardcoded here -- a
    # real deployment would use a Connection + secrets backend instead.
    "POSTGRES_PASSWORD": "{{ var.value.store_db_postgres_password }}",
}

with DAG(
    dag_id="warehouse_pipeline",
    description="Rebuild warehouse/ silver+gold from current bronze Parquet + store_db",
    schedule=None,
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["warehouse", "dbt"],
) as dag:
    dbt_run = BashOperator(
        task_id="dbt_run",
        bash_command=f"cd {WAREHOUSE_DIR} && dbt run --profiles-dir .",
        env=ENV,
    )
    dbt_test = BashOperator(
        task_id="dbt_test",
        bash_command=f"cd {WAREHOUSE_DIR} && dbt test --profiles-dir .",
        env=ENV,
    )
    dbt_run >> dbt_test
