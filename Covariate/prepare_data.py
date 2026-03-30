import os
from google.cloud import bigquery

os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'
def create_training_base_table():
    """
    Extracts plot-level longitudinal data from FIA ENTIRE_PLOT and ENTIRE_TREE datasets.
    Uploads the joined dataframe as a new table `fia_matrix_training_base` in BigQuery.
    Converts measurements to MATRIX-compatible metric units (cm, hectares).
    """
    
    # Initialize the BigQuery client for the 'cameltrain' project
    client = bigquery.Client(project="cameltrain")
    
    # We join ENTIRE_PLOT and ENTIRE_TREE to get longitudinal data
    # - REMPER gives us the time elapsed (dY)
    # - DIA and PREVDIA give us tree growth (in inches, multiplied by 2.54 for cm)
    # - TPA_UNADJ gives us Trees Per Acre (multiplied by 2.471 for Trees Per Hectare - TPH)
    query = """
    CREATE OR REPLACE TABLE `cameltrain.Forest_MATRIX.fia_matrix_training_base` AS
    SELECT 
        -- Control Number represents a unique temporal visit
        p.CN AS PlotID,
        
        -- Permanent plot identification (avoids USFS LAT/LON fuzzing and swapping overlaps)
        p.STATECD AS STATECD,
        p.UNITCD AS UNITCD,
        p.COUNTYCD AS COUNTYCD,
        p.PLOT AS PLOT,
        
        p.LAT AS LAT,
        p.LON AS LON,
        p.MEASYEAR AS YR,
        p.REMPER AS dY,
        t.PREVDIA * 2.54 AS PrevDBH,
        t.DIA * 2.54 AS DBH,
        t.STATUSCD AS Status,
        t.TPA_UNADJ * 2.47105 AS TPH,
        t.CN AS TreeID
    FROM `cameltrain.fia.ENTIRE_PLOT` p
    INNER JOIN `cameltrain.fia.ENTIRE_TREE` t
        ON p.CN = t.PLT_CN
    WHERE p.REMPER IS NOT NULL 
      AND (t.DIA IS NOT NULL OR t.PREVDIA IS NOT NULL)
    """
    
    print("Executing query to create 'cameltrain.Forest_MATRIX.fia_matrix_training_base'...")
    
    try:
        query_job = client.query(query)
        # Wait for the job to complete
        query_job.result()
        print("Success! The training table has been provisioned.")
    except Exception as e:
        print(f"Failed to execute BigQuery table creation: {e}")

if __name__ == "__main__":
    create_training_base_table()
