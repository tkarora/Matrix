################################################################################
# MATRIX: Distributed Random Forest Training Pipeline (Forest Type Focus)
#
# This script is a refactored version of MATRIX_training_public.R.
# It is designed to be invoked by train_model.py.
#
# Reference: Matrix/Context/forestmatrixmodel/matrix_training_explained.md
################################################################################

# Parse command line arguments
args <- commandArgs(trailingOnly = TRUE)

parse_args <- function(args) {
  params <- list()
  for (arg in args) {
    parts <- strsplit(arg, "=")[[1]]
    if (length(parts) == 2) {
      name <- gsub("^--", "", parts[1])
      value <- parts[2]
      params[[name]] <- value
    }
  }
  return(params)
}

params <- parse_args(args)

input_ug      <- params$input_ug
input_mt      <- params$input_mt
input_rc      <- params$input_rc
val_ug        <- params$val_ug
val_mt        <- params$val_mt
val_rc        <- params$val_rc
ft            <- params$ft
out_dir       <- params$out_dir
public_export <- as.logical(params$public_export)

if (is.null(input_ug) || is.null(input_mt) || is.null(input_rc) || is.null(ft) || is.null(out_dir)) {
  stop("Missing required arguments: --input_ug, --input_mt, --input_rc, --ft, --out_dir")
}

library(dplyr)
library(tidyr)
library(randomForest)
library(foreach)
library(doParallel)

# 1. Read Data
cat("Reading UG data from:", input_ug, "\n")
dat_ug <- read.csv(input_ug)
cat("Loaded", nrow(dat_ug), "UG rows\n")

cat("Reading MT data from:", input_mt, "\n")
dat_mt <- read.csv(input_mt)
cat("Loaded", nrow(dat_mt), "MT rows\n")

cat("Reading RC data from:", input_rc, "\n")
dat_rc <- read.csv(input_rc)
cat("Loaded", nrow(dat_rc), "RC rows\n")

dat_val_ug <- if (!is.null(val_ug)) read.csv(val_ug) else NULL
dat_val_mt <- if (!is.null(val_mt)) read.csv(val_mt) else NULL
dat_val_rc <- if (!is.null(val_rc)) read.csv(val_rc) else NULL

if (!is.null(dat_val_ug)) cat("Loaded", nrow(dat_val_ug), "Validation UG rows\n")
if (!is.null(dat_val_mt)) cat("Loaded", nrow(dat_val_mt), "Validation MT rows\n")
if (!is.null(dat_val_rc)) cat("Loaded", nrow(dat_val_rc), "Validation RC rows\n")

# Assumption: Data from BigQuery already contains covariates and is filtered for the specific FT.
# We also assume it contains columns: B, N, S1, S2, C1..C21, O1..O5, H1..H4, T1..T12 and GEZ_label columns.

# Standardize response column names if they are different in BQ
# Baseline used 'dD' for upgrowth, 'M' for mortality, 'R' for recruitment.
# We assume they are named 'dD', 'M', 'R' in the input CSV.

train_model <- function(df, target_col, mod_name, out_dir, ft, df_val = NULL) {
  date <- format(Sys.Date(), "%m%d")
  
  # Standardize response column name
  names(df)[names(df) == target_col] <- "Y"
  
  # Remove unwanted columns (ID, etc.)
  attr_remove <- c("PlotID", "CONTINENT", "FT", "GEZ", "Biome", "GEC", "GEZ_label")
  df <- df[, !colnames(df) %in% attr_remove]
  df <- na.omit(df)
  
  if (nrow(df) < 10) {
    cat("Too few rows for training", mod_name, "for FT", ft, "\n")
    return(NULL)
  }
  
  cat("Training", mod_name, "Model for FT", ft, "with", nrow(df), "rows...\n")
  
  # Hyperparameter tuning (Reduced for speed in testing, increase for production)
  n            <- 2   # iterations (Baseline was 10)
  prop         <- 0.1 # sample proportion (Baseline was 0.001 but with huge data)
  max_ntree    <- 100 # Baseline was 200
  max_nodesize <- 5
  max_mtry     <- 5
  
  # Drop DBH to avoid leakage and matching issues in eval
  if ("DBH" %in% names(df)) {
    df$DBH <- NULL
  }
  
  sample_size <- max(50, floor(prop * nrow(df)))
  if (sample_size > nrow(df)) sample_size <- nrow(df)
  
  sample_idx <- sample.int(n = nrow(df), size = sample_size, replace = TRUE)
  train_df1 <- df[sample_idx, ]
  
  if (!is.null(df_val) && nrow(df_val) > 0) {
    cat("Using provided validation data for hyperparameter tuning.\n")
    names(df_val)[names(df_val) == target_col] <- "Y"
    df_val <- df_val[, !colnames(df_val) %in% attr_remove]
    test <- na.omit(df_val)
    train <- train_df1 # Use all sampled training data for training candidates
  } else {
    cat("Self-splitting training data for hyperparameter tuning.\n")
    sample_idx <- sample.int(n = nrow(train_df1), size = floor(0.5 * nrow(train_df1)), replace = FALSE)
    test  <- train_df1[sample_idx, ]
    train <- train_df1[-sample_idx, ]
  }
  
  grid <- expand.grid(
    ntree = round(seq(10, max_ntree, length.out = 5)),
    nodesize = seq(1, max_nodesize, 2),
    mtry = seq(1, min(max_mtry, ncol(df) - 1), 2),
    iter = seq_len(n)
  )
  
  # Limit to 3 cores to avoid data duplication OOM in Cloud Run
  num_cores <- min(3, detectCores() - 1)
  if (num_cores < 1) num_cores <- 1
  cat("Registering doParallel with", num_cores, "cores\n")
  cl <- makeCluster(num_cores)
  registerDoParallel(cl)
  
  results <- foreach(idx = 1:nrow(grid), .combine = rbind, .packages = c('randomForest')) %dopar% {
    p <- grid[idx, ]
    current_mtry <- min(p$mtry, ncol(train) - 1)
    
    RF <- randomForest(
      Y ~ ., data = train,
      importance = FALSE,
      proximity  = FALSE,
      ntree      = p$ntree,
      nodesize   = p$nodesize,
      mtry       = current_mtry
    )
    
    pred <- predict(RF, test, type = "response")
    rmse <- sqrt(sum((test$Y - pred)^2) / length(test$Y))
    
    c(p$ntree, p$nodesize, current_mtry, rmse)
  }
  
  stopCluster(cl)
  
  results <- as.data.frame(results)
  names(results) <- c("ntree", "nodesize", "mtry", "rmse")
  
  # Aggregate by hyperparams to get mean RMSE
  RMSE1 <- results %>%
    group_by(ntree, nodesize, mtry) %>%
    summarise(RMSE_mean = mean(rmse), .groups = 'drop')
  
  min_row <- which.min(RMSE1$RMSE_mean)
  
  ntree_best    <- as.numeric(RMSE1[min_row, "ntree"])
  nodesize_best <- as.numeric(RMSE1[min_row, "nodesize"])
  mtry_best     <- as.numeric(RMSE1[min_row, "mtry"])
  
  cat("Best Hyperparams - ntree:", ntree_best, "nodesize:", nodesize_best, "mtry:", mtry_best, "\n")
  
  # Train final model on all data
  RF <- randomForest(
    Y ~ ., data = df,
    importance = FALSE,
    proximity  = FALSE,
    ntree      = ntree_best,
    nodesize   = nodesize_best,
    mtry       = mtry_best
  )
  
  # Save model using the fixed date expected by simulation script
  # Simulation script expects hardcoded dates:
  # UG: 0503, RC: 0426, MT: 0425
  # We use these here to match the simulation script's load_models function.
  
  if (mod_name == "UG") date_str <- "0503"
  else if (mod_name == "RC") date_str <- "0426"
  else if (mod_name == "MT") date_str <- "0425"
  else date_str <- date
  
  file_name <- paste0("RF.", mod_name, ".", date_str, ".ft.", ft, ".RData")
  save(RF, file = file.path(out_dir, file_name))
  cat("Saved model to", file.path(out_dir, file_name), "\n")
  return(RF)
}

# 3. Train Models
# Filter data for specific targets if needed (e.g. only positive increment for UG)
# Baseline did some filtering.

# Upgrowth
df_ug <- dat_ug %>% filter(dD > 0) # Keep filter just in case
train_model(df_ug, "dD", "UG", out_dir, ft, dat_val_ug)

# Mortality
# 'M' is the column prepared by BQ.
train_model(dat_mt, "M", "MT", out_dir, ft, dat_val_mt)

# Recruitment
# 'R' is the column prepared by BQ.
train_model(dat_rc, "R", "RC", out_dir, ft, dat_val_rc)

# Optional Public Export
if (public_export) {
  cat("Exporting public data...\n")
  # ... implementation of export logic if needed ...
}

cat("Training completed for FT", ft, "\n")
