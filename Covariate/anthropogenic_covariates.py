import pandas as pd
import rasterio
from concurrent.futures import ThreadPoolExecutor, as_completed

# Define the Google Cloud Storage endpoints for the raster files
# Assuming the user uploads the downloaded Venter and Ibisch datasets to this bucket
RASTER_CONFIG = {
    'HFP1993': 'gs://cameltrain/covariates/HFP1993.tif',
    'HFP2009': 'gs://cameltrain/covariates/HFP2009.tif',
    'ROADLESS': 'gs://cameltrain/covariates/roadlesskm2.tif'
}

def _extract_raster_band(df_coords, var_key, url):
    """
    Extracts a value for all coordinates from a rasterio-compatible URI (e.g. gs://).
    """
    results = []
    
    # We use rasterio's internal VFS to stream the rasters directly from GCS
    # without downloading massive files locally. Application Default Credentials
    # will automatically authenticate the gs:// calls.
    try:
        env_kwargs = {
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR"
        }
        with rasterio.Env(**env_kwargs):
            # rasterio handles the gs:// prefix seamlessly
            with rasterio.open(url) as src:
                coords = [(r['LON'], r['LAT']) for _, r in df_coords.iterrows()]
                
                # Fetch exact pixel values
                for val in src.sample(coords):
                    res = val[0]
                    # Convert to float and filter out common nodata values
                    results.append(float(res) if pd.notna(res) and res != src.nodata else None)
    except Exception as e:
        print(f"Error reading {var_key} from {url}: {e}")
        results = [None] * len(df_coords)
        
    return results

def fetch_static_anthropogenic_rasters(df_coords, max_workers=3):
    """
    Extracts H1, H2, and H3 concurrently for a DataFrame of coordinates using ThreadPoolExecutor.
    """
    print(f"Fetching static Anthropogenic rasters (H1, H2, H3) for {len(df_coords)} coordinates...")
    df_out = df_coords[['LAT', 'LON']].copy()
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_var = {}
        for key, url in RASTER_CONFIG.items():
            future = executor.submit(_extract_raster_band, df_coords, key, url)
            future_to_var[future] = key
            
        for future in as_completed(future_to_var):
            col_name = future_to_var[future]
            try:
                data = future.result()
                df_out[col_name] = data
            except Exception as e:
                print(f"Failed to extract {col_name}: {e}")
                df_out[col_name] = [None] * len(df_coords)
                
    # Calculate derived covariates based on the original R code:
    # H1 = Human Footprint 2009
    # H2 = Human Footprint 2009 - Human Footprint 1993
    # H3 = Roadless Areas
    
    h1_out = df_out['HFP2009']
    
    # H2 is the difference (can only compute if both are not None)
    h2_out = []
    for h2009, h1993 in zip(df_out['HFP2009'], df_out['HFP1993']):
        if h2009 is not None and h1993 is not None:
            h2_out.append(h2009 - h1993)
        else:
            h2_out.append(None)
            
    h3_out = df_out['ROADLESS']
    # The original R pipeline filled NAs in H3 and H4 with 0
    h3_out = h3_out.fillna(0)
    
    # Pack exactly what the downstream dataset needs
    return pd.DataFrame({
        'LAT': df_out['LAT'],
        'LON': df_out['LON'],
        'H1_hfp2009': h1_out,
        'H2_hfp_change': h2_out,
        'H3_roadless': h3_out
    })

def _init_ee():
    import ee
    try:
        ee.Initialize(project='cameltrain')
    except Exception as e:
        print(f"Warning: Earth Engine initialization failed: {e}")

def fetch_protected_areas_ee(df_coords, chunk_size=5000):
    """
    Determines if coordinates fall within the World Database on Protected Areas (WDPA).
    Returns H4 covariate.
    """
    import ee
    print(f"Fetching WDPA Protected Areas (H4) via Earth Engine for {len(df_coords)} coordinates...")
    _init_ee()
    
    results = []
    wdpa_fc = ee.FeatureCollection('WCMC/WDPA/current/polygons')
    
    for start_idx in range(0, len(df_coords), chunk_size):
        chunk = df_coords.iloc[start_idx:start_idx+chunk_size]
        
        # Build Points FeatureCollection
        features = []
        for _, row in chunk.iterrows():
            geom = ee.Geometry.Point([row['LON'], row['LAT']])
            feat = ee.Feature(geom, {'LAT': row['LAT'], 'LON': row['LON']})
            features.append(feat)
            
        fc = ee.FeatureCollection(features)
        
        # A spatial filter is faster: intersect points with the WDPA polygons.
        # Alternatively, we can use an EE spatial join to check intersection
        spatialFilter = ee.Filter.intersects(
            leftField='.geo',
            rightField='.geo',
            maxError=100
        )
        
        # Save intersecting polygon WDPA IDs to the points
        saveAllJoin = ee.Join.saveFirst(
            matchKey='wdpa_match',
            outer=True
        )
        
        joined = saveAllJoin.apply(fc, wdpa_fc, spatialFilter)
        
        try:
            chunk_results = joined.getInfo()['features']
            for feat in chunk_results:
                props = feat['properties']
                lon, lat = props.get('LON'), props.get('LAT')
                
                # If 'wdpa_match' exists, it means the point intersected a protected area
                is_protected = 1 if props.get('wdpa_match') is not None else 0
                
                results.append({
                    'LAT': lat, 'LON': lon,
                    'H4_protected': is_protected
                })
        except Exception as e:
            print(f"Error extracting EE values for chunk starting at index {start_idx}: {e}")
            
    df_h4 = pd.DataFrame(results)
    
    # Fill any missing extractions with 0 as defined in original script
    if 'H4_protected' in df_h4.columns:
        df_h4['H4_protected'] = df_h4['H4_protected'].fillna(0)
        
    return df_h4
