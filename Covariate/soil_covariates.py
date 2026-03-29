import pandas as pd
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

def _query_ssurgo_single(lat, lon):
    url = "https://SDMDataAccess.nrcs.usda.gov/Tabular/post.rest"
    query = f"""
    SELECT TOP 1 
        c.mukey,
        ch.dbthirdbar_r AS O1_bulk_density, 
        ch.ph1to1h2o_r AS O4_ph, 
        ch.ec_r AS O5_ec
    FROM mapunit mu 
    JOIN component c ON c.mukey = mu.mukey 
    JOIN chorizon ch ON ch.cokey = c.cokey 
    WHERE mu.mukey IN (SELECT * FROM SDA_Get_Mukey_from_intersection_with_WktWgs84('POINT({lon} {lat})'))
    ORDER BY c.comppct_r DESC, ch.hzdept_r ASC;
    """
    try:
        response = requests.post(url, json={"query": query, "format": "JSON"}, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if 'Table' in data and data['Table']:
                # Table returns lists of strings: [mukey, O1, O4, O5]
                row = data['Table'][0]
                return {
                    'LAT': lat, 'LON': lon,
                    'O1_bulk_density': float(row[1]) if row[1] else None,
                    'O4_ph': float(row[2]) if row[2] else None,
                    'O5_ec': float(row[3]) if row[3] else None
                }
    except Exception as e:
        pass
    
    # Return explicit None values on failure or missing data
    return {'LAT': lat, 'LON': lon, 'O1_bulk_density': None, 'O4_ph': None, 'O5_ec': None}

def fetch_ssurgo_properties(df_coords, max_workers=5):
    """
    Fetches physical soil properties from SSURGO SDA API for a dataframe of coordinates.
    """
    print(f"Fetching SSURGO properties for {len(df_coords)} coordinates...")
    results = []
    
    # Prepare list of dicts for faster iteration
    records = df_coords[['LAT', 'LON']].to_dict('records')
    
    # "The ThreadPoolExecutor is an Executor subclass that uses a pool of at most max_workers threads 
    # to execute calls asynchronously." (Source: Python docs, concurrent.futures)
    # This allows us to make multiple REST API calls concurrently without blocking the main workflow,
    # significantly speeding up the extraction geometry processing time.
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_coord = {executor.submit(_query_ssurgo_single, r['LAT'], r['LON']): r for r in records}
        
        # "Returns an iterator over the given futures that yields them as they complete." (Source: Python docs)
        # Using as_completed ensures we process the API responses as soon as they return, regardless of order.
        for i, future in enumerate(as_completed(future_to_coord)):
            res = future.result()
            results.append(res)
            if (i + 1) % 10 == 0 or (i + 1) == len(records):
                print(f"Processed {i + 1}/{len(records)} SSURGO points...")
                
    return pd.DataFrame(results)

def _init_ee():
    import ee
    try:
        ee.Initialize(project='cameltrain')
    except Exception as e:
        print(f"Warning: Earth Engine initialization failed: {e}")

def fetch_soilgrids_properties(df_coords, chunk_size=5000):
    """
    Fetches chemical soil properties from SoilGrids (Earth Engine) for a dataframe of coordinates.
    Uses Earth Engine's native parallelization (reduceRegions) to process in batches.
    """
    import ee
    print(f"Fetching SoilGrids properties via Earth Engine for {len(df_coords)} coordinates...")
    _init_ee()
    
    nitrogen = ee.Image("projects/soilgrids-isric/nitrogen_mean").select('nitrogen_0-5cm_mean')
    soc = ee.Image("projects/soilgrids-isric/soc_mean").select('soc_0-5cm_mean')
    
    # Combine bands to sample both at once
    combined_img = nitrogen.addBands(soc)
    
    results = []
    
    for start_idx in range(0, len(df_coords), chunk_size):
        chunk = df_coords.iloc[start_idx:start_idx+chunk_size]
        
        # Convert pandas chunk to ee.FeatureCollection
        features = []
        for _, row in chunk.iterrows():
            geom = ee.Geometry.Point([row['LON'], row['LAT']])
            feat = ee.Feature(geom, {'LAT': row['LAT'], 'LON': row['LON']})
            features.append(feat)
            
        fc = ee.FeatureCollection(features)
        
        # Earth Engine's native parallel batch processing
        sampled = combined_img.reduceRegions(
            collection=fc,
            reducer=ee.Reducer.first(),
            scale=250,
            tileScale=4
        )
        
        try:
            # Fetch the entire chunk's results back to Python in one network call
            chunk_results = sampled.getInfo()['features']
            
            for feat in chunk_results:
                props = feat['properties']
                lon, lat = props.get('LON'), props.get('LAT')
                
                n_res = props.get('nitrogen_0-5cm_mean')
                soc_res = props.get('soc_0-5cm_mean')
                
                cn_ratio = None
                if soc_res is not None and n_res is not None and n_res > 0:
                    cn_ratio = (float(soc_res) * 10) / float(n_res)
                    
                results.append({
                    'LAT': lat, 'LON': lon,
                    'O2_total_nitrogen': float(n_res) if n_res is not None else None,
                    'O3_cn_ratio': cn_ratio
                })
        except Exception as e:
            print(f"Error extracting EE values for chunk starting at index {start_idx}: {e}")
            
    return pd.DataFrame(results)
