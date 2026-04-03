import os
import argparse
import json
import pandas as pd
from google.cloud import bigquery
from google.cloud import storage

# Authentication stability inside Google corp network
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'

def generate_map(args):
    client = bigquery.Client(project=args.project)
    
    if args.test:
        filter_clause = "AND ID IN (SELECT DISTINCT PlotID FROM `cameltrain.Forest_MATRIX.fia_matrix_test_set`)"
        split_name = "test"
    elif args.val:
        filter_clause = "AND ID IN (SELECT DISTINCT PlotID FROM `cameltrain.Forest_MATRIX.fia_matrix_val_set`)"
        split_name = "val"
    else:
        filter_clause = ""
        split_name = "full"
        
    storage_client = storage.Client(project=args.project)
    bucket = storage_client.bucket(args.bucket)
    blob_path = f"eval_worker_task_mapping/{split_name}_task_map_{args.tasks}.json"
    blob = bucket.blob(blob_path)
    
    if blob.exists():
        print(f"Mapping gs://{args.bucket}/{blob_path} already exists. Skipping map generation.")
        return

    cnt_query = f"""
        SELECT FT, COUNT(DISTINCT ID) as cnt
        FROM `cameltrain.Forest_MATRIX.fia_grid_3km_eval`
        WHERE 1=1 {filter_clause}
        GROUP BY FT
        ORDER BY cnt DESC
    """
    print(f"Querying FT counts for split '{split_name}'...")
    df_cnt = client.query(cnt_query).to_dataframe()
    total_plots = df_cnt['cnt'].sum()
    
    df_cnt['cum_plots'] = df_cnt['cnt'].cumsum() / total_plots
    
    task_count = args.tasks
    mapping = {}
    
    for task_index in range(task_count):
        task_fraction = task_index / task_count
        assigned_ft = None
        sub_task_index = 0
        tasks_for_ft = 1
        
        last_cum = 0.0
        for _, row in df_cnt.iterrows():
            this_cum = row['cum_plots']
            if task_fraction < this_cum:
                assigned_ft = row['FT']
                pos_within_ft = (task_fraction - last_cum) / (this_cum - last_cum)
                tasks_allocated = int(round((this_cum - last_cum) * task_count))
                if tasks_allocated == 0: tasks_allocated = 1
                
                sub_task_index = int(pos_within_ft * tasks_allocated)
                tasks_for_ft = tasks_allocated
                break
            last_cum = this_cum

        if assigned_ft is None:
            assigned_ft = df_cnt.iloc[-1]['FT']
            tasks_allocated = int(round((1.0 - last_cum) * task_count))
            if tasks_allocated == 0: tasks_allocated = 1
            sub_task_index = tasks_allocated - 1
            tasks_for_ft = tasks_allocated

        if sub_task_index >= tasks_for_ft:
            sub_task_index = tasks_for_ft - 1

        mapping[str(task_index)] = {
            'assigned_ft': int(assigned_ft),
            'tasks_for_ft': int(tasks_for_ft),
            'sub_task_index': int(sub_task_index)
        }

    # Using the storage client and blob initialized at the start of the function
    
    print(f"Uploading mapping to gs://{args.bucket}/{blob_path}...")
    blob.upload_from_string(json.dumps(mapping, indent=2))
    print("Upload complete!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", default="cameltrain")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--tasks", type=int, default=1000)
    parser.add_argument("--test", action="store_true")
    parser.add_argument("--val", action="store_true")
    args = parser.parse_args()
    generate_map(args)
