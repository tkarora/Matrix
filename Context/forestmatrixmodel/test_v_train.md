# Training vs. Simulation Framework Differences

The core difference between the **Training** runs and the **Simulation** workflows lies in their purpose within the modeling pipeline: **Training** learns the rules of how trees grow and die using historical reality, while **Simulation** applies those rules to forecast identical 3km patches across the globe into the future.

Here is a breakdown of their primary differences:

### 1. Goal and Output
*   **Training (`MATRIX_training_public.R`):** The goal is to build machine learning models representing actual biological transition logic for upgrowth ($p_i$), stasis ($q_i$), mortality ($m_i$), and fecundity ($f_i$). By observing historical data (trees standing vs upgrowing vs dying), it tunes and exports continent-specific Random Forest binary files (`.RData`).
*   **Simulation (`matrix_simulation.R`):** The goal is to project future forest carbon, demographics, and states. It ingests the final trained `.RData` files and calculates annual stand adjustments over a sequence, ultimately producing timeline CSVs containing annual biomass predictions and exact structural DBH states over `X` years.

### 2. Time Operations
*   **Training:** It is retrospective. It looks at the single difference gap between `PrevDBH` (at $time=t$) and `DBH` (at $time=t+\Delta t$). There is no temporal looping here—it purely trains the models to estimate the growth rate dynamically given the interval.
*   **Simulation:** It is sequential and forward-looking. It starts with an initial grid state, applies the loaded Matrix predictions to calculate transitions, applies those increments to update the living trees in memory, and then loops again—progressing step-by-step for the specified forecast duration (`dY` years, defaulting to 25).

### 3. Spatial Scope and the "Input Data"
*   **Training:** Runs exclusively on **plot-level tree lists**. It requires massive CSVs filled with ground-truth census data (such as the US FIA and global GFBI sets), containing individual `TreeID` boundaries, and specific `Status` tracking markers from field scientists.
*   **Simulation:** Runs on a continuous, synthesized **3km spatial grid**. Instead of individual trees, it deals with "Trees Per Hectare" density estimates loaded across geographic arrays. It applies the models against uniform 3x3 km geographic cells globally.

### 4. Computational Demands
*   **Training:** Typically a one-time intensive statistical procedure involving Random Forest hyperparameter grid searches (`ntree`, `mtry`), heavy memory requirements for sub-sampling million-tree records across different environmental dimensions, and building split logic.
*   **Simulation:** An embarrassingly parallel, arrayed High-Performance Computing (HPC) operation. As shown by the CLI instructions in the README, it’s meant to be dispatched in massive arrays across compute clusters (like SLURM) in "chunks" to quickly transition millions of grid locations simultaneously.

## Summary

| Feature | Training (`MATRIX_training_public.R`) | Simulation (`matrix_simulation.R`) |
| :--- | :--- | :--- |
| **Primary Goal** | Tune mathematical machine learning models | Track population transitions step-by-step over decades |
| **Target Output** | Continent-specific `.RData` files | CSVs containing annual biomass and DBH distributions |
| **Input Data Scale** | Plot-level historical truths (Individual Trees) | Worldwide 3x3 km aggregation matrix |
| **Time Operations** | Retrospective analysis | Sequential forward loops |
| **Compute Profile** | Heavy memory single-batch node operations | Massively parallelized array splitting (SLURM) |
