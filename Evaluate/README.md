# MATRIX Evaluation Framework

This module contains the end-to-end framework for evaluating trained `.RData` Forest Matrix models. The pipeline is designed to execute against millions of longitudinal survey plots natively on Google Cloud by leveraging massive parallelization across BigQuery and Cloud Run Array Jobs.

## High-Level Execution Plan

Because the core model simulation is written in native R (`MATRIX_simulation.R`), we structure the evaluation system to prepare massive chunks of validation data cleanly inside BigQuery, and then slice those datasets identically into hundreds of serverless containers. Each container invokes the native R logic as a rapid subprocess and parses the pure mathematical errors across the resulting array populations.

**The Pipeline Flow**:
1. **Data Preprocessing**: Aggregate tree-level training records into plot-level DBH structural arrays using BigQuery.
2. **Horizontal Simulation Logging (Cloud Run)**: Query chunked fractions of data locally, call `Rscript MATRIX_simulation.R` directly on them to step populations forward $dY$ years, and extract the generated distributions.
3. **Metric Calculation**: Compare predicted vs. ground-truth actual arrays utilizing `scikit-learn` (Vector RMSE, MAE) and `scipy` (Cosine Similarity), automatically appending the analytics per-plot back to the BigQuery tracking table `cameltrain.Forest_MATRIX.forest_matrix_fia_runs` under an explicit `--run-id`.

---

## Train, Validation, and Test Split Strategy

In order to rigorously evaluate the matrix models for predicting forest demography into the future across varying geographies, we partition longitudinal plot transitions into three distinct datasets: **Train**, **Validation**, and **Test**.

### Rationale and Methodology
Because the FIA dataset contains multiple temporal measurements for identically located plots, a purely random 80/20 data split is insufficient. A random fractional split would indiscriminately leak both temporal and spatial data, potentially placing future measurements in the training set and historical measurements in the test set.

To mathematically guarantee causality and rigorously assess geographic generalization, we employ a **Spatiotemporal 3-Way Split**:
1. **Spatial Test Set (Out-of-Geography Generalization)**: A random ~20% of unique plots (`PlotID`s) are entirely withheld prior to any temporal sampling. This is achieved using cryptographic hashing securely linked to the PlotID. This tests the model's true geographic generalization by evaluating predictions over "out-of-area" unseen forests.
2. **Temporal Validation Set (Out-of-Time Forecasting)**: For the 80% remaining "in-sample" training pool, the **single most recent (last)** measurement transition for each plot is actively pulled from the timeline and pushed into the validation set. This cleanly evaluates the model's capability for chronologically forecasting a geographically known location without violating causality. 
3. **Training Set**: All previous, historical measurement transitions belonging to the 80% in-sample pool. Any plots possessing only a single chronological transition automatically skip validation to maximize total geographic locations in the training matrix.

### Accessing the Split Datasets
The datasets are provisioned directly in BigQuery by executing `python Evaluate/train_test_split.py`. They explicitly branch off from the raw `fia_matrix_training_grid3km_cov` base table:
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

---

## `evaluate_model.py` (Pending Execution Validation)
_Detailed documentation of the orchestrator subprocess mechanics, chunking formulas via `$CLOUD_RUN_TASK_INDEX`, and terminal containerization logic will be added here once the system conducts a successful Cloud Run Array Job test!_
