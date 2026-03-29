import argparse
import os
from dotenv import load_dotenv

# Load workspace bypass variables
load_dotenv()

from covariates import get_unique_training_coordinates, get_covariates, upload_covariates_to_bq, process_and_upload_in_chunks
from soil_covariates import fetch_ssurgo_properties, fetch_soilgrids_properties

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract soil covariates for FIA data.")
    parser.add_argument('--test-bq', action='store_true', help="Test Step 1: BigQuery coordinate extraction.")
    parser.add_argument('--test-ssurgo', action='store_true', help="Test Step 2: SSURGO API fetch logic.")
    parser.add_argument('--test-soilgrids', action='store_true', help="Test Step 3: SoilGrids EE fetch logic.")
    parser.add_argument('--test-merge', action='store_true', help="Test Step 4: Merging dataframes.")
    parser.add_argument('--test-upload', action='store_true', help="Test Step 5: Uploading to BigQuery.")
    
    parser.add_argument('--limit', type=int, default=None, help="Limit number of coordinates for testing. Pass None for all.")
    parser.add_argument('--chunk-size', type=int, default=5000, help="Chunk size for testing uploads.")
    args = parser.parse_args()
    
    if args.test_bq:
        print("--- Testing Step 1: BigQuery Extraction ---")
        df_coords = get_unique_training_coordinates(limit=args.limit)
        print("\nSample Data:")
        print(df_coords)
        print("-------------------------------------------")

    if args.test_ssurgo:
        print("--- Testing Step 2: SSURGO Extraction ---")
        df_coords = get_unique_training_coordinates(limit=args.limit)
        df_ssurgo = fetch_ssurgo_properties(df_coords)
        print("\nSSURGO Results:")
        print(df_ssurgo)
        print("-------------------------------------------")

    if args.test_soilgrids:
        print("--- Testing Step 3: SoilGrids (Earth Engine) Extraction ---")
        df_coords = get_unique_training_coordinates(limit=args.limit)
        df_soilgrids = fetch_soilgrids_properties(df_coords)
        print("\nSoilGrids Results:")
        print(df_soilgrids)
        print("-------------------------------------------")

    if args.test_merge:
        print("--- Testing Step 4: Merging Dataframes ---")
        df_coords = get_unique_training_coordinates(limit=args.limit)
        
        df_merged = get_covariates(df_coords)
        
        print("\nMerged Results:")
        print(df_merged)
        print("-------------------------------------------")

    if args.test_upload:
        print("--- Testing Step 5: BigQuery Upload ---")
        df_coords = get_unique_training_coordinates(limit=args.limit)
        process_and_upload_in_chunks(df_coords, chunk_size=args.chunk_size)
        print("-------------------------------------------")
