import pandas as pd
import numpy as np

def chunk_coordinates_spatially(df_coords, tile_size=5.0):
    """
    Groups coordinates into spatial tiles of `tile_size` x `tile_size` degrees.
    This is necessary to avoid memory and fetch limits when querying high-resolution climate grids.
    
    Returns a list of dictionaries, each containing:
    - 'xmin', 'xmax', 'ymin', 'ymax': the bounding box for the chunk
    - 'df': the subset dataframe of coordinates falling in this chunk
    """
    print(f"Dividing {len(df_coords)} coordinates into {tile_size}° spatial tiles...")
    
    df_coords = df_coords.copy()
    df_coords['lat_tile'] = np.floor(df_coords['LAT'] / tile_size) * tile_size
    df_coords['lon_tile'] = np.floor(df_coords['LON'] / tile_size) * tile_size
    
    chunks = []
    for (lat_start, lon_start), group_df in df_coords.groupby(['lat_tile', 'lon_tile']):
        # Create a bounding box slightly padded around the true min/max to ensure interpolation works later
        xmin = np.floor(group_df['LON'].min() * 10) / 10.0 - 0.1
        xmax = np.ceil(group_df['LON'].max() * 10) / 10.0 + 0.1
        ymin = np.floor(group_df['LAT'].min() * 10) / 10.0 - 0.1
        ymax = np.ceil(group_df['LAT'].max() * 10) / 10.0 + 0.1
        
        chunks.append({
            'xmin': xmin,
            'xmax': xmax,
            'ymin': ymin,
            'ymax': ymax,
            'num_points': len(group_df),
            'df': group_df.drop(columns=['lat_tile', 'lon_tile'])
        })
        
    # Sort chunks by size for informational purposes (largest first)
    chunks = sorted(chunks, key=lambda x: x['num_points'], reverse=True)
    
    print(f"Successfully created {len(chunks)} spatial chunks.")
    return chunks

def fetch_climate_data_for_chunk(chunk, base_output_dir="/tmp/climate_data", scenarios=None):
    """
    Fetches the NetCDF grid data using `chelsa-cmip6` for a specific spatial chunk.
    Dynamically supports looping through years to satisfy the flexible duration requirement.
    
    `scenarios` format: List of dictionaries defining the model and timeframe:
    [
      {'name': 'historical', 'activity_id': 'CMIP', 'experiment_id': 'historical', 'years': range(2000, 2015)},
      {'name': 'ssp245', 'activity_id': 'ScenarioMIP', 'experiment_id': 'ssp245', 'years': range(2015, 2026)},
      {'name': 'ssp585', 'activity_id': 'ScenarioMIP', 'experiment_id': 'ssp585', 'years': range(2015, 2026)},
    ]
    """
    import os
    from chelsa_cmip6.GetClim import chelsa_cmip6
    
    # Define default scenarios if not provided, for testing
    if scenarios is None:
        scenarios = [
            {'name': 'historical', 'activity_id': 'CMIP', 'experiment_id': 'historical', 'years': [2010]},
            {'name': 'ssp245', 'activity_id': 'ScenarioMIP', 'experiment_id': 'ssp245', 'years': [2020]}
        ]
        
    os.makedirs(base_output_dir, exist_ok=True)
    
    xmin, xmax, ymin, ymax = chunk['xmin'], chunk['xmax'], chunk['ymin'], chunk['ymax']
    
    for scenario in scenarios:
        for year in scenario['years']:
            print(f"Fetching {scenario['name']} data for {year} in bounds ({xmin:.1f}, {xmax:.1f}, {ymin:.1f}, {ymax:.1f})...")
            
            try:
                # The paper example uses MPI-ESM1-2-LR
                chelsa_cmip6(
                    activity_id=scenario['activity_id'],
                    table_id='Amon',
                    experiment_id=scenario['experiment_id'],
                    institution_id='MPI-M',
                    source_id='MPI-ESM1-2-LR',
                    member_id='r1i1p1f1',
                    refps='1981-01-15',
                    refpe='2010-12-15',
                    fefps=f'{year}-01-15',
                    fefpe=f'{year}-12-15',
                    xmin=xmin,
                    xmax=xmax,
                    ymin=ymin,
                    ymax=ymax,
                    output=base_output_dir
                )
            except Exception as e:
                print(f"Error fetching for year {year}, {scenario['name']}: {e}")
                
    print(f"Saved NetCDF outputs to {base_output_dir}.")
    return base_output_dir

def extract_points_from_climate_data(df_coords, netcdf_dir):
    """
    Extracts time-series climate data for specific coordinates from downloaded NetCDF files.
    Returns a unified pandas DataFrame with the extracted data.
    """
    import xarray as xr
    import os
    import glob
    
    print(f"Extracting point data from NetCDF files in {netcdf_dir}...")
    nc_files = glob.glob(os.path.join(netcdf_dir, '*.nc'))
    if not nc_files:
        print("No NetCDF files found for extraction.")
        return pd.DataFrame()
        
    extracted_data = []
    
    for nc_file in nc_files:
        print(f"Reading {os.path.basename(nc_file)}...")
        try:
            ds = xr.open_dataset(nc_file)
            
            # Use xarray's advanced indexing to select all points at once
            target_lats = xr.DataArray(df_coords['LAT'].values, dims='points')
            target_lons = xr.DataArray(df_coords['LON'].values, dims='points')
            
            # CHELSA standardizes on 'lat' and 'lon'. We use 'nearest' for grid cell mapping
            extracted = ds.sel(lat=target_lats, lon=target_lons, method='nearest')
            
            df_points = extracted.to_dataframe().reset_index()
            
            # Attach the true queried LAT/LON from df_coords to maintain identity
            df_points['queried_LAT'] = df_coords['LAT'].values
            df_points['queried_LON'] = df_coords['LON'].values
            df_points['source_file'] = os.path.basename(nc_file)
            
            extracted_data.append(df_points)
            ds.close()
            
        except Exception as e:
            print(f"Error processing {nc_file}: {e}")
            
    if extracted_data:
        # Concatenate all dataframes
        final_df = pd.concat(extracted_data, ignore_index=True)
        print(f"Extraction complete: {len(final_df)} records created.")
        return final_df
        
    return pd.DataFrame()

def format_climate_covariates(df_extracted):
    """
    Formats the raw extracted data into the flat format required for BigQuery upload.
    Note: Real logic should pivot the 'source_file' depending on actual NetCDF shapes.
    """
    if df_extracted.empty:
        return df_extracted
    # Minimal transform pass-through
    return df_extracted

def upload_climate_covariates_to_bq(df, project_id='cameltrain', dataset='Forest_MATRIX', table='fia_matrix_training_cov_climate'):
    """
    Uploads the climate covariates dataframe to BigQuery.
    """
    if df is None or df.empty:
        print("No data to upload.")
        return
        
    from google.cloud import bigquery
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.{table}"
    
    # Use WRITE_APPEND so we can run chunks incrementally over days/weeks without overwriting.
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    
    print(f"Uploading {len(df)} rows to {table_id}...")
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # Wait for completion
    print(f"Successfully uploaded {len(df)} rows to {table_id}.")
