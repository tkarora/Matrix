import argparse
import os
import pandas as pd
from dotenv import load_dotenv

# Load workspace bypass variables
load_dotenv()

from covariates import get_unique_training_coordinates, upload_covariates_to_bq, process_and_upload_in_chunks
from anthropogenic_covariates import fetch_static_anthropogenic_rasters, fetch_protected_areas_ee

def get_anthropogenic_covariates(df_coords):
    """
    Retrieves Anthropogenic covariates from GCS rasters (H1, H2, H3) and Earth Engine (H4).
    Merges both sub-dataframes together.
    """
    df_static = fetch_static_anthropogenic_rasters(df_coords)
    df_ee = fetch_protected_areas_ee(df_coords)
    
    print("Merging Static and Earth Engine dataframes...")
    df_merged = pd.merge(df_static, df_ee, on=['LAT', 'LON'], how='left')
    return df_merged

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract Anthropogenic covariates for FIA data.")
    parser.add_argument('--test-bq', action='store_true', help="Test Step 1: BigQuery coordinate extraction.")
    parser.add_argument('--test-extract', action='store_true', help="Test Step 2: Extraction logic.")
    parser.add_argument('--test-upload', action='store_true', help="Test Step 3: Uploading to BigQuery.")
    
    parser.add_argument('--limit', type=int, default=None, help="Limit number of coordinates for testing. Pass None for all.")
    parser.add_argument('--chunk-size', type=int, default=5000, help="Chunk size for testing uploads.")
    args = parser.parse_args()
    
    TARGET_TABLE = 'fia_matrix_training_cov_anthropogenic'
    
    if args.test_bq:
        print("--- Testing Step 1: BigQuery Extraction ---")
        df_coords = get_unique_training_coordinates(target_table=TARGET_TABLE, limit=args.limit)
        print("\nSample Data:")
        print(df_coords)
        print("-------------------------------------------")

    if args.test_extract:
        print("--- Testing Step 2: Extraction logic ---")
        df_coords = get_unique_training_coordinates(target_table=TARGET_TABLE, limit=args.limit)
        df_merged = get_anthropogenic_covariates(df_coords)
        print("\nExtracted Results:")
        print(df_merged)
        print("-------------------------------------------")

    if args.test_upload:
        print("--- Testing Step 3: BigQuery Upload ---")
        df_coords = get_unique_training_coordinates(target_table=TARGET_TABLE, limit=args.limit)
        process_and_upload_in_chunks(df_coords, extractor_func=get_anthropogenic_covariates, chunk_size=args.chunk_size, target_table=TARGET_TABLE)
        print("-------------------------------------------")
