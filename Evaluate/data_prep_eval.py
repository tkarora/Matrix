import os
import argparse
from google.cloud import bigquery

# Ensure ADC works even if MTLS is flaky
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'

def create_eval_vectors_table():
    """
    Groups individual tree data from the BigQuery training table into 
    13 DBH class distributions for both the initial state (t) and 
    final state (t+dY). 
    """
    client = bigquery.Client(project="cameltrain")
    
    # DBH bounds
    bounds = [12.93003, 17.28223, 22.25088, 27.31658, 32.29727, 37.24331, 
              42.30573, 47.27999, 52.22731, 57.30927, 62.43174, 67.25792, 90.29815]
    
    # We dynamically generate the CASE WHEN statements for DBH classes 1 to 13 
    # for the PREV state (t) and FINAL state (t+dY)
    def make_bins(col, prefix="DBH"):
        lines = []
        lines.append(f"SUM(CASE WHEN b.{col} < {bounds[0]} AND b.Status = 1 THEN b.TPH ELSE 0 END) AS {prefix}1")
        for i in range(1, 12):
            lines.append(f"SUM(CASE WHEN b.{col} >= {bounds[i-1]} AND b.{col} < {bounds[i]} AND b.Status = 1 THEN b.TPH ELSE 0 END) AS {prefix}{i+1}")
        lines.append(f"SUM(CASE WHEN b.{col} >= {bounds[11]} AND b.Status = 1 THEN b.TPH ELSE 0 END) AS {prefix}13")
        return ",\n        ".join(lines)

    t1_bins = make_bins("PrevDBH", "DBH")
    t2_bins = make_bins("DBH", "TRUE_TPH2_")
    
    query = f"""
    CREATE OR REPLACE TABLE `cameltrain.Forest_MATRIX.fia_grid_3km_eval` AS
    WITH base_grouped AS (
        SELECT 
            b.PlotID AS ID,
            b.STATECD, b.UNITCD, b.COUNTYCD, b.PLOT,
            b.LAT,
            b.LON,
            b.YR,
            MAX(b.dY) AS dY,
            
            -- Initial State (t) 
            {t1_bins},
            
            -- Final State (t+dY) (Ground Truth)
            {t2_bins}
            
        FROM `cameltrain.Forest_MATRIX.fia_matrix_training_base` b
        GROUP BY b.PlotID, b.STATECD, b.UNITCD, b.COUNTYCD, b.PLOT, b.LAT, b.LON, b.YR
    )
    SELECT 
        bg.ID,
        bg.STATECD, 
        bg.UNITCD, 
        bg.COUNTYCD, 
        bg.PLOT,
        bg.LAT,
        bg.LON,
        bg.YR,
        bg.dY,
        
        -- Explode all 100+ Environment & Geography variables cleanly via SELECT *
        g.* EXCEPT(STATECD, UNITCD, COUNTYCD, PLOT, LAT, LON),
        
        -- Bubble up the aggregated Demographic Density arrays (t1 and t2)
        bg.DBH1, bg.DBH2, bg.DBH3, bg.DBH4, bg.DBH5, bg.DBH6, bg.DBH7, bg.DBH8, bg.DBH9, bg.DBH10, bg.DBH11, bg.DBH12, bg.DBH13,
        bg.TRUE_TPH2_1, bg.TRUE_TPH2_2, bg.TRUE_TPH2_3, bg.TRUE_TPH2_4, bg.TRUE_TPH2_5, bg.TRUE_TPH2_6, bg.TRUE_TPH2_7, bg.TRUE_TPH2_8, bg.TRUE_TPH2_9, bg.TRUE_TPH2_10, bg.TRUE_TPH2_11, bg.TRUE_TPH2_12, bg.TRUE_TPH2_13
        
    FROM base_grouped bg
    JOIN `cameltrain.Forest_MATRIX.fia_grid3km_covariates` g
      ON bg.STATECD = g.STATECD 
     AND bg.UNITCD = g.UNITCD 
     AND bg.COUNTYCD = g.COUNTYCD 
     AND bg.PLOT = g.PLOT
    WHERE (
        -- Concise trick to check if ANY of these 26 columns are NULL. In standard SQL, something + NULL = NULL.
        bg.DBH1 + bg.DBH2 + bg.DBH3 + bg.DBH4 + bg.DBH5 + bg.DBH6 + bg.DBH7 + bg.DBH8 + bg.DBH9 + bg.DBH10 + bg.DBH11 + bg.DBH12 + bg.DBH13 +
        bg.TRUE_TPH2_1 + bg.TRUE_TPH2_2 + bg.TRUE_TPH2_3 + bg.TRUE_TPH2_4 + bg.TRUE_TPH2_5 + bg.TRUE_TPH2_6 + bg.TRUE_TPH2_7 + bg.TRUE_TPH2_8 + bg.TRUE_TPH2_9 + bg.TRUE_TPH2_10 + bg.TRUE_TPH2_11 + bg.TRUE_TPH2_12 + bg.TRUE_TPH2_13
    ) IS NOT NULL
    """
    
    print("Executing query to create 'cameltrain.Forest_MATRIX.fia_grid_3km_eval'...")
    try:
        query_job = client.query(query)
        query_job.result()
        print("Success! The evaluation vector table has been provisioned.")
    except Exception as e:
        print(f"Failed to execute BigQuery table creation: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually run the query")
    args = parser.parse_args()
    
    if args.execute:
        create_eval_vectors_table()
    else:
        print("Run with --execute to build the BigQuery dimension tables.")
