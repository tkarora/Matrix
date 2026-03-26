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
                    refps='1981-01-01',
                    refpe='2010-12-31',
                    fefps=f'{year-1}-01-01',
                    fefpe=f'{year+1}-12-31',
                    xmin=xmin,
                    xmax=xmax,
                    ymin=ymin,
                    ymax=ymax,
                    output=base_output_dir + '/'
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
    nc_files = glob.glob(os.path.join(netcdf_dir, '*_bio*.nc'))
    if not nc_files:
        print("No BioClim NetCDF files found for extraction.")
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
    Pivots the 'source_file' string to explicitly map variables (bio1..bio19) against Year and Scenario.
    """
    if df_extracted.empty:
        return df_extracted
        
    import re
    
    # Example filename: CHELSA_MPI-M_MPI-ESM1-2-LR_bio1_historical_r1i1p1f1_2009-01-01_2011-12-31.nc
    # We want to pull: Variable (bio1), Scenario (historical), Target Year (middle of slice, 2010)
    
    records = []
    
    # Iterate dynamically based on the filename strings attached during extraction
    for idx, row in df_extracted.iterrows():
        fname = row.get('source_file', '')
        
        # CHELSA logic dumps "bioX" or "pr"/"tas"
        var_match = re.search(r'_(bio\d+|gdd|tas|tasmax|tasmin|pr)_', fname)
        variable = var_match.group(1) if var_match else 'unknown'
        
        # Extract the scenario type (historical, ssp245, etc)
        scenario_match = re.search(r'_(historical|ssp245|ssp585)_', fname)
        scenario = scenario_match.group(1) if scenario_match else 'historical'
        
        # Extract the start year from the dates at the end of the file string
        year_match = re.search(r'_(\d{4})-\d{2}-\d{2}_\d{4}-\d{2}-\d{2}\.nc', fname)
        target_year = int(year_match.group(1)) + 1 if year_match else None  # Add 1 because we did year-1 for fetch window
        
        # The actual raster value is usually in a column named with the variable, or 'Band1', or 'Band1' is the default output 
        val = None
        for col in [variable, 'Band1']:
            if col in row and pd.notnull(row[col]):
                val = row[col]
                break
                
        records.append({
            'LAT': row['queried_LAT'],
            'LON': row['queried_LON'],
            'Year': target_year,
            'Scenario': scenario,
            'Variable': variable,
            'Value': val
        })
        
    df_long = pd.DataFrame(records)
    
    # Pivot so each BioClim variable becomes its own column (required for ML matrix)
    df_wide = df_long.pivot_table(
        index=['LAT', 'LON', 'Year', 'Scenario'], 
        columns='Variable', 
        values='Value', 
        aggfunc='first'
    ).reset_index()
    
    return df_wide

def _process_single_chunk_task(chunk, i, scenarios, target_table):
    import shutil
    import os
    
    temp_dir = f"/tmp/climate_data_{i}"
    
    print(f"\n--- Thread starting Spatial Chunk {i+1} [{chunk['num_points']} points] ---")
    
    try:
        # 1. Fetch raw data to isolated temp directory
        out_dir = fetch_climate_data_for_chunk(chunk, base_output_dir=temp_dir, scenarios=scenarios)
        
        # 2. Extract specific LAT/LONs
        df_extracted = extract_points_from_climate_data(chunk['df'], out_dir)
        
        # 3. Pivot to Wide Bioclim format
        df_clean = format_climate_covariates(df_extracted)
        
        # 4. Upload to BQ
        upload_climate_covariates_to_bq(df_clean, table=target_table)
    except Exception as e:
        print(f"Error processing chunk {i+1}: {e}")
    finally:
        # 5. Clean up the isolated grid temp directory for this chunk
        print(f"Purging temporary NetCDF grids in {temp_dir} to save memory...")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)

def process_and_upload_climate_chunks(df_coords, target_table="fia_matrix_training_cov_climate", tile_size=5.0, scenarios=None, max_workers=3):
    """
    Orchestrates the entire climate workflow:
    1. Chunks specific coordinates spatially to avoid memory overload limits
    2. Downloads raw NetCDF files using CHELSA for standard models and loops over required years
    3. Extracts point data from those grids using Xarray
    4. Formats and pivots variables into standard Bioclim layouts
    5. Appends to BigQuery iteratively while deleting the /tmp cache per chunk
    """
    from concurrent.futures import ProcessPoolExecutor, as_completed
    
    if len(df_coords) == 0:
        print("No new coordinates to process. Pipeline is caught up!")
        return
        
    chunks = chunk_coordinates_spatially(df_coords, tile_size=tile_size)
    
    print(f"Starting ProcessPoolExecutor with {max_workers} workers for {len(chunks)} chunks...")
    
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_process_single_chunk_task, chunk, i, scenarios, target_table): i for i, chunk in enumerate(chunks)}
        
        for future in as_completed(futures):
            # Acknowledges completion and surfaces any uncaught worker thread exceptions
            try:
                future.result()
            except Exception as exc:
                print(f"A chunk generated an exception: {exc}")

def upload_climate_covariates_to_bq(df, project_id='cameltrain', dataset='Forest_MATRIX', table='fia_matrix_training_cov_climate'):
    """
    Uploads the climate covariates dataframe to BigQuery.
    """
    if df is None or df.empty:
        print("No data to upload.")
        return
        
    import os
    
    # [BUGFIX] Prevent MutualTLSChannelError (Exit Code -11)
    # The default google.auth credential workflow sometimes tries to execute an external
    # mTLS (mutual TLS) certificate provider binary (like 'ecclesia' or Corp Airlock).
    # We must disable BOTH the endpoint routing AND the certificate fetcher command.
    os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
    os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'
        
    from google.cloud import bigquery
    client = bigquery.Client(project=project_id)
    table_id = f"{project_id}.{dataset}.{table}"
    
    # Use WRITE_APPEND so we can run chunks incrementally over days/weeks without overwriting.
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND")
    
    print(f"Uploading {len(df)} rows to {table_id}...")
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()  # Wait for completion
    print(f"Successfully uploaded {len(df)} rows to {table_id}.")
