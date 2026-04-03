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
        
    if args.filter:
        filter_clause += f" {args.filter}"
        
    storage_client = storage.Client(project=args.project)
    bucket = storage_client.bucket(args.bucket)
    if args.output_name:
        blob_path = f"eval_worker_task_mapping/{args.output_name}"
    else:
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
    
    # Pass 1: Assign tasks to FTs and count them
    ft_task_assignments = {}
    for task_index in range(task_count):
        task_fraction = task_index / task_count
        assigned_ft = None
        
        last_cum = 0.0
        for _, row in df_cnt.iterrows():
            this_cum = row['cum_plots']
            if task_fraction < this_cum:
                assigned_ft = row['FT']
                break
            last_cum = this_cum
            
        if assigned_ft is None:
            assigned_ft = df_cnt.iloc[-1]['FT']
            
        if assigned_ft not in ft_task_assignments:
            ft_task_assignments[assigned_ft] = []
        ft_task_assignments[assigned_ft].append(task_index)
        
    # Pass 2: Build the final map with correct tasks_for_ft and sub_task_index
    for ft, task_indices in ft_task_assignments.items():
        tasks_allocated = len(task_indices)
        for sub_idx, task_idx in enumerate(task_indices):
            mapping[str(task_idx)] = {
                'assigned_ft': int(ft),
                'tasks_for_ft': int(tasks_allocated),
                'sub_task_index': int(sub_idx)
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
    parser.add_argument("--filter", default="", help="Custom SQL filter clause")
    parser.add_argument("--output_name", default="", help="Custom output blob name")
    args = parser.parse_args()
    generate_map(args)
