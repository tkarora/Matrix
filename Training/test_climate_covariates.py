import argparse
from covariates import get_unique_training_coordinates
from climate_covariates import chunk_coordinates_spatially, fetch_climate_data_for_chunk, extract_points_from_climate_data

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract climate covariates for FIA data.")
    parser.add_argument('--test-climate-bq', action='store_true', help="Climate Step 2: Test coordinate extraction and spatial chunking.")
    parser.add_argument('--test-climate-fetch', action='store_true', help="Climate Step 3: Test downloading CHELSA-CMIP6 NetCDF files.")
    parser.add_argument('--test-climate-extract', action='store_true', help="Climate Step 4: Test extracting exact points from downloaded NetCDFs.")
    parser.add_argument('--limit', type=int, default=None, help="Limit number of coordinates for testing. Pass None for all.")
    args = parser.parse_args()

    if args.test_climate_bq:
        print("--- Testing Climate Step 2: Coordinate Chunking ---")
        df_coords = get_unique_training_coordinates(limit=args.limit)
        chunks = chunk_coordinates_spatially(df_coords, tile_size=5.0)
        
        print(f"\nCreated {len(chunks)} spatial chunks.")
        for i, chunk in enumerate(chunks[:5]): # show top 5 chunks
            print(f"Chunk {i+1} [Points: {chunk['num_points']}]: Bounds(xmin={chunk['xmin']:.1f}, xmax={chunk['xmax']:.1f}, ymin={chunk['ymin']:.1f}, ymax={chunk['ymax']:.1f})")
        if len(chunks) > 5:
            print("... (more chunks)")
        print("-------------------------------------------")

    if args.test_climate_fetch:
        print("--- Testing Climate Step 3: CHELSA-CMIP6 Fetching ---")
        df_coords = get_unique_training_coordinates(limit=args.limit)
        chunks = chunk_coordinates_spatially(df_coords, tile_size=5.0)
        
        # We will test fetching just one very small piece of data for the *first* chunk
        test_chunk = chunks[0]
        # To avoid massive downloads in tests, let's shrink the bounding box arbitrarily smaller for the test
        test_chunk['xmax'] = test_chunk['xmin'] + 0.1
        test_chunk['ymax'] = test_chunk['ymin'] + 0.1
        
        out_dir = fetch_climate_data_for_chunk(test_chunk, base_output_dir="/tmp/climate_test")
        print(f"Test fetches complete in {out_dir}")
        print("-------------------------------------------")

    if args.test_climate_extract:
        print("--- Testing Climate Step 4: NetCDF Point Extraction ---")
        df_coords = get_unique_training_coordinates(limit=args.limit)
        chunks = chunk_coordinates_spatially(df_coords, tile_size=5.0)
        
        test_chunk = chunks[0]
        test_chunk['xmax'] = test_chunk['xmin'] + 0.1
        test_chunk['ymax'] = test_chunk['ymin'] + 0.1
        
        # 1. Fetch
        out_dir = fetch_climate_data_for_chunk(test_chunk, base_output_dir="/tmp/climate_test")
        
        # 2. Extract
        df_extracted = extract_points_from_climate_data(test_chunk['df'], out_dir)
        print("\nExtracted Data Sample:")
        print(df_extracted.head())
        print("-------------------------------------------")
