import os
import argparse
import subprocess
import shutil
import glob
import pandas as pd
import numpy as np
from sklearn.metrics import mean_squared_error, mean_absolute_error
from scipy.spatial.distance import cosine
from google.cloud import bigquery
from concurrent.futures import ThreadPoolExecutor

# Authentication stability
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'

# The legacy R simulation naturally expects an HPC scheduler to define its chunk via SLURM_ARRAY_TASK_ID.
# Since this Python orchestrator organically handles Cloud Run parallelization natively via CLOUD_RUN_TASK_INDEX 
# and explicitly subsets the data, we strictly set the SLURM ID to "1" so R processes its assigned local subset flawlessly.
os.environ['SLURM_ARRAY_TASK_ID'] = '1'

def compute_metrics(row):
    # Extract prediction array and true array
    pred = row[[f'TPH2_{i}' for i in range(1, 14)]].values.astype(float)
    true = row[[f'TRUE_TPH2_{i}' for i in range(1, 14)]].values.astype(float)
    
    # Vector RMSE (squared error over the 13 bins)
    rmse = np.sqrt(mean_squared_error(true, pred))
    # Mean Absolute Error
    mae = mean_absolute_error(true, pred)
    # Cosine Similarity (handles 0 vectors gracefully)
    norm_pred = np.linalg.norm(pred)
    norm_true = np.linalg.norm(true)
    
    if norm_pred == 0 and norm_true == 0:
        cos_sim = 1.0
    elif norm_pred == 0 or norm_true == 0:
        cos_sim = 0.0
    else:
        cos_sim = 1 - cosine(true, pred)
        
    # Total Density Diff
    total_diff = np.sum(pred) - np.sum(true)
    
    return pd.Series({'RMSE': rmse, 'MAE': mae, 'Cosine_Sim': cos_sim, 'Density_Diff': total_diff})

def simulate_group(dy_val, group, task_index, args, out_dir, chunk_id=None):
    if dy_val <= 0:
        return None
        
    suffix = f"_c{chunk_id}" if chunk_id is not None else ""
    print(f"--> Simulating {len(group)} plots for explicit interval dY = {dy_val} years{suffix}...")
    input_csv = f"/tmp/eval_input_tmp_{task_index}_dy{dy_val}{suffix}.csv"
    group.to_csv(input_csv, index=False)
    
    prefix = f"eval_out_dy{dy_val}{suffix}"
    
    cmd = [
        "Rscript", args.rscript,
        "--mode=NA_FT",
        f"--input={input_csv}",
        f"--models={args.models}",
        f"--biomass={args.biomass}",
        f"--out_dir={out_dir}",
        f"--years={dy_val}",
        f"--out_prefix={prefix}",
        "--quiet=false"
    ]
    
    try:
        subprocess.run(cmd, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as e:
        print(f"    Encountered an error in Rscript for dY={dy_val}! Exit Code: {e.returncode}")
        print(f"    Rscript STDOUT: {e.stdout}")
        print(f"    Rscript STDERR: {e.stderr}")
        return None
        
    sim_output_file = os.path.join(out_dir, f"{prefix}_1.csv")
    if not os.path.exists(sim_output_file):
        print(f"    Warning: Expected output {sim_output_file} not found.")
        return None
        
    preds = pd.read_csv(sim_output_file)
    merged = pd.merge(preds, group[['ID'] + [f'TRUE_TPH2_{i}' for i in range(1, 14)]], on='ID')
    
    metrics_df = merged.apply(compute_metrics, axis=1)
    
    final_row = pd.concat([merged['ID'], merged[[f'TPH2_{i}' for i in range(1, 14)]], merged[[f'TRUE_TPH2_{i}' for i in range(1, 14)]], metrics_df], axis=1)
    
    if os.path.exists(input_csv):
        os.remove(input_csv)
        
    return final_row

def main():
    parser = argparse.ArgumentParser(description="Matrix Model Evaluator")
    parser.add_argument("--models", help="Directory containing the .RData model files")
    parser.add_argument("--biomass", help="CSV file mapping GEC to Biomass weights")
    parser.add_argument("--cloud", action="store_true", help="Use default /mnt/kokua-data mounted paths for Cloud Run")
    parser.add_argument("--rscript", default="../Context/forestmatrixmodel/MATRIX_simulation_vectorized.R", help="Path to MATRIX_simulation.R")
    parser.add_argument("--project", default="cameltrain", help="GCP project")
    parser.add_argument("--run-id", required=True, help="Unique identifier for this evaluation run to track in BigQuery")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--test", action="store_true", help="Evaluate the Test set")
    group.add_argument("--val", action="store_true", help="Evaluate the Validation set")
    parser.add_argument("--workers", type=int, default=4, help="Max parallel workers for local evaluation (reduce to avoid OOM)")
    parser.add_argument("--filter", default="", help="Custom SQL filter clause")
    parser.add_argument("--map_name", default="", help="Custom task map blob name")
    args = parser.parse_args()
    
    if args.cloud:
        if not args.models:
            args.models = "/mnt/kokua-data/Forest/Matrix/model"
        if not args.biomass:
            args.biomass = "/mnt/kokua-data/Forest/Matrix/model/FT_biomass_kg_0227_Mitra.csv"
            
    if not args.models or not args.biomass:
        parser.error("You must explicitly specify --models and --biomass, or run with the --cloud flag to use the standard Cloud Run mounted paths.")
        
    # Cloud Run Array Job parallelization context
    task_index = int(os.environ.get("CLOUD_RUN_TASK_INDEX", 0))
    task_count = int(os.environ.get("CLOUD_RUN_TASK_COUNT", 1))
    
    print(f"Starting Evaluation Chunk {task_index + 1} of {task_count}")
    
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
        
    # 1. Load task mapping from Google Cloud Storage (Cache File approach)
    from google.cloud import storage
    import json
    
    bucket_name = "matrix_model"
    if args.map_name:
        blob_path = f"eval_worker_task_mapping/{args.map_name}"
    else:
        blob_path = f"eval_worker_task_mapping/{split_name}_task_map_{task_count}.json"
    
    assigned_ft = None
    sub_task_index = 0
    tasks_for_ft = 1
    
    print(f"Checking for task map at gs://{bucket_name}/{blob_path}...")
    try:
        storage_client = storage.Client(project=args.project)
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(blob_path)
        content = blob.download_as_string()
        mapping = json.loads(content)
        
        task_info = mapping.get(str(task_index))
        if task_info:
            assigned_ft = task_info['assigned_ft']
            tasks_for_ft = task_info['tasks_for_ft']
            sub_task_index = task_info['sub_task_index']
            print(f"Loaded task map from GCS! Task {task_index} assigned to Forest Type {assigned_ft} (SubTask {sub_task_index+1} / {tasks_for_ft})")
        else:
            print(f"No task info for index {task_index} in GCS map. Falling back...")
            
    except Exception as e:
        print(f"Could not load task_map from GCS ({e}). Falling back to live BigQuery counting...")

    if assigned_ft is None:
        cnt_query = f"""
            SELECT FT, COUNT(DISTINCT ID) as cnt
            FROM `cameltrain.Forest_MATRIX.fia_grid_3km_eval`
            WHERE 1=1 {filter_clause}
            GROUP BY FT
            ORDER BY cnt DESC
        """
        df_cnt = client.query(cnt_query).to_dataframe()
        total_plots = df_cnt['cnt'].sum()
        
        df_cnt['cum_plots'] = df_cnt['cnt'].cumsum() / total_plots
        
        task_fraction = task_index / task_count
        
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

        print(f"Fallback assignment: Task {task_index} assigned to Forest Type {assigned_ft} (SubTask {sub_task_index+1} / {tasks_for_ft})")

    query = f"""
        SELECT *
        FROM `cameltrain.Forest_MATRIX.fia_grid_3km_eval`
        WHERE FT = {assigned_ft}
        AND MOD(ABS(FARM_FINGERPRINT(CAST(ID AS STRING))), {tasks_for_ft}) = {sub_task_index}
        {filter_clause}
        ORDER BY ID
    """
    
    print("Executing parameterized BigQuery slice...")
    df = client.query(query).to_dataframe()
    if df.empty:
        print("No evaluation plots assigned to this chunk. Exiting gracefully.")
        return
        
    print(f"Loaded {len(df)} plots for evaluation. Grouping by simulation intervals (dY).")
    
    # The R simulation script expects an integer number of years for the loop. 
    # The FIA data 'dY' is originally float (e.g. 5.1). Round to nearest integer.
    df['dY_int'] = df['dY'].round().astype(int)
    # Give all rows a dummy ChunkID=1 so legacy un-vectorized R script passes its validation
    df['ChunkID'] = 1 
    # Provide a legacy CONTINENT flag structurally so the R script passes its array chunk validation seamlessly
    df['CONTINENT'] = 'NAmerica'
    
    # Pre-configure output directory
    out_dir = f"/tmp/simulation_outputs_task_{task_index}"
    os.makedirs(out_dir, exist_ok=True)
    
    all_metrics = []
    dy_groups = list(df.groupby('dY_int'))
    
    if not args.cloud:
        print(f"Running locally! Executing unique dY groups in parallel using {args.workers} workers limit.")
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = [executor.submit(simulate_group, dy_val, group, task_index, args, out_dir) for dy_val, group in dy_groups]
            for future in futures:
                result = future.result()
                if result is not None:
                    all_metrics.append(result)
    else:
        chunk_size = 50
        print(f"Running in Cloud Run! Executing dY groups sequentially with chunk_size={chunk_size} plots.")
        for dy_val, group in dy_groups:
            if dy_val <= 0: continue
            
            chunk_results = []
            # Split group into chunks of 50 plots to avoid R session memory leaks over thousands of predictions
            for i, start_idx in enumerate(range(0, len(group), chunk_size)):
                sub_group = group.iloc[start_idx:start_idx+chunk_size]
                res = simulate_group(dy_val, sub_group, task_index, args, out_dir, chunk_id=i)
                if res is not None:
                    chunk_results.append(res)
            
            if chunk_results:
                all_metrics.append(pd.concat(chunk_results))
        
    if all_metrics:
        final_eval = pd.concat(all_metrics, ignore_index=True)
        # Summarize the average evaluation across all tested coordinates in this chunk
        print("\n===========================================")
        print(f"Evaluation Metrics Summary (Task {task_index})")
        print(f"Analyzed {len(final_eval)} Plot Transitions")
        print("-------------------------------------------")
        print(f"Median Array RMSE:   {final_eval['RMSE'].median():.4f} (Avg: {final_eval['RMSE'].mean():.4f})")
        print(f"Median Cosine Sim:   {final_eval['Cosine_Sim'].median():.4f} (Avg: {final_eval['Cosine_Sim'].mean():.4f})")
        print(f"Total Net Bias TPH:  {final_eval['Density_Diff'].sum():.2f}")
        print("===========================================\\n")
        
        # Optionally, write completion payload JSONs or push directly to a BQ tracking table.
        # Add run metadata for tracking
        final_eval.insert(0, 'run_id', args.run_id)
        final_eval.insert(1, 'dataset_split', split_name)
        final_eval['evaluation_timestamp'] = pd.Timestamp.utcnow()
        
        final_eval.to_csv(f"final_eval_metrics_task_{task_index}.csv", index=False)
        print("Saved raw row-level comparison metrics locally.")
        
        # Upload directly to BigQuery
        table_id = f"{args.project}.Forest_MATRIX.forest_matrix_fia_runs"
        print(f"Uploading evaluation metrics to BigQuery: {table_id}")
        
        job_config = bigquery.LoadJobConfig(
            write_disposition="WRITE_APPEND",
            # Auto-detect schema if the table doesn't exist
            autodetect=True,
        )
        
        load_job = client.load_table_from_dataframe(final_eval, table_id, job_config=job_config)
        load_job.result()  # Wait for the job to complete
        
        print(f"Successfully appended {len(final_eval)} rows to {table_id}")

if __name__ == "__main__":
    try:
        main()
    finally:
        print("Cleaning up temporary evaluation data...")
        for tmp_dir in glob.glob("/tmp/simulation_outputs_task_*"):
            shutil.rmtree(tmp_dir, ignore_errors=True)
        for tmp_csv in glob.glob("/tmp/eval_input_tmp_*.csv"):
            try:
                os.remove(tmp_csv)
            except OSError:
                pass
