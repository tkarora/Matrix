import os
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'
import argparse
import pandas as pd
from topography_covariates import fetch_topography_properties
from covariates import get_unique_training_coordinates, process_and_upload_in_chunks

def parse_args():
    parser = argparse.ArgumentParser(description="Test Topography covariates extraction pipeline.")
    parser.add_argument("--test-extract", action="store_true", help="Run extraction on a small subset locally.")
    parser.add_argument("--test-upload", action="store_true", help="Run full extraction and upload to BigQuery in chunks.")
    parser.add_argument("--limit", type=int, default=3, help="Row limit for testing/fetching base coordinates.")
    return parser.parse_args()

def main():
    args = parse_args()
    
    if args.test_extract:
        print("Testing topography extraction (EarthEnv /vsicurl/)...")
        # Fetch a few points from the base training table
        df_coords = get_unique_training_coordinates(target_table='fia_matrix_training_cov_topography', limit=args.limit)
        if len(df_coords) == 0:
            print("No coordinates found to extract.")
            return
            
        # Run extraction
        df_merged = fetch_topography_properties(df_coords)
        print("\n=== Topography Result Head ===")
        print(df_merged.head())
        print("==============================")
        
    if args.test_upload:
        # Full background upload mode
        limit_val = args.limit if args.limit and args.limit != 3 else None
        df_coords = get_unique_training_coordinates(target_table='fia_matrix_training_cov_topography', limit=limit_val)
        process_and_upload_in_chunks(
            df_coords, 
            extractor_func=fetch_topography_properties, 
            chunk_size=5000, 
            target_table='fia_matrix_training_cov_topography'
        )

if __name__ == "__main__":
    main()
