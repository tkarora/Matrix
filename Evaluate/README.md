# MATRIX Evaluation Framework

This module contains the end-to-end framework for evaluating trained `.RData` Forest Matrix models. The pipeline is designed to execute against millions of longitudinal survey plots natively on Google Cloud by leveraging massive parallelization across BigQuery and Cloud Run Array Jobs.

## High-Level Execution Plan

Because the core model simulation is written in native R (`MATRIX_simulation_vectorized.R`), we structure the evaluation system to prepare massive chunks of validation data cleanly inside BigQuery, and then slice those datasets identically into hundreds of serverless containers. Each container invokes the native R logic as a rapid subprocess and parses the pure mathematical errors across the resulting array populations.

**The Pipeline Flow**:
1. **Data Preprocessing**: Aggregate tree-level training records into plot-level DBH structural arrays using BigQuery.
2. **Horizontal Simulation Logging (Cloud Run)**: Query chunked fractions of data locally, call `Rscript MATRIX_simulation_vectorized.R` directly on them to step populations forward $dY$ years, and extract the generated distributions.
3. **Metric Calculation**: Compare predicted vs. ground-truth actual arrays utilizing `scikit-learn` (Vector RMSE, MAE) and `scipy` (Cosine Similarity), automatically appending the analytics per-plot back to the BigQuery tracking table `cameltrain.Forest_MATRIX.forest_matrix_fia_runs` under an explicit `--run-id`.

---

## Train, Validation, and Test Split Strategy

In order to rigorously evaluate the matrix models for predicting forest demography into the future across varying geographies, we partition longitudinal plot transitions into three distinct datasets: **Train**, **Validation**, and **Test**.

### Rationale and Methodology
Because the FIA dataset contains multiple temporal measurements for identically located plots, a purely random 80/20 data split is insufficient. A random fractional split would indiscriminately leak both temporal and spatial data, potentially placing future measurements in the training set and historical measurements in the test set.

To mathematically guarantee causality and rigorously assess geographic generalization, we employ a **Spatiotemporal 3-Way Split**:
1. **Spatial Test Set (Out-of-Geography Generalization)**: A random ~20% of unique physical plots are entirely withheld prior to any temporal sampling. This is achieved using cryptographic hashing securely linked to the official FIA plot identifiers (`STATECD, UNITCD, COUNTYCD, PLOT`). This tests the model's true geographic generalization by evaluating predictions over "out-of-area" unseen forests.
2. **Temporal Validation Set (Out-of-Time Forecasting)**: For the 80% remaining "in-sample" training pool, the **single most recent (last)** measurement transition for each unique location is actively pulled from the timeline and pushed into the validation set. This cleanly evaluates the model's capability for chronologically forecasting a geographically known location without violating causality. 
3. **Training Set**: All previous, historical measurement transitions belonging to the 80% in-sample pool. Any plots possessing only a single chronological transition automatically skip validation to maximize total geographic locations in the training matrix.

### Accessing the Split Datasets
The datasets are provisioned directly in BigQuery by executing `python Evaluate/train_test_split.py`. The script dynamically joins the longitudinal `fia_matrix_training_base` tree records with the static `fia_grid3km_covariates` layer to organically form the unified splits:
- **Train (80% Historical)**: `cameltrain.Forest_MATRIX.fia_matrix_train_set`
- **Val (80% Future)**: `cameltrain.Forest_MATRIX.fia_matrix_val_set`
- **Test (20% Holdout)**: `cameltrain.Forest_MATRIX.fia_matrix_test_set`

---

## `data_prep_eval.py` 

This script is the first critical step of the pipeline. In order to evaluate if the Matrix model correctly transitioned the population density matrix $state_t \to state_{t+\Delta t}$, we must organically construct the ground truth arrays for the bounds matching exactly what the simulation loop produces (`DBH1` to `DBH13`).

### Core Logic
The script dynamically creates an optimized SQL Common Table Expression (CTE) targeting two distinct data structures:

1. **Native Demographic Binning**: Initially, the query parses the raw individual tree observation table `cameltrain.Forest_MATRIX.fia_matrix_training_base`. Because we need *plot-level* distributions, it organically applies dynamic `SUM(CASE WHEN DBH...)` loops grouped intimately around physical layout tracking keys (`PlotID`, `STATECD`, `UNITCD`, `COUNTYCD`, `PLOT`, `YR`). This funnels the weight `TPH` (Trees per Hectare) of every tree logically into numeric arrays representing:
   - **`DBH1...13`**: The plot's starting density matrix at initial time $t$.
   - **`TRUE_TPH2_1...13`**: The natively re-measured (Ground Truth) outcome matrix after the $dY$ measurement interval elapses.

2. **Geographic Nearest-Neighbor Append**: Once clustered into pure array histograms, the CTE cleanly executes exactly ONE horizontal `JOIN` strictly onto the standalone `cameltrain.Forest_MATRIX.fia_grid3km_covariates` master table. Rather than manually copying 100+ structural properties via heavy `MAX()` operations, the script executes an optimized `SELECT g.* EXCEPT(...)`. This structurally forces the 19 Bioclim arrays, Soil/Topography grids, and exactly the 38 required `GEZ_label*` Region Dummy Variables to seamlessly pass backward into the resulting dataset.

The output tightly materializes inside `cameltrain.Forest_MATRIX.fia_grid_3km_eval`. This provides exactly what the underlying structural Simulation code strictly expects (`DBH1`, one-hot coordinates, environmental variants) and what the external Python Python Evaluator mathematically leverages as its scoring truth (`TRUE_TPH2_`).

### Filtering Missing DBH Values (Periodic Inventory Legacy)

To prevent runtime crashes in the R simulation (which panics on `NA` values), we filter out evaluation plots that contain `NULL` values in any of the 13 DBH classes (either at the initial state or ground truth).

*   **Total Plots Dropped:** 156 (out of 561,952, or $< 0.03\%$).
*   **Root Cause:** The `NULL` weights are legacy artifacts from the transition between **Periodic Inventories** (unstandardized, state-specific surveys pre-2005) and modern **Annual Inventories** (standardized nationwide). 
*   **Regional Concentration:** The drops are heavily clustered in the Southeastern US (Georgia, Florida, Carolinas), where legacy periodic cycles extended into the 2000s.

#### Top Regional/Temporal Distribution of Drops

| Year | State Code | State Name | Dropped Plots |
| :--- | :--- | :--- | :--- |
| 1980 | 12 | Florida | 7 |
| 1986 | 45 | South Carolina | 6 |
| 1979 | 12 | Florida | 5 |
| 1969 | 12 | Florida | 4 |

This filtering is intentional and safe, as it prevents pipeline crashes without skewing regional metrics (loss is $< 0.03\%$). 

*Source: For details on the Periodic-to-Annual transition and data quality implications, consult the [FIADB User Guide](https://apps.fs.usda.gov/fia/datamart/datamart.html).*

---

## Task Sharding Anatomy (`generate_task_map.py`)
To evaluate forest types efficiently without loading all model files into every container, we use a **proportional task mapping** strategy instead of random modulo-based sharding. Since some forest types are far more prevalent than others, this script guarantees that worker compute is spent proportionally where the data resides.

The `generate_task_map.py` script executes the following workflow:

1. **Calculate Density**: It scans the un-vectorized evaluation table `fia_grid_3km_eval` and counts the distinct rows per `FT` (Forest Type).
2. **Assign Shares Proportional to Weight**: It splits the total task pool (e.g. 100 workers) proportionally based on the cumulative distribution of plots.
3. **Map Work with sub-indexes**: For each task index, it saves `assigned_ft`, `tasks_for_ft` (how many workers share this FT), and `sub_task_index` (the 0-indexed worker counter for this FT).
4. **Persist to GCS**: It uploads a JSON file to `gs://[BUCKET]/eval_worker_task_mapping/{split}_task_map_{workers}.json`.

The Cloud Run tasks pull this JSON during boot to find their exact assignments instantly and skip BigQuery heavy scans!

### Usage

Run this script prior to Cloud Run job execution to seed the GCS bucket task map cache (The `Makefile` will attempt to auto-execute this for you):

```bash
uv run python generate_task_map.py --bucket="matrix_model" --test --tasks 100
```

Flags:
- `--test` / `--val`: Specifies the respective evaluation data subset.
- `--tasks`: The total number of tasks your Cloud Run job is configured to run.

---

## `evaluate_model.py`

This script orchestrates the R-based matrix models locally while leaning entirely on massive parallelization via Cloud Run Array Jobs against BigQuery.

### Dynamic Holdout Splitting
Rather than duplicating the enormous plot-level array histograms (`DBH1..13`) into three separate physical tables for training, validation, and testing, `evaluate_model.py` dynamically subsets the monolithic pre-aggregated `fia_grid_3km_eval` table directly at runtime.

By appending the mutual exclusive flags `--test` or `--val`, the orchestrator natively injects a lightning-fast subquery (e.g., `WHERE ID IN (SELECT DISTINCT PlotID FROM fia_matrix_test_set)`) into the BigQuery `FROM` clause. This allows us to rapidly re-evaluate out-of-time (Val) and out-of-geography (Test) model deployments over identically processed arrays, preventing any redundant data prep. 

**Execution Configuration Flags (`--cloud`)**: The code handles dynamic mounting paths. You can execute the script locally with standard file paths by passing `--models /local/path` and `--biomass /local/path.csv`. When deploying directly to GCP, you can omit physical pathing and append `--cloud` instead. The orchestrator will intrinsically switch parsing bounds to the container's remote volume storage points (`/mnt/kokua-data/Forest/Matrix/...`).

### Memory and Scaling Optimizations

To handle heavy `R` simulation runs without exceeding the 16GiB memory limits on Cloud Run (scaled up from 8GiB to accommodate heavy Random Forest weights), we employ two distinct optimization strategies:

#### 1. Proportional Task Mapping (by Forest Type)
Instead of a random modulo-based split across all forest types, we use `generate_task_map.py` to create a deterministic mapping of Cloud Run tasks to specific Forest Types (FT).
- **How it works**: A JSON map tells each Cloud Run task which FT to process and how many other workers are sharing that FT.
- **Benefit**: Each worker container only loads the `.RData` model files for its assigned FT, reducing baseline memory consumption. Heavy FTs are automatically allocated more workers proportionally.

#### 2. Sequential Subprocess Chunking (Inner-Task Splits)
For the heaviest Forest Types (e.g., FT 2 Oak/Hickory), even a single FT subset of plots can cause memory to build up over thousands of sequential `predict()` calls in R. 
- **Benefit**: We slice the task's assigned plots into smaller chunks (e.g., 50 plots) and invoke the R script sequentially per chunk. This forces the R process to terminate and reset its memory space between chunks.
- **Garbage Collection**: We also added explicit `gc()` (Garbage Collection) calls inside the R simulation loop to aggressively reclaim memory between plot steps, keeping usage flat and far below the 16GiB limit without modifying legacy model weights.

#### 3. Vectorized Simulation Engine (Matrix Mathematics)
We refactored the simulation engine (`MATRIX_simulation_vectorized.R`) to use group-by matrix algebra instead of row-by-row loops in R.
- **How it works**: Plots with the same simulation interval ($\Delta t$) are grouped together, and transition matrices are applied to all plots simultaneously.
- **Why it is faster**: Standard R Random Forest predictions call compiled C code. Passing 1 plot at a time incurrs a heavy context-switching overhead between R and C for *every single plot*. By passing an entire dataframe of plots in one call, we eliminate thousands of inter-language handshakes, delegating the loop to the ultra-fast compiled C layer!
- **Empirical Evidence**: We ran a controlled sequential benchmark of 100 plots to compare the vectorized engine against the legacy baseline:

| Metric | Vectorized Engine | Legacy Engine | Improvement |
| :--- | :--- | :--- | :--- |
| **Execution Time** | **146 seconds** | 337 seconds | **~2.3x Speedup** |
| **Median Array RMSE** | 208.3926 | 208.4113 | Parity |
| **Median Cosine Sim** | 0.8704 | 0.8714 | Parity |

Combined with resource downsizing (reducing from 32GiB to 16GiB), this yields a projected **~4.5x total cost reduction** for production runs.


### Execution 

To natively integrate parallel computation, scale horizontally across hundreds of VM instances, and mount external model weights directly from our big data object storage without ballooning the container disk size, this pipeline runs natively as a Google Cloud Run Job. The logic concurrently effortlessly supports identical localized evaluation.

We've constructed a unified `Makefile` to securely orchestrate this complexity for you! 

#### Local Evaluation
Execute the evaluation directly on your machine's R installation seamlessly by pointing natively to your local datasets (configured dynamically in the `Makefile` paths `LOCAL_MODELS_DIR` and `LOCAL_BIOMASS`).

```bash
# Evaluate out-of-geography generalization
make eval-local-test

# Evaluate out-of-time forecasting
make eval-local-val

# Evaluate overall system aggregate
make eval-local-full
```

#### Cloud Run Evaluation (Native Array Jobs)
When executing the job on Google Cloud, the pipeline actively leverages the Generation-2 Execution Environment to natively mount the `kokua-data` Google Cloud Storage bucket as a volume drive onto the container (`/mnt/kokua-data`). This entirely skips slow `gcsfuse` container packaging!

#### 4. Read-Only Filesystem & Ephemeral /tmp
Cloud Run Job containers operate on a read-only filesystem by default outside of the ephemeral `/tmp` space.
- **Ephemeral Isolation**: The python orchestrator writes task CSVs and logs strictly into `/tmp`.
- **Lockfile Isolation**: The R simulation scripts have been updated to write lockfiles (to prevent concurrent write collisions) and output CSV caches into `/tmp` as well to prevent silent failures.

**1. Build and Propagate**:
First, build the Docker target (it natively reaches back to the repo root to bundle `../Context` safely) and push it to Google Container Registry:
```bash
make docker-build
```

**2. Deploy and Execute Array**:
Deploy and map instances safely across 100 nodes targeting the respective holdout splits! This explicitly spins the exact `gcloud run jobs create` logic natively bound to `--add-volume=name=kokua-data`:
```bash
# Deploys configurations natively isolating the subsets
make deploy-cloud-test
make deploy-cloud-val
make deploy-cloud-full

# Execute the specific tracked array job
make execute-cloud-test
```

The evaluator scripts will dynamically execute the default vectorized logic, parse the respective dimensional prediction bins, calculated metrics per-plot, and append them straight back into BigQuery's `cameltrain.Forest_MATRIX.forest_matrix_fia_runs`. 

#### Targeted Recovery Runs

If a run fails to complete 100% of the plots (e.g., due to isolated worker crashes or sharding gaps), you can execute a targeted recovery run to process ONLY the missing plots and append them to the same `run_id`.

1. **Generate a Recovery Task Map**:
   Run `generate_task_map.py` with a filter targeting missing plots:
   ```bash
   uv run python3 generate_task_map.py \
     --bucket="matrix_model" \
     --tasks=200 \
     --output_name="recovery_task_map_200.json" \
     --filter="AND ID NOT IN (SELECT DISTINCT ID FROM \`cameltrain.Forest_MATRIX.forest_matrix_fia_runs\` WHERE run_id = 'YOUR_RUN_ID')"
   ```

2. **Execute the Recovery Run**:
   Execute the Cloud Run job passing the custom map and filter:
   ```bash
   gcloud run jobs execute matrix-eval-full-split \
     --tasks=200 \
     --args="--run-id=YOUR_RUN_ID,--map_name=recovery_task_map_200.json,--filter=AND ID NOT IN (SELECT DISTINCT ID FROM \`cameltrain.Forest_MATRIX.forest_matrix_fia_runs\` WHERE run_id = 'YOUR_RUN_ID')"
   ```

---

## 📈 Comparing Model Error to Input Quality

We have provisioned a dedicated guide for querying the BigQuery tables to attribute errors to input resolution (e.g., plot distance to grid centers).

See **[EvalAnalysisGuide.md](file:///usr/local/google/home/tkarora/Matrix/Evaluate/EvalAnalysisGuide.md)** for:
- Global Median Plot Distance queries.
- Pearson Correlation Coefficient queries between RMSE and distance.
