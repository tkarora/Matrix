#!/usr/bin/env Rscript
# =============================================================================
# VECTORIZED MATRIX SIMULATION
# -----------------------------------------------------------------------------
# Translates the serial plot-by-plot loop into matrix algebra.
# Processes all plots in a chunk simultaneously for each year.
# =============================================================================

suppressPackageStartupMessages({
  library(randomForest)
  library(stringr)
})

# ----------------------------- CLI PARSING -----------------------------------
args <- commandArgs(trailingOnly = TRUE)

get_flag <- function(flag, default = NULL) {
  hit <- grep(paste0("^", flag, "="), args, value = TRUE)
  if (length(hit) == 0) return(default)
  sub(paste0("^", flag, "="), "", hit[1])
}

get_bool <- function(flag, default = FALSE) {
  val <- tolower(get_flag(flag, ifelse(default, "true", "false")))
  val %in% c("1","true","t","yes","y")
}

mode         <- toupper(get_flag("--mode", "GLOBAL_GEC"))
input_csv    <- get_flag("--input")
models_dir   <- get_flag("--models")
biomass_csv  <- get_flag("--biomass")
out_dir      <- get_flag("--out_dir")
clim         <- toupper(get_flag("--clim", "CC"))
years        <- as.integer(get_flag("--years", "25"))
cont_filter  <- get_flag("--continent", "")
bioclim_csv  <- get_flag("--bioclim", "")
out_prefix   <- get_flag("--out_prefix", ifelse(mode == "NA_FT", "glob3km_nam_25y", "glob3km_onehot_25y"))
lock_prefix  <- paste0(".lock_", out_prefix, "_")
quiet        <- get_bool("--quiet", FALSE)

if (is.null(input_csv) || is.null(models_dir) || is.null(biomass_csv) || is.null(out_dir)) {
  stop("Missing required flags.")
}

message_if <- function(...) { if (!quiet) message(...) }

message_if("--- R Script Initialization ---")
message_if(sprintf("Working Dir: %s", getwd()))
message_if(sprintf("Input CSV: %s", input_csv))
message_if(sprintf("Models Dir: %s", models_dir))
message_if(sprintf("Out Dir: %s", out_dir))
message_if(sprintf("Args: %s", paste(args, collapse=" ")))

if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)


# ------------------------- SLURM/CLI INDEX HANDLING --------------------------
get_array_index <- function() {
  sid <- Sys.getenv("SLURM_ARRAY_TASK_ID", unset = NA)
  if (!is.na(sid) && nzchar(sid)) return(as.integer(sid))
  io <- suppressWarnings(as.integer(args[1]))
  if (!is.na(io)) return(io)
  NA_integer_
}

io <- get_array_index()

# ----------------------------- LOAD DATA -------------------------------------
dat <- read.csv(input_csv, check.names = FALSE)
dat$dY <- years

if (nzchar(cont_filter)) {
  keep <- dat$CONTINENT == cont_filter
  dat <- dat[keep, , drop = FALSE]
  if (nrow(dat) == 0) stop("No rows left after filtering.")
}

bioclim <- if (nzchar(bioclim_csv) && file.exists(bioclim_csv)) read.csv(bioclim_csv, check.names = FALSE) else NULL
biomass_df <- read.csv(biomass_csv, check.names = FALSE)

# ----------------------------- HELPERS ---------------------------------------
DBH_vec <- c(12.93003, 17.28223, 22.25088, 27.31658, 32.29727, 37.24331, 42.30573,
             47.27999, 52.22731, 57.30927, 62.43174, 67.25792, 90.29815)

res <- NULL

load_models <- function(mode, models_dir, FT = NULL, CONT = NULL) {
  if (mode == "NA_FT") {
    load(file.path(models_dir, sprintf("RF.UG.0503.ft.%s.RData", FT))); RF_up <- RF
    load(file.path(models_dir, sprintf("RF.RC.0426.ft.%s.RData", FT))); RF_rc <- RF
    load(file.path(models_dir, sprintf("RF.MT.0425.ft.%s.RData", FT))); RF_mt <- RF
    return(list(up = RF_up, rc = RF_rc, mt = RF_mt, key = paste0("FT", FT), key_type = "FT"))
  } else {
    up_f <- list.files(models_dir, pattern = paste0("^RF\\.UG\\..*", CONT, "\\.RData$"), full.names = TRUE)[1]
    rc_f <- list.files(models_dir, pattern = paste0("^RF\\.RC\\..*", CONT, "\\.RData$"), full.names = TRUE)[1]
    mt_f <- list.files(models_dir, pattern = paste0("^RF\\.MT\\..*", CONT, "\\.RData$"), full.names = TRUE)[1]
    load(up_f); RF_up <- RF
    load(rc_f); RF_rc <- RF
    load(mt_f); RF_mt <- RF
    return(list(up = RF_up, rc = RF_rc, mt = RF_mt, key = "GEC", key_type = "GEC"))
  }
}

MATRIX_sim_func_vectorized <- function(mode, models_dir, abund_matrix, cov_matrix, DBH_vec, bioclim,
                                      CONT, FT, clim, res, biomass_df) {
  cat("-----Vectorized Simulation Starts-----\n")
  nplot <- nrow(cov_matrix)
  dY    <- max(cov_matrix$dY)
  
  # Output columns
  out_cols <- c("ID","LAT","LON","GEC","FT","CONT","Year","B","N","S1","S2",
                paste0("TPH1_", 1:13),
                paste0("TPH2_", 1:13),
                paste0(rep(c("Y","AGB","UP","RC","MT"), times = dY), rep(1:dY, each = 5)))
  
  plt_vec_out <- matrix(NA, nrow = nplot, ncol = length(out_cols))
  colnames(plt_vec_out) <- out_cols
  
  Y_t1 <- as.matrix(abund_matrix) # N x 13
  plt_vec0 <- Y_t1 # Save initial state
  
  # Diversity helpers
  calc_div <- function(Y) {
    N <- rowSums(Y)
    N[N == 0] <- 1 # avoid div by zero
    pi <- Y / N
    pi[pi == 0] <- NA # log(0) is NA, handled below
    Shannon <- pi * log(pi); Shannon[is.na(Shannon)] <- 0
    Simpson <- pi^2;         Simpson[is.na(Simpson)] <- 0
    list(S1 = -rowSums(Shannon), S2 = rowSums(Simpson), N = N)
  }
  
  # Load models once for the entire group (assuming one FT/CONT for this execution chunk)
  if (mode == "NA_FT") {
    mdl <- load_models("NA_FT", models_dir, FT = FT, CONT = NULL)
  } else {
    mdl <- load_models("GLOBAL_GEC", models_dir, FT = NULL, CONT = CONT)
  }
  
  if (mdl$key_type == "FT") {
    bvec <- as.numeric(biomass_df[[paste0("FT", FT)]])
  } else {
    bvec <- as.numeric(biomass_df[[CONT]]) # Approximation
  }
  
  annual_metrics <- list()
  
  for (m in seq_len(dY)) {
    year <- 1999 + m
    
    # Update plot-level state variables
    div_out <- calc_div(Y_t1)
    cov_matrix$N <- rowSums(Y_t1)
    cov_matrix$B <- rowSums(Y_t1 * matrix(DBH_vec^2 / 40000 * 3.14, nrow = nplot, ncol = 13, byrow = TRUE))
    cov_matrix$S1 <- div_out$S1
    cov_matrix$S2 <- div_out$S2
    
    # Climate (Constant for now in this simplification, adapt if time-varying is needed)
    cond_m <- cov_matrix 
    
    # 1. Predict Recruitment
    rc_pred <- pmax(0, predict(mdl$rc, cond_m, type = "response")) # nplot length
    
    # 2. Predict Up-growth and Mortality (Need expanded D-dataframe)
    expanded_indices <- rep(seq_len(nplot), each = 13)
    expanded_cov <- cond_m[expanded_indices, , drop = FALSE]
    expanded_cov$D <- rep(DBH_vec, times = nplot)
    
    up_all <- pmax(0, predict(mdl$up, expanded_cov, type = "response") / 5)
    up_matrix <- matrix(up_all, nrow = nplot, ncol = 13, byrow = TRUE)
    up_matrix[, 13] <- 0 # Class 13 cannot up-grow
    
    mt_all <- pmax(0, predict(mdl$mt, expanded_cov, type = "response"))
    mt_matrix <- matrix(mt_all, nrow = nplot, ncol = 13, byrow = TRUE)
    
    # 3. Apply Matrix Algebra
    a_matrix <- pmax(0, 1 - up_matrix - mt_matrix) # Stasis probabilities
    
    stasis <- Y_t1 * a_matrix
    up_growth <- cbind(0, (Y_t1 * up_matrix)[, -13, drop = FALSE])
    
    Y_t2 <- stasis + up_growth
    Y_t2[, 1] <- Y_t2[, 1] + rc_pred
    
    # Non-negativity
    Y_t2[Y_t2 < 0] <- 0
    Y_t2[rowSums(Y_t2) == 0, 1] <- 1 # Avoid extinction
    
    # Biomass Accounting
    # bvec is 13 length. Y_t1 is N x 13.
    # sweep is fast for matrix x vector multiplication
    AGB_t1 <- rowSums(sweep(Y_t1, 2, bvec, "*")) / 1000
    AGB_t2 <- rowSums(sweep(Y_t2, 2, bvec, "*")) / 1000
    
    biomass_up <- (rowSums(sweep(up_growth, 2, bvec, "*")) - rowSums(Y_t1 * up_matrix * matrix(bvec, nrow = nplot, ncol = 13, byrow = TRUE))) / 1000
    biomass_rc <- rc_pred * bvec[1] / 1000
    biomass_mt <- rowSums(Y_t1 * mt_matrix * matrix(bvec, nrow = nplot, ncol = 13, byrow = TRUE)) / 1000
    
    annual_metrics[[m]] <- list(
      AGB = AGB_t2,
      UP  = biomass_up,
      RC  = biomass_rc,
      MT  = biomass_mt
    )
    
    Y_t1 <- Y_t2 # Next state
    gc(verbose = FALSE) # Force garbage collection to prevent memory leaks from predict()
  }
  
  # Fill Output Matrix
  plt_vec_out[, "ID"]   <- cov_matrix$ID
  plt_vec_out[, "LAT"]  <- cov_matrix$LAT
  plt_vec_out[, "LON"]  <- cov_matrix$LON
  plt_vec_out[, "GEC"]  <- cov_matrix$GEC
  plt_vec_out[, "FT"]   <- cov_matrix$FT
  plt_vec_out[, "CONT"] <- cov_matrix$CONTINENT
  plt_vec_out[, "Year"] <- dY
  
  div_final <- calc_div(Y_t1)
  plt_vec_out[, "B"]  <- rowSums(Y_t1 * matrix(DBH_vec^2 / 40000 * 3.14, nrow = nplot, ncol = 13, byrow = TRUE))
  plt_vec_out[, "N"]  <- div_final$N
  plt_vec_out[, "S1"] <- div_final$S1
  plt_vec_out[, "S2"] <- div_final$S2
  
  # TPH1 and TPH2
  for (j in 1:13) {
    plt_vec_out[, paste0("TPH1_", j)] <- plt_vec0[, j]
    plt_vec_out[, paste0("TPH2_", j)] <- Y_t1[, j]
  }
  
  # Annuals
  for (m in seq_len(dY)) {
    plt_vec_out[, paste0("Y", m)]   <- m
    plt_vec_out[, paste0("AGB", m)] <- annual_metrics[[m]]$AGB
    plt_vec_out[, paste0("UP", m)]  <- annual_metrics[[m]]$UP
    plt_vec_out[, paste0("RC", m)]  <- annual_metrics[[m]]$RC
    plt_vec_out[, paste0("MT", m)]  <- annual_metrics[[m]]$MT
  }
  
  cat("-----Vectorized Simulation Ends-----\n")
  plt_vec_out
}

`%||%` <- function(a, b) if (!is.null(a) && !is.na(a)) a else b

# Process all rows in the input CSV (Python handles sharding)
df <- dat
ChunkID <- 1 # Hardcoded for output file naming compatibility with evaluate_model.py
final_out <- file.path(out_dir, sprintf("%s_%d.csv", out_prefix, ChunkID))
CONT <- unique(df$CONTINENT)

abund_matrix <- df[, paste0("DBH", 1:13), drop = FALSE]
cov_matrix   <- df[, setdiff(colnames(df), colnames(abund_matrix)), drop = FALSE]

out_df <- MATRIX_sim_func_vectorized(
  mode         = mode,
  models_dir   = models_dir,
  abund_matrix = abund_matrix,
  cov_matrix   = cov_matrix,
  DBH_vec      = DBH_vec,
  bioclim      = bioclim,
  CONT         = CONT,
  FT           = if ("FT" %in% names(df)) unique(df$FT)[1] else NA,
  clim         = clim,
  res          = res,
  biomass_df   = biomass_df
)

tmp_out <- paste0(final_out, ".tmp_", Sys.getpid())
write.csv(out_df, tmp_out, row.names = FALSE)
file.rename(tmp_out, final_out)

message_if("Done.")
