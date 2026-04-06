import os
import argparse
import json
from google.cloud import bigquery
from google.cloud import storage

# Authentication stability inside Google corp network
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'

def generate_map(args):
    client = bigquery.Client(project=args.project)
    storage_client = storage.Client(project=args.project)
    bucket = storage_client.bucket(args.bucket)
    
    blob_path = "training_task_mapping/task_map.json"
    blob = bucket.blob(blob_path)
    
    # Query for unique Forest Types from the training set
    query = """
        SELECT DISTINCT FT
        FROM `cameltrain.Forest_MATRIX.fia_matrix_train_set`
        WHERE FT IS NOT NULL
        ORDER BY FT
    """
    print("Querying unique Forest Types from BigQuery...")
    df = client.query(query).to_dataframe()
    fts = df['FT'].dropna().tolist()
    
    print(f"Found {len(fts)} unique Forest Types.")
    
    mapping = {}
    for idx, ft in enumerate(fts):
        mapping[str(idx)] = {
            'assigned_ft': int(ft)
        }
        
    print(f"Uploading mapping to gs://{args.bucket}/{blob_path}...")
    blob.upload_from_string(json.dumps(mapping, indent=2))
    print("Upload complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="cameltrain")
    parser.add_argument("--bucket", default="matrix_model")
    args = parser.parse_args()
    generate_map(args)
