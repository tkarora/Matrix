import os
# [BUGFIX] Prevent MutualTLSChannelError (Exit Code -11)
# Disables mTLS endpoints so BigQuery does not crash when the certificate provider fails.
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'

from google.cloud import bigquery
import pandas as pd
import sys
import google.auth
from google.auth.exceptions import DefaultCredentialsError, RefreshError
import google.auth.transport.requests

from soil_covariates import fetch_ssurgo_properties, fetch_soilgrids_properties

def ensure_gcp_auth():
    """Validates that Google Cloud ADC is authenticated and not expired."""
    try:
        credentials, project = google.auth.default()
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)
    except (DefaultCredentialsError, RefreshError):
        print("\n" + "="*80)
        print("ERROR: Google Cloud CLI is not authenticated or credentials have expired.")
        print("Please run the following command to authenticate before proceeding:")
        print("    gcloud auth application-default login")
        print("="*80 + "\n")
        sys.exit(1)
    except Exception:
        # Ignore other exceptions
        pass

def get_unique_training_coordinates(project_id='cameltrain', dataset='Forest_MATRIX', table='fia_matrix_training_base', target_table='fia_matrix_training_cov_soil', limit=None):
    ensure_gcp_auth()
    """
    Extracts unique LAT and LON coordinates from the BigQuery training base table,
    excluding those already present in the target covariates table.
    """
    client = bigquery.Client(project=project_id)
    full_target_table = f"{project_id}.{dataset}.{target_table}"
    
    try:
        client.get_table(full_target_table)
        exclude_clause = f" AND NOT EXISTS (SELECT 1 FROM `{full_target_table}` cov WHERE ROUND(cov.LAT, 5) = ROUND(base.LAT, 5) AND ROUND(cov.LON, 5) = ROUND(base.LON, 5))"
    except Exception:
        exclude_clause = ""
        
    query = f"""
        SELECT DISTINCT LAT, LON
        FROM `{project_id}.{dataset}.{table}` base
        WHERE LAT IS NOT NULL AND LON IS NOT NULL
        {exclude_clause}
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
    # [BUGFIX] Prevent EE Serialization Nulls
    # Earth Engine JSON payloads slightly shift Float64 precision, breaking pd.merge instances.
    # Rounding keys to 5 decimal places (~1 meter) safely resolves the drifting.
    df_ssurgo['merge_lat'] = df_ssurgo['LAT'].round(5)
    df_ssurgo['merge_lon'] = df_ssurgo['LON'].round(5)
    df_soilgrids['merge_lat'] = df_soilgrids['LAT'].round(5)
    df_soilgrids['merge_lon'] = df_soilgrids['LON'].round(5)
    
    # Merge and safely drop the duplicate coordinate columns
    df_merged = pd.merge(df_ssurgo, df_soilgrids.drop(columns=['LAT', 'LON']), on=['merge_lat', 'merge_lon'], how='left')
    df_merged.drop(columns=['merge_lat', 'merge_lon'], inplace=True)
    
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

def process_and_upload_in_chunks(df_coords, extractor_func=get_covariates, chunk_size=5000, target_table='fia_matrix_training_cov_soil'):
    """
    Processes the coordinate extraction and pushes to BigQuery in chunks to allow resumption.
    """
    if len(df_coords) == 0:
        print("No new coordinates to process. All caught up!")
        return

    print(f"\nStarting chunked processing and upload for {len(df_coords)} total points with chunks of size {chunk_size}...")
    for start_idx in range(0, len(df_coords), chunk_size):
        chunk = df_coords.iloc[start_idx:start_idx+chunk_size]
        print(f"\n--- Processing Chunk [{start_idx} to {start_idx+len(chunk)}] ---")
        df_merged = extractor_func(chunk)
        upload_covariates_to_bq(df_merged, table=target_table)
    print("\nAll chunks processed and uploaded successfully!")
