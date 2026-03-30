import os
import argparse
from google.cloud import bigquery

# Bypass internal proxy mTLS authentication blocks
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'

def compute_splits():
    """
    Creates Train, Val, and Test tables based on a combined spatial (geographical)
    and chronological (temporal) holdout strategy using official FIA plot identifiers.
    Dynamically merges the tree-level Base table and Grid 3km covariates table
    on the fly to form the unified training datasets.
    """
    client = bigquery.Client(project="cameltrain")
    
    base_cte = """
    WITH JoinedGrid AS (
      SELECT 
          b.*, 
          g.* EXCEPT(STATECD, UNITCD, COUNTYCD, PLOT, LAT, LON)
      FROM `cameltrain.Forest_MATRIX.fia_matrix_training_base` b
      JOIN `cameltrain.Forest_MATRIX.fia_grid3km_covariates` g
        ON b.STATECD = g.STATECD 
       AND b.UNITCD = g.UNITCD 
       AND b.COUNTYCD = g.COUNTYCD 
       AND b.PLOT = g.PLOT
    ),
    SpatialPlots AS (
      SELECT STATECD, UNITCD, COUNTYCD, PLOT, YR,
             DENSE_RANK() OVER(PARTITION BY STATECD, UNITCD, COUNTYCD, PLOT ORDER BY YR DESC) as rn,
             COUNT(DISTINCT YR) OVER(PARTITION BY STATECD, UNITCD, COUNTYCD, PLOT) as total_measurements
      FROM JoinedGrid
    ),
    RankedTemporal AS (
      SELECT DISTINCT STATECD, UNITCD, COUNTYCD, PLOT, YR, rn, total_measurements 
      FROM SpatialPlots
    ),
    HashedPlots AS (
      SELECT j.*,
             MOD(ABS(FARM_FINGERPRINT(CONCAT(CAST(j.STATECD AS STRING), '_', CAST(j.UNITCD AS STRING), '_', CAST(j.COUNTYCD AS STRING), '_', CAST(j.PLOT AS STRING)))), 100) AS hash_mod,
             r.rn,
             r.total_measurements
      FROM JoinedGrid j
      JOIN RankedTemporal r 
        ON j.STATECD = r.STATECD 
       AND j.UNITCD = r.UNITCD 
       AND j.COUNTYCD = r.COUNTYCD 
       AND j.PLOT = r.PLOT 
       AND j.YR = r.YR
    )
    """

    # 1. Test set creation
    query_test = f"""
    CREATE OR REPLACE TABLE `cameltrain.Forest_MATRIX.fia_matrix_test_set` AS
    {base_cte}
    SELECT * EXCEPT(hash_mod, rn, total_measurements)
    FROM HashedPlots
    WHERE hash_mod < 20
    """
    
    # 2. Validation set creation
    query_val = f"""
    CREATE OR REPLACE TABLE `cameltrain.Forest_MATRIX.fia_matrix_val_set` AS
    {base_cte}
    SELECT * EXCEPT(hash_mod, rn, total_measurements)
    FROM HashedPlots
    WHERE hash_mod >= 20 AND rn = 1 AND total_measurements > 1
    """
    
    # 3. Train set creation
    query_train = f"""
    CREATE OR REPLACE TABLE `cameltrain.Forest_MATRIX.fia_matrix_train_set` AS
    {base_cte}
    SELECT * EXCEPT(hash_mod, rn, total_measurements)
    FROM HashedPlots
    WHERE hash_mod >= 20 AND (rn > 1 OR total_measurements = 1)
    """

    queries = [
        ("Test Set", query_test),
        ("Validation Set", query_val),
        ("Train Set", query_train)
    ]

    for name, q in queries:
        print(f"Provisioning {name} in BigQuery...")
        try:
            job = client.query(q)
            job.result()
            print(f"--> Success! {name} created.")
        except Exception as e:
            print(f"--> Failed to provision {name}: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Execute the table creation queries.")
    args = parser.parse_args()
    
    if args.execute:
        compute_splits()
    else:
        print("Run with --execute")
