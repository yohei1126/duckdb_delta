from deltalake import DeltaTable, write_deltalake
from pyspark.sql import SparkSession
from delta import *
from pyspark.sql.functions import *
import duckdb
import pandas as pd
import os
import shutil

BASE_PATH = os.path.dirname(os.path.realpath(__file__)) + "/../data/generated"
TMP_PATH = '/tmp'

# Query to deal with our currently not-implemented types
modified_lineitem_query = """
SELECT 
    l_orderkey,
    l_partkey,
    l_suppkey,
    l_linenumber,
    (l_quantity*100)::INTEGER as l_quantity,
    (l_extendedprice*100)::INTEGER as l_extendedprice,
    (l_discount*100)::INTEGER as l_discount,
    (l_tax*100)::INTEGER as l_tax,
    l_returnflag,
    l_linestatus,
    l_shipdate::VARCHAR as l_shipdate,
    l_commitdate::VARCHAR as l_commitdate,
    l_receiptdate::VARCHAR as l_receiptdate,
    l_shipinstruct,
    l_shipmode,
    l_comment
FROM
    lineitem
"""

def delete_old_files():
    if (os.path.isdir(BASE_PATH)):
        shutil.rmtree(BASE_PATH)
def generate_test_data_delta_rs(path, query, part_column=False):
    """
    generate_test_data_delta_rs generates some test data using delta-rs and duckdb

    :param path: the test data path (prefixed with BASE_PATH)
    :param query: a duckdb query that produces a table called 'test_table'
    :param part_column: Optionally the name of the column to partition by
    :return: describe what it returns
    """
    generated_path = f"{BASE_PATH}/{path}"

    if (os.path.isdir(generated_path)):
        return

    con = duckdb.connect()

    con.sql(query)

    # Write delta table data
    test_table_df = con.sql("FROM test_table;").df()
    if (part_column):
        write_deltalake(f"{generated_path}/delta_lake", test_table_df,  partition_by=[part_column])
    else:
        write_deltalake(f"{generated_path}/delta_lake", test_table_df)

    # Write DuckDB's reference data
    os.mkdir(f'{generated_path}/duckdb')
    if (part_column):
        con.sql(f"COPY test_table to '{generated_path}/duckdb' (FORMAT parquet, PARTITION_BY {part_column})")
    else:
        con.sql(f"COPY test_table to '{generated_path}/duckdb/data.parquet' (FORMAT parquet)")

def generate_test_data_pyspark(current_path, input_path, delete_predicate):
    """
    generate_test_data_pyspark generates some test data using pyspark and duckdb

    :param current_path: the test data path
    :param input_path: the path to an input parquet file
    :return: describe what it returns
    """

    if (os.path.isdir(BASE_PATH + '/' + current_path)):
        return

    ## SPARK SESSION
    builder = SparkSession.builder.appName("MyApp") \
        .config("spark.sql.extensions", "io.delta.sql.DeltaSparkSessionExtension") \
        .config("spark.sql.catalog.spark_catalog", "org.apache.spark.sql.delta.catalog.DeltaCatalog")
    spark = configure_spark_with_delta_pip(builder).getOrCreate()

    ## CONFIG
    delta_table_path = BASE_PATH + '/' + current_path + '/delta_lake'
    parquet_reference_path = BASE_PATH + '/' + current_path + '/parquet'

    ## CREATE DIRS
    os.makedirs(delta_table_path, exist_ok=True)
    os.makedirs(parquet_reference_path, exist_ok=True)

    ## DATA GENERATION
    # df = spark.read.parquet(input_path)
    # df.write.format("delta").mode("overwrite").save(delta_table_path)
    spark.sql(f"CREATE TABLE test_table USING delta LOCATION '{delta_table_path}' AS SELECT * FROM parquet.`{input_path}`")

    ## CREATE
    ## CONFIGURE USAGE OF DELETION VECTORS
    spark.sql(f"ALTER TABLE test_table SET TBLPROPERTIES ('delta.enableDeletionVectors' = true);")

    ## ADDING DELETES
    deltaTable = DeltaTable.forPath(spark, delta_table_path)
    deltaTable.delete(delete_predicate)

    ## Writing the
    df = spark.table('test_table')
    df.write.parquet(parquet_reference_path, mode='overwrite')

# TO CLEAN, uncomment
# delete_old_files()

### Simple partitioned table
query = "CREATE table test_table AS SELECT i, i%2 as part from range(0,10) tbl(i);"
generate_test_data_delta_rs("simple_partitioned", query, "part")

### Lineitem SF0.01 No partitions
query = "call dbgen(sf=0.01);"
query += "CREATE table test_table AS SELECT * as part from lineitem;"
generate_test_data_delta_rs("lineitem_sf0_01", query)

### Lineitem SF0.01 10 Partitions
query = "call dbgen(sf=0.01);"
query += "CREATE table test_table AS SELECT *, l_orderkey%10 as part from lineitem;"
generate_test_data_delta_rs("lineitem_sf0_01_10part", query, "part")

### Lineitem SF1 10 Partitions
query = "call dbgen(sf=1);"
query += "CREATE table test_table AS SELECT *, l_orderkey%10 as part from lineitem;"
generate_test_data_delta_rs("lineitem_sf1_10part", query, "part")

### Lineitem_modified SF0.01
query = "call dbgen(sf=0.01);"
query += f"CREATE table test_table AS SELECT *, l_orderkey%10 as part from ({modified_lineitem_query});"
generate_test_data_delta_rs("lineitem_modified_sf0.01", query, "part")

### Lineitem_modified SF1
query = "call dbgen(sf=1);"
query += f"CREATE table test_table AS SELECT *, l_orderkey%10 as part from ({modified_lineitem_query});"
generate_test_data_delta_rs("lineitem_modified_sf1", query, "part")

### Lineitem_modified SF10
query = "call dbgen(sf=10);"
query += f"CREATE table test_table AS SELECT *, l_orderkey%10 as part from ({modified_lineitem_query});"
generate_test_data_delta_rs("lineitem_modified_sf10", query, "part")

## Simple partitioned table with structs
query = "CREATE table test_table AS SELECT {'i':i, 'j':i+1} as value, i%2 as part from range(0,10) tbl(i);"
generate_test_data_delta_rs("simple_partitioned_with_structs", query, "part");

## Simple table with deletion vector
con = duckdb.connect()
con.query(f"COPY (SELECT i as id, ('val' || i::VARCHAR) as value  FROM range(0,1000000) tbl(i))TO '{TMP_PATH}/simple_sf1_with_dv.parquet'")
generate_test_data_pyspark('simple_sf1_with_dv', f'{TMP_PATH}/simple_sf1_with_dv.parquet', "id % 1000 = 0")

## Lineitem SF0.01 with deletion vector
con = duckdb.connect()
con.query(f"call dbgen(sf=0.01); COPY ({modified_lineitem_query}) TO '{TMP_PATH}/modified_lineitem_sf0_01.parquet'")
generate_test_data_pyspark('lineitem_sf0_01_with_dv', f'{TMP_PATH}/modified_lineitem_sf0_01.parquet', "l_shipdate = '1994-01-01'")

## Lineitem SF1 with deletion vector
con = duckdb.connect()
con.query(f"call dbgen(sf=1); COPY ({modified_lineitem_query}) TO '{TMP_PATH}/modified_lineitem_sf1.parquet'")
generate_test_data_pyspark('lineitem_sf1_with_dv', f'{TMP_PATH}/modified_lineitem_sf1.parquet', "l_shipdate = '1994-01-01'")