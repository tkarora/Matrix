# Implementation Breakdown: Matrix Model Training Algorithm

The training algorithm implementation in `MATRIX_training_public.R` is designed to learn parameterizing functions for the population density matrix described in `matrix_model.pdf`. Rather than using simple, fixed transition rates for mortality ($m_i$), stasis ($q_i$), upgrowth ($p_i$), and fecundity/recruitment ($f_i$), the code trains **three non-linear, density-dependent Random Forest (RF) models** to predict vital rates based on a comprehensive suite of geographic, environmental, and stand-level variables. 

These models are trained per continent and are subsequently fed into the forward recurrence relationship simulation (`matrix_simulation.R` discussed in the `README.md`) using $O = UN$. Every step of the simulation progresses time sequentially by 1 year.

Here is a step-by-step breakdown of how the training workflow processes data to learn these probabilities.

---

## 1. Initial Data Processing & Plot-Level Attributes

The algorithm starts by injesting global "tree-list" data and preparing the covariates for every stand (plot). 

According to the demographic Matrix, transitions depend heavily on the stand's current density and tree-size biodiversity. Given plot measurements, the code groups individual trees into DBH (Diameter at Breast Height) classes (initially using a 5-cm bin from 5cm and up) to compute structure attributes.

**Inputs:**
- Raw tree list dataset: `"GFB3_globe_step4_0721.csv"`
- Key specific columns mapping tree state at `time = t`:
  - `PlotID`, `PrevDBH`, `TPH` (Trees Per Hectare representation for that observation)

**Code Snippet:**
```R
# Plot basal area and total number of trees
B <- tapply(
  3.14 * ifelse(is.na(dat$PrevDBH), 0, dat$PrevDBH)^2 / 40000 * dat$TPH,
  dat$PlotID, sum
)

# Shannon and Simpson size-diversity indices
pi_mat <- X / N_plot
ln_pi       <- log(pi_mat)
```

**Outputs of this section:**
- `B`: Total basal area of the plot
- `N`: Total number of trees in the plot 
- `S1`: Shannon diversity index of size classes
- `S2`: Simpson diversity index of size classes

---

## 2. Covariate Extraction (`cov_func2`)

For each unique plot coordinate (`LAT`, `LON`), the framework maps geographic data to about ~40+ predictors. This matches what `matrix_simulation.R` demands (`C1-C21`, etc.).

Missing covariates are imputed using the geographically nearest plot's valid records.

**Outputs:**
- `C1-C21`: 19 Bioclimatic layers (Bio1-Bio19) + Aridity Index + Potential Evapotranspiration
- `O1-O5`: Soil metrics (Bulk density, pH, Electrical Conductivity, C/N, Total Nitrogen) 
- `H1-H4`: Anthropogenic impacts (Human footprint, its change, Roadless blocks, Protected areas)
- `T1-T12`: Global Topographic factors (slope, aspect, etc.)
- `GEZ`: Global Ecological Zones
- `CONTINENT`: Continent identifier

---

## 3. The Upgrowth Model (UG)

This model handles the probability and rate of transition to the next state ($p_i$ and $q_i$). Specifically, it maps to the **Diameter Increment** (`dD`).

**Target Output ($Y$):** `dD`
Here, `dD` represents the **annualized diameter increment**. In the input dataset, this is pre-calculated as the measured growth between the survey periods divided by the time interval. The resulting model predicts the diameter increment expected over a **single year**.
During forecasting (`matrix_simulation.R`), this model's prediction is called sequentially at the end of *every* simulated year to iteratively progress the state vector $O = UN$. 

**Inputs:** 
- Filtered tree list (`flag_dD == "FALSE"`)
- All plot-level and environmental covariates (the `C`, `O`, `H`, `T` vectors + `B`, `N`, `S1`, `S2`)
- The individual tree's diameter (`D` which was `PrevDBH`)
- Uses one-hot encoded permutations for global ecozones (`GEZ`).

**Code Snippet:**
```R
train_df <- dat_ug[, !colnames(dat_ug) %in% attr_remove]
names(train_df)[names(train_df) == "PrevDBH"] <- "D"
Mod <- "UG"
Y   <- "dD"

# One-hot encode GEZ by continent
df1 <- train_df %>%
  mutate(GEZ_label = paste(CONTINENT, GEZ, sep = "_")) %>% ...
```

---

## 4. The Mortality Model (MT)

This model learns the rate at which trees leave the alive classes ($m_i$). Rather than determining this randomly per tree, reality shows mortality occurs at steady rates. The algorithm computes a composite annual mortality rate per plot across **individual 2-cm DBH classes**. 

**Target Output ($Y$):** `M`
`M` represents the **annual probability** of mortality within a specific DBH class in a specific plot. It calculates `(Total Dead TPH / Total Living TPH) / census_interval_years`. 

**Inputs:**
- Total dead trees per DBH class in a plot (`Xm`) 
- Total living trees in that DBH class (`X_all`)
- Time interval between census: `dY_plot`

**Code Snippet:**
```R
# Mortality matrix by DBH class (2cm groups)
Xm <- tapply(ifelse(dat_mt$M == 1, dat_mt$TPH, 0), list(dat_mt$PlotID, dat_mt$D_GP), sum)
X_all <- tapply(dat_mt$TPH, list(dat_mt$PlotID, dat_mt$D_GP), sum)

AnnualMort <- Xm / X_all
AnnualMort <- sweep(AnnualMort, 1, dY_plot, `/`)
```

---

## 5. The Recruitment Model (RC)

This corresponds to the vector $R$ / Fecundity factors $f_i$ outlined in the PDF. Matrix demography models add newly recruited saplings into the first diameter class state using this term. 

The minimum DBH threshold to be classified as a measured sapling is assumed to be 10 cm. The predictor computes recruitment at the **plot-aggregate-level**, determining the total flux of trees breaching the 10cm threshold dynamically over the time interval.

**Target Output ($Y$):** `R` 
`R` is the **annual ingrowth rate** measured in `TPH / year` plot-wide. 

**Inputs:** 
- Filter condition `D < 10 & DBH >= 10`: Trees that stepped over the 10cm threshold exactly in the bounds of the census time `dY`.
- Plot-level metrics (`LAT`, `LON`, `B`, `N`, `S1`, `S2`, plus `C`, `O`, `H`, `T` covariates)
- *(Note: Variables that define individual trees are stripped out here since recruitment deals in stand totals)*

**Code Snippet:**
```R
# Plot-level recruitment (threshold 10 cm DBH)
R <- tapply(
  ifelse(df1$D < 10 & df1$DBH >= 10, df1$TPH / df1$dY, 0),
  df1$PlotID, sum
)
dat_rc <- cbind.data.frame(LAT, LON, B, N, S1, S2, R)
```

> [!TIP]
> **Validating the Recruitment Threshold in BigQuery (FIA Data)**
> 
> The requirement states that we must validate this assumption for the FIA dataset present in `cameltrain.Forest_MATRIX.fia_matrix_training_grid3km_cov`. The US FIA standard protocol divides tree measurements where trees 5.0+ inches DBH are surveyed on the subplot, and 1.0 - 4.9 inches are surveyed on the microplot. We can validate the crossing of the growth threshold by tracking trees that started below a specific DBH in the previous census and are above it in the current census.
> 
> You can run the following SQL snippet in the BigQuery console to inspect these precise recruited events:
> 
> ```sql
> SELECT 
>   COUNT(*) AS total_recruited_events,
>   SUM(tpa_unadj) AS total_recruited_tpa,
>   AVG(tpa_unadj / remper) AS avg_annual_recruitment_tpa
> FROM `cameltrain.Forest_MATRIX.fia_matrix_training_grid3km_cov`
> WHERE prev_dia < 5.0 AND dia >= 5.0 -- Change 5.0 to corresponding 10cm or 12.7cm equivalent depending on table units
> ```
> This validates the logic used in the Matrix Training where only the trees breaching the target bin are scaled into plot-level annualized rates.

---

## 6. Training Regimen & Hyperparameter Tuning (`MATRIX_RF_func`)

Once each dataframe above is assembled, it filters by Continent `CONT` and calls `MATRIX_RF_func` on them iteratively.
To prevent overfitting while tackling dense forestry data, the code tunes Random Forest limits programmatically using Root Mean Squared Error evaluation.

1. **Subsampling:** Uses maximum 1000 items as the validation set logic. Splits them roughly 50% (Train/Test).
2. **Grid Search Iteration:** Loops over variations of `ntree` (10 to 200), `nodesize` (1 to 5), and `mtry` (1 to 5). Repeats the ensemble loops `n = 10` times.
3. Finds best row configurations minimizing the mean Test `RMSE`.
4. Trains the final `randomForest` model against the **entire continent dataset** with the winning `ntree`, `nodesize`, and `mtry`.
5. Outputs metrics to `RF_<Mod>_summary_<date>.csv` and writes `.RData` binary models exactly identical to how `matrix_simulation.R` loads them.
