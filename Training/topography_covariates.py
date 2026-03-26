import pandas as pd
import rasterio
from concurrent.futures import ThreadPoolExecutor, as_completed

# Map T1 to T12 based on EarthEnv Topography for 1km GMTED median resolution
TOPO_VARS = {
    'T1': ('aspectcosine', 'aspectcosine_1KMmn_GMTEDmd.tif'),
    'T2': ('aspectsine', 'aspectsine_1KMmn_GMTEDmd.tif'),
    'T3': ('dx', 'dx_1KMmn_GMTEDmd.tif'),
    'T4': ('dxx', 'dxx_1KMmn_GMTEDmd.tif'),
    'T5': ('dy', 'dy_1KMmn_GMTEDmd.tif'),
    'T6': ('dyy', 'dyy_1KMmn_GMTEDmd.tif'),
    'T7': ('pcurv', 'pcurv_1KMmn_GMTEDmd.tif'),
    'T8': ('roughness', 'roughness_1KMmn_GMTEDmd.tif'),
    'T9': ('slope', 'slope_1KMmn_GMTEDmd.tif'),
    'T10': ('tcurv', 'tcurv_1KMmn_GMTEDmd.tif'),
    'T11': ('tpi', 'tpi_1KMmn_GMTEDmd.tif'),
    'T12': ('tri', 'tri_1KMmn_GMTEDmd.tif')
}

BASE_URL = "https://data.earthenv.org/topography"

def _extract_topo_band(df_coords, var_key, filename):
    """
    Extracts a single topography variable for all coordinates using rasterio /vsicurl/.
    """
    url = f"/vsicurl/{BASE_URL}/{filename}"
    results = []
    
    # rasterio securely handles the HTTP connection and range requests.
    try:
        # Use Env to configure GDAL to handle Cloudflare caching headers correctly 
        # and prevent HEAD requests from misreporting range support.
        env_kwargs = {
            "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
            "CPL_VSIL_CURL_USE_HEAD": "NO"
        }
        with rasterio.Env(**env_kwargs):
            with rasterio.open(url) as src:
                # We construct an iterator of (lon, lat) points.
                coords = [(r['LON'], r['LAT']) for _, r in df_coords.iterrows()]
                
                # src.sample yields the pixel value at each coordinate.
                for val in src.sample(coords):
                    res = val[0]
                    results.append(float(res) if pd.notna(res) else None)
    except Exception as e:
        print(f"Error reading {var_key} from {url}: {e}")
        # Return a list of Nones matching length
        results = [None] * len(df_coords)
        
    return results

def fetch_topography_properties(df_coords, max_workers=6):
    """
    Extracts all 12 topography variables concurrently for a DataFrame of coordinates.
    """
    print(f"Fetching EarthEnv Topography via vsicurl for {len(df_coords)} coordinates...")
    
    # Initialize an output dataframe aligned with LAT and LON
    df_out = df_coords[['LAT', 'LON']].copy()
    
    # Requesting different TIFs means opening different network streaming connection pools,
    # so we multithread the variable extraction.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_var = {}
        for key, (name, filename) in TOPO_VARS.items():
            future = executor.submit(_extract_topo_band, df_coords, key, filename)
            future_to_var[future] = f"{key}_{name}"
            
        for future in as_completed(future_to_var):
            col_name = future_to_var[future]
            try:
                data = future.result()
                df_out[col_name] = data
            except Exception as e:
                print(f"Failed to extract {col_name}: {e}")
                df_out[col_name] = None
                
    return df_out
