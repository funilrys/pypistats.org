"""Get the download stats for a specific day."""
import datetime
import json
import time
import os

from google.auth.crypt._python_rsa import RSASigner
from google.cloud import bigquery
from google.oauth2.service_account import Credentials
import pandas as pd
import psycopg2
from psycopg2.extras import execute_values


# For local use.
def load_env_vars(env="dev"):
    """Load environment variables."""
    local_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "secret",
        f"env_vars_{env}.json")
    for key, value in json.load(open(local_path, 'r')).items():
        os.environ[key] = value


# Mirrors to disregard when considering downloads
MIRRORS = ("bandersnatch", "z3c.pypimirror", "Artifactory", "devpi")

# PyPI systems
SYSTEMS = ("Windows", "Linux", "Darwin")

# BigQuery definitions
DATASET_ID = "pypistats"
TABLE_ID = "pypistats"
SCHEMA = [
    bigquery.SchemaField("package", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("category_label", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("category", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("downloads", "INTEGER", mode="NULLABLE"),
]

# postgresql tables to update for __all__
PSQL_TABLES = ["overall", "python_major", "python_minor", "system"]

# Number of days to retain records
MAX_RECORD_AGE = 45


def get_google_credentials():
    """Obtain the Google credentials object explicitly."""
    private_key = os.environ["GOOGLE_PRIVATE_KEY"]
    private_key_id = os.environ["GOOGLE_PRIVATE_KEY_ID"]
    signer = RSASigner.from_string(key=private_key, key_id=private_key_id)

    project_id = os.environ["GOOGLE_PROJECT_ID"]
    service_account_email = os.environ["GOOGLE_CLIENT_EMAIL"]
    scopes = (
        'https://www.googleapis.com/auth/bigquery',
        'https://www.googleapis.com/auth/cloud-platform'
    )
    token_uri = os.environ["GOOGLE_TOKEN_URI"]
    credentials = Credentials(
        signer=signer,
        service_account_email=service_account_email,
        token_uri=token_uri,
        scopes=scopes,
        project_id=project_id,
    )
    return credentials


def get_daily_download_stats(event, context):
    """Get daily download stats for pypi packages from BigQuery."""
    start = time.time()
    env = event["env"]
    if os.environ.get("ENV", None) is None:
        load_env_vars(env)
    job_config = bigquery.QueryJobConfig()
    credentials = get_google_credentials()
    bq_client = bigquery.Client(
        project=os.environ["GOOGLE_PROJECT_ID"],
        credentials=credentials
    )
    date = event.get("date", None)
    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    # # Prepare a reference to the new dataset
    # dataset_ref = bq_client.dataset(DATASET_ID)
    # dataset = bigquery.Dataset(dataset_ref)
    #
    # # Create the dataset
    # try:
    #     dataset = bq_client.create_dataset(dataset)
    # except Conflict:
    #     pass
    #
    # # Prepare a reference to the table
    # table_ref = dataset_ref.table(TABLE_ID)
    # table = bigquery.Table(table_ref, schema=SCHEMA)
    #
    # # Create the table
    # try:
    #     table = bq_client.create_table(table)
    # except Conflict:
    #     pass

    # local = False
    # if env == "dev":
    #     try:
    #         print("Loading from csv...")
    #         df = pd.read_csv("ignore/sample_data.csv", index_col=0)
    #         print("Done.")
    #         # print(set(df["category_label"].values))
    #         # sys.exit()
    #         local = True
    #     except Exception:
    #         print("Loading failed.")

    # if not local:
    print("Querying BigQuery...")
    # Get and perform the query, writing to destination table
    query = get_query(date)
    print("Done.")
    # job_config.destination = table_ref
    # job_config.write_disposition = "WRITE_TRUNCATE"
    query_job = bq_client.query(query, job_config=job_config)
    iterator = query_job.result()
    rows = list(iterator)
    print(len(rows), "rows from gbq")

    data = []
    for row in rows:
        data.append((
            date,
            row['package'],
            row['category_label'],
            row['category'],
            row['downloads']
        ))

    df = pd.DataFrame(data, columns=[
        "date",
        "package",
        "category_label",
        "category",
        "downloads",
    ])

    # # For local testing
    # df.to_csv("ignore/sample_data.csv")

    results = update_db(df, env)
    print("Elapsed: " + str(time.time() - start))
    return results


def update_db(df, env="dev"):
    """Update the db with new data by table."""
    load_env_vars(env)
    connection, cursor = get_connection_cursor(env)

    df_groups = df.groupby("category_label")

    success = {}
    for category_label, df_category in df_groups:
        table = category_label
        df_category = df_category[[
            "date",
            "package",
            "category",
            "downloads",
        ]]
        success[table] = update_table(
            connection, cursor, table, df_category, date
        )
        # update_all_package_stats(cursor, table, date)

    # update_recent_stats(cursor, date)

    return success


def update_table(connection, cursor, table, df, date):
    """Update a table."""
    print(table)
    df = df.fillna("null")

    delete_query = \
        f"""DELETE FROM {table}
            WHERE date = '{date}'"""
    insert_query = \
        f"""INSERT INTO {table} (date, package, category, downloads)
            VALUES %s"""
    values = list(df.itertuples(index=False, name=None))
    try:
        print(delete_query)
        cursor.execute(delete_query)
        print(insert_query)
        execute_values(cursor, insert_query, values)
        connection.commit()
        return True
    except psycopg2.IntegrityError as e:
        connection.rollback()
        return False


def update_all_package_stats(event, context):
    """Update stats for __all__ packages."""
    print("__all__")
    start = time.time()

    date = event.get("date", None)
    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    env = event["env"]
    if os.environ.get("ENV", None) is None:
        load_env_vars(env)

    connection, cursor = get_connection_cursor(env)

    success = {}
    for table in PSQL_TABLES:
        aggregate_query = \
            f"""SELECT date, '__all__' AS package, category, sum(downloads) AS downloads
                FROM {table} where date = '{date}' GROUP BY date, category"""
        cursor.execute(aggregate_query, (table,))
        values = cursor.fetchall()

        delete_query = \
            f"""DELETE FROM {table}
                WHERE date = '{date}' and package = '__all__'"""
        insert_query = \
            f"""INSERT INTO {table} (date, package, category, downloads)
                VALUES %s"""
        try:
            print(delete_query)
            cursor.execute(delete_query)
            print(insert_query)
            execute_values(cursor, insert_query, values)
            connection.commit()
            success[table] = True
        except psycopg2.IntegrityError as e:
            connection.rollback()
            success[table] = False

    print("Elapsed: " + str(time.time() - start))
    return success


def update_recent_stats(event, context):
    """Update daily, weekly, monthly stats for all packages."""
    print("recent")
    start = time.time()

    date = event.get("date", None)
    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    env = event["env"]
    if os.environ.get("ENV", None) is None:
        load_env_vars(env)

    connection, cursor = get_connection_cursor(env)

    downloads_table = "overall"
    recent_table = "recent"

    date = datetime.datetime.strptime(date, "%Y-%m-%d").date()
    date_week = date - datetime.timedelta(days=7)
    date_month = date - datetime.timedelta(days=30)

    where = {
        "day": f"date = '{str(date)}'",
        "week": f"date > '{str(date_week)}'",
        "month": f"date > '{str(date_month)}'",
    }

    success = {}
    for period, clause in where.items():
        select_query = \
            f"""SELECT package, '{period}' as category, sum(downloads) AS downloads
                FROM {downloads_table}
                WHERE category = 'without_mirrors' and {clause}
                GROUP BY package"""
        cursor.execute(select_query)
        values = cursor.fetchall()

        delete_query = \
            f"""DELETE FROM {recent_table}
                WHERE category = '{period}'"""
        insert_query = \
            f"""INSERT INTO {recent_table}
               (package, category, downloads) VALUES %s"""
        try:
            print(delete_query)
            cursor.execute(delete_query)
            print(insert_query)
            execute_values(cursor, insert_query, values)
            connection.commit()
            success[period] = True
        except psycopg2.IntegrityError as e:
            connection.rollback()
            success[period] = False

    print("Elapsed: " + str(time.time() - start))
    return success


def get_connection_cursor(env):
    """Get a db connection cursor."""
    connection = psycopg2.connect(
        dbname=os.environ["POSTGRESQL_DBNAME"],
        user=os.environ["POSTGRESQL_USERNAME"],
        password=os.environ["POSTGRESQL_PASSWORD"],
        host=os.environ["POSTGRESQL_HOST"],
        port=os.environ["POSTGRESQL_PORT"],
        # sslmode='require',
    )
    cursor = connection.cursor()
    return connection, cursor


def purge_old_data(event, context):
    """Purge old data records."""
    print("Purge")
    age = MAX_RECORD_AGE
    start = time.time()

    date = event.get("date", None)
    if date is None:
        date = str(datetime.date.today() - datetime.timedelta(days=1))

    env = event["env"]
    if os.environ.get("ENV", None) is None:
        load_env_vars(env)

    connection, cursor = get_connection_cursor(env)

    date = datetime.datetime.strptime(date, '%Y-%m-%d')
    purge_date = date - datetime.timedelta(days=age)
    purge_date = purge_date.strftime('%Y-%m-%d')

    success = {}
    for table in PSQL_TABLES:
        delete_query = f"""DELETE FROM {table} where date < '{purge_date}'"""
        try:
            print(delete_query)
            cursor.execute(delete_query)
            connection.commit()
            success[table] = True
        except psycopg2.IntegrityError as e:
            connection.rollback()
            success[table] = False

    print("Elapsed: " + str(time.time() - start))
    return success


def get_query(date):
    """Get the query to execute against pypistats on bigquery."""
    return f"""
    WITH
      dls AS (
      SELECT
        country_code,
        file.project AS package,
        file.version AS package_version,
        file.type AS file_type,
        details.installer.name AS installer,
        details.python AS python_version,
        details.implementation.name AS python_implementation,
        details.distro.name AS distro,
        details.system.name AS system
      FROM
        `the-psf.pypi.downloads{date.replace("-", "")}` )
    SELECT
      package,
      'python_major' AS category_label,
      cast(SPLIT(python_version, '.')[
    OFFSET
      (0)] as string) AS category,
      COUNT(*) AS downloads
    FROM
      dls
    WHERE
      installer NOT IN {str(MIRRORS)}
    GROUP BY
      package,
      category
    UNION ALL
    SELECT
      package,
      'python_minor' AS category_label,
      cast(CONCAT(SPLIT(python_version, '.')[
      OFFSET
        (0)],'.',SPLIT(python_version, '.')[
      OFFSET
        (1)]) as string) AS category,
      COUNT(*) AS downloads
    FROM
      dls
    WHERE
      installer NOT IN {str(MIRRORS)}
    GROUP BY
      package,
      category
    UNION ALL
    SELECT
      package,
      'overall' AS category_label,
      'with_mirrors' AS category,
      COUNT(*) AS downloads
    FROM
      dls
    GROUP BY
      package,
      category
    UNION ALL
    SELECT
      package,
      'overall' AS category_label,
      'without_mirrors' AS category,
      COUNT(*) AS downloads
    FROM
      dls
    WHERE
      installer NOT IN {str(MIRRORS)}
    GROUP BY
      package,
      category
    UNION ALL
    SELECT
      package,
      'system' AS category_label,
      CASE
        WHEN system NOT IN {str(SYSTEMS)} THEN 'other'
        ELSE system
      END AS category,
      COUNT(*) AS downloads
    FROM
      dls
    WHERE
      installer NOT IN {str(MIRRORS)}
    GROUP BY
      package,
      category
    """


if __name__ == "__main__":
    date = "2018-04-17"
    env = "prod"
    event = {
        "date": date,
        "env": env,
    }
    context = None
    print(date, env)
    print(get_daily_download_stats(event, context))
    print(update_all_package_stats(event, context))
    print(update_recent_stats(event, context))
