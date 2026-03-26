import argparse
import os
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'

from covariates import get_unique_training_coordinates
from climate_covariates import process_and_upload_climate_chunks

def get_scenarios_from_bq():
    """
    Dynamically gets the min/max observation years from fia_matrix_training_base
    to construct optimal year ranges instead of downloading 2000-2025.
    For this specific script, we simulate this or fetch it directly.
    """
    from google.cloud import bigquery
    client = bigquery.Client()
    query = """
    SELECT MIN(MEASYEAR_1) as min_y, MAX(MEASYEAR_2) as max_y 
    FROM `cameltrain.Forest_MATRIX.fia_matrix_training_base`
    """
    try:
        df = client.query(query).to_dataframe()
        min_y = int(df['min_y'].iloc[0])
        max_y = int(df['max_y'].iloc[0])
        print(f"Detected observation year range from BigQuery: {min_y} - {max_y}")
    except Exception as e:
        print(f"Could not fetch dynamic bounds from BQ, defaulting to 2000-2025: {e}")
        min_y, max_y = 2000, 2025

    return [
        {'name': 'historical', 'activity_id': 'CMIP', 'experiment_id': 'historical', 'years': range(min_y, 2015)},
        # Usually ssp245 and ssp585 are run from 2015+ 
        {'name': 'ssp245', 'activity_id': 'ScenarioMIP', 'experiment_id': 'ssp245', 'years': range(max(2015, min_y), max_y + 1)}
    ]

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run Climate Covariates Pipeline Orchestrator")
    parser.add_argument('--full', action='store_true', help="Run the pipeline for ALL coordinates")
    parser.add_argument('--limit', type=int, default=None, help="Limit number of coordinates for testing")
    parser.add_argument('--test-integration', action='store_true', help="Run a dry run on 5 points to verify BioClim logic fixes")
    args = parser.parse_args()

    scenarios = get_scenarios_from_bq()

    if args.test_integration:
        print("Starting E2E Integration Dry Run for BioClim variables over a 3-year padded window...")
        # Get exactly 5 points
        df_coords = get_unique_training_coordinates(
            target_table="fia_matrix_training_cov_climate_TEST", 
            limit=5
        )
        # Override purely for a fast test: 2010 historical only
        test_scenarios = [{'name': 'historical', 'activity_id': 'CMIP', 'experiment_id': 'historical', 'years': [2010]}]
        
        process_and_upload_climate_chunks(
            df_coords, 
            target_table="fia_matrix_training_cov_climate_TEST", 
            tile_size=5.0,
            scenarios=test_scenarios
        )
        print("\nIntegration test complete. Verify target table output!")
    else:
        # Normal execution
        df_coords = get_unique_training_coordinates(
            target_table="fia_matrix_training_cov_climate", 
            limit=args.limit
        )
        
        process_and_upload_climate_chunks(
            df_coords, 
            target_table="fia_matrix_training_cov_climate", 
            tile_size=5.0,
            scenarios=scenarios
        )
