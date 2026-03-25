from google.cloud import bigquery
import pandas as pd

from soil_covariates import fetch_ssurgo_properties, fetch_soilgrids_properties

def get_unique_training_coordinates(project_id='cameltrain', dataset='Forest_MATRIX', table='fia_matrix_training_base', limit=None):
    """
    Extracts unique LAT and LON coordinates from the BigQuery training base table.
    """
    client = bigquery.Client(project=project_id)
    
    query = f"""
        SELECT DISTINCT LAT, LON
        FROM `{project_id}.{dataset}.{table}`
        WHERE LAT IS NOT NULL AND LON IS NOT NULL
    """
    if limit is not None:
        query += f" LIMIT {limit}"
        
    print(f"Executing query on {project_id}.{dataset}.{table}...")
    df = client.query(query).to_dataframe()
    print(f"Extracted {len(df)} unique coordinate pairs.")
    return df

def get_covariates(df_coords):
    """
    Retrieves soil covariates from SSURGO and SoilGrids for a given dataframe of coordinates.
    Merges the physical (SSURGO) and chemical (SoilGrids) sub-dataframes.
    """
    df_ssurgo = fetch_ssurgo_properties(df_coords)
    df_soilgrids = fetch_soilgrids_properties(df_coords)
    
    print("Merging SSURGO and SoilGrids dataframes...")
    df_merged = pd.merge(df_ssurgo, df_soilgrids, on=['LAT', 'LON'], how='left')
    return df_merged

def upload_covariates_to_bq(df, project_id='cameltrain', dataset='Forest_MATRIX', table='fia_matrix_training_cov_soil'):
    """
    Uploads the covariates dataframe to BigQuery.
    """
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.{table}"
    
    # We use WRITE_APPEND so we can run chunks without overwriting previously processed data
    job_config = bigquery.LoadJobConfig(
        write_disposition="WRITE_APPEND",
    )
    
    print(f"Uploading {len(df)} rows to {table_id}...")
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # Wait for the job to complete
    
    print(f"Successfully uploaded {len(df)} rows to {table_id}.")
