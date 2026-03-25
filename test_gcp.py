import os
from google.cloud import bigquery
from dotenv import load_dotenv

def test_gcp_auth():
    load_dotenv()
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
    print(f"Testing authentication for project: {project_id}")
    
    try:
        # Initialize the storage client
        client = bigquery.Client(project=project_id)
        
        # List buckets
        datasets = list(client.list_datasets())
        print("Authentication successful!")
        print(f"Found {len(datasets)} datasets in the project.")
        
        if datasets:
            print("\nFirst 3 datasets:")
            for b_name in datasets[:3]:
                print(f" - {b_name.dataset_id}")
    except Exception as e:
        print(f"Authentication failed: {e}")
        print("\nPlease run: gcloud auth application-default login")

if __name__ == "__main__":
    test_gcp_auth()
