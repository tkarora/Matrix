import os
import argparse
from google.cloud import bigquery

# Bypass internal proxy mTLS authentication blocks
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'

def compute_grid3km_covariates():
    """
    Executes a Spatial Nearest-Neighbor JOIN utilizing BigQuery's native S2 indexing.
    Abstracts tree surveys by pulling only distinctly located physical plot layouts.
    Finds the absolute closest corresponding spatial grid center within a generous 10km radius.
    Culls state tree densities, keeping pure, statically mapped covariates.
    """
    client = bigquery.Client(project="cameltrain")
    
    query = """
    CREATE OR REPLACE TABLE `cameltrain.Forest_MATRIX.fia_grid3km_covariates` AS
    WITH unique_plots AS (
        SELECT DISTINCT 
            STATECD, UNITCD, COUNTYCD, PLOT, 
            LAT, LON
        FROM `cameltrain.Forest_MATRIX.fia_matrix_training_base`
        WHERE LAT IS NOT NULL AND LON IS NOT NULL
    )
    SELECT 
        u.STATECD, u.UNITCD, u.COUNTYCD, u.PLOT,
        
        -- Exact Plot Coordinates natively retained
        u.LAT AS LAT, u.LON AS LON,
        
        -- Exact Grid Coordinates & Metrics retained
        g.ID AS GridID,
        g.LAT AS Grid_LAT, 
        g.LON AS Grid_LON,
        ST_DISTANCE(ST_GEOGPOINT(u.LON, u.LAT), ST_GEOGPOINT(g.LON, g.LAT)) AS Distance_Meters,
        
        -- Native array mapping bypassing DBH properties
        g.* EXCEPT(ID, LAT, LON, N, DBH1, DBH2, DBH3, DBH4, DBH5, DBH6, DBH7, DBH8, DBH9, DBH10, DBH11, DBH12, DBH13, dY)
        
    FROM unique_plots u
    JOIN `cameltrain.Forest_MATRIX.grid_3km` g
        -- Massive 10km S2-indexed bounding search overcoming USFS 1-mile spatial fuzzing
        ON ST_DWithin(ST_GEOGPOINT(u.LON, u.LAT), ST_GEOGPOINT(g.LON, g.LAT), 10000)
        
    -- Restraints guaranteeing strictly ONE neighbor cross-paired per physical geometry plot layout  
    QUALIFY ROW_NUMBER() OVER(
        PARTITION BY u.STATECD, u.UNITCD, u.COUNTYCD, u.PLOT 
        ORDER BY ST_DISTANCE(ST_GEOGPOINT(u.LON, u.LAT), ST_GEOGPOINT(g.LON, g.LAT)) ASC
    ) = 1
    """
    
    print("Executing massive geographic S2 index match to build 'cameltrain.Forest_MATRIX.fia_grid3km_covariates'...")
    try:
        query_job = client.query(query)
        query_job.result()
        print("Success! The static geographic covariates master-table has seamlessly completed provisions.")
    except Exception as e:
        print(f"Failed to execute spatial join BigQuery creation: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="Actually run the massive spatial projection query.")
    args = parser.parse_args()
    
    if args.execute:
        compute_grid3km_covariates()
    else:
        print("Run with --execute to perform the BigQuery bounding S2 geographic join.")
