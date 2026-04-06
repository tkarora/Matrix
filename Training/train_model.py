import os
import argparse
import subprocess
import shutil
import glob
import pandas as pd
import numpy as np
from google.cloud import bigquery
from google.cloud import storage
from training_utils import prepare_data_pandas, prepare_data_bq

# Authentication stability
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'

def main():
    parser = argparse.ArgumentParser(description="Matrix Model Training Orchestrator")
    parser.add_argument("--ft", type=int, required=False, help="Forest Type to train")
    parser.add_argument("--r-script", default="MATRIX_training_distributed.R", help="Path to R training script")
    parser.add_argument("--cloud", action="store_true", help="Run in Cloud mode (uses Cloud Run/GCS)")
    parser.add_argument("--bucket", default="matrix_model", help="GCS bucket for task maps and models")
    parser.add_argument("--models-path", default="retrained_models", help="Path in bucket or local dir to save models")
    parser.add_argument("--project", default="cameltrain", help="GCP project")
    parser.add_argument("--input-csv", help="Optional local input CSV (skips BigQuery read)")
    parser.add_argument("--public-export", action="store_true", help="Enable public data sharing export in R")
    parser.add_argument("--limit", type=int, help="Limit number of rows to query from BigQuery")
    
    args = parser.parse_args()
    
    task_index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", 0))
    
    ft = args.ft
    if args.cloud and ft is None:
        print(f"Cloud mode active. Loading task map to determine FT for task {task_index}...")
        import json
        storage_client = storage.Client(project=args.project)
        bucket = storage_client.bucket(args.bucket)
        blob = bucket.blob("training_task_mapping/task_map.json")
        
        try:
            map_data = json.loads(blob.download_as_string())
            task_info = map_data.get(str(task_index))
            if task_info:
                ft = task_info.get('assigned_ft')
                print(f"Assigned Forest Type: {ft}")
            else:
                raise ValueError(f"No mapping found for task index {task_index}")
        except Exception as e:
            print(f"Error loading task map: {e}")
            raise
            
    if ft is None:
        raise ValueError("Forest Type (--ft) must be specified or available via task map in cloud mode.")
        
    # 1. Get Data
    if args.input_csv:
        df_ug, df_mt, df_rc = prepare_data_pandas(args.input_csv, ft)
        print("Using local input CSV. Validation data will not be queried from BigQuery.")
    else:
        df_ug, df_mt, df_rc = prepare_data_bq(args.project, ft, args.limit, split="train")
        df_ug_val, df_mt_val, df_rc_val = prepare_data_bq(args.project, ft, args.limit, split="val")
        
    print(f"Loaded Train: UG={len(df_ug)}, MT={len(df_mt)}, RC={len(df_rc)} rows.")
    
    input_ug = f"/tmp/train_input_ug_ft{ft}_{task_index}.csv"
    input_mt = f"/tmp/train_input_mt_ft{ft}_{task_index}.csv"
    input_rc = f"/tmp/train_input_rc_ft{ft}_{task_index}.csv"
    
    df_ug.to_csv(input_ug, index=False)
    df_mt.to_csv(input_mt, index=False)
    df_rc.to_csv(input_rc, index=False)
    
    if not args.input_csv:
        print(f"Loaded Val: UG={len(df_ug_val)}, MT={len(df_mt_val)}, RC={len(df_rc_val)} rows.")
        input_ug_val = f"/tmp/val_input_ug_ft{ft}_{task_index}.csv"
        input_mt_val = f"/tmp/val_input_mt_ft{ft}_{task_index}.csv"
        input_rc_val = f"/tmp/val_input_rc_ft{ft}_{task_index}.csv"
        
        df_ug_val.to_csv(input_ug_val, index=False)
        df_mt_val.to_csv(input_mt_val, index=False)
        df_rc_val.to_csv(input_rc_val, index=False)
        
    print("Saved temporary inputs.")
        
    # 2. Prepare Output Dir
    if args.cloud:
        local_out_dir = f"/tmp/train_output_ft{ft}_{task_index}"
    else:
        local_out_dir = args.models_path
        
    os.makedirs(local_out_dir, exist_ok=True)
    
    # 3. Call R Script
    print(f"Invoking R script: {args.r_script} for FT {ft}...")
    
    cmd = [
        "Rscript", args.r_script,
        f"--input_ug={input_ug}",
        f"--input_mt={input_mt}",
        f"--input_rc={input_rc}",
        f"--ft={ft}",
        f"--out_dir={local_out_dir}",
        f"--public_export={str(args.public_export).lower()}"
    ]
    
    if not args.input_csv:
        cmd.extend([
            f"--val_ug={input_ug_val}",
            f"--val_mt={input_mt_val}",
            f"--val_rc={input_rc_val}"
        ])

    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"Rscript STDOUT:\n{result.stdout}")
    except subprocess.CalledProcessError as e:
        print(f"Error in Rscript! Exit Code: {e.returncode}")
        print(f"Rscript STDOUT:\n{e.stdout}")
        print(f"Rscript STDERR:\n{e.stderr}")
        return
        
    # 4. Upload to GCS if in Cloud mode
    if args.cloud:
        print("Uploading models to GCS...")
        storage_client = storage.Client(project=args.project)
        bucket = storage_client.bucket(args.bucket)
        
        # Find generated .RData files
        rdata_files = glob.glob(os.path.join(local_out_dir, "*.RData"))
        for local_file in rdata_files:
            file_name = os.path.basename(local_file)
            blob_path = f"{args.models_path}/{file_name}"
            blob = bucket.blob(blob_path)
            blob.upload_from_filename(local_file)
            print(f"Uploaded {file_name} to gs://{args.bucket}/{blob_path}")
            
        # Clean up tmp files
        shutil.rmtree(local_out_dir, ignore_errors=True)
        
        # Clean up generated input CSVs
        for f in glob.glob(f"/tmp/*_ft{ft}_{task_index}.csv"):
            try:
                os.remove(f)
                print(f"Removed temp file: {f}")
            except OSError as e:
                print(f"Error removing {f}: {e}")
            
    print("Training task completed successfully.")

if __name__ == "__main__":
    main()
