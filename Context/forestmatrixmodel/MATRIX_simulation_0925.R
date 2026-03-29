#!/usr/bin/env Rscript
# =============================================================================
# MATRIX SIMULATION (Unified)
# -----------------------------------------------------------------------------
# Author: Jingjing Liang (albeca.liang@gmail.com)
# Public shareable script that unifies two internal workflows:
#   1) North America (forest type models; FT-based biomass vectors)
#   2) Other continents (ecozone models; GEC-based biomass vectors)
#
# Key updates reflected:
# - Biomass component; up/rc/mt tracking in both biomass and TPH by DBH
# - Deterministic core with optional residual "res" noise by CONT
# - 20–25 year runs; annual AGB (total, up, rc, mt)
# - Per-chunk execution with SLURM array index or CLI index
# - “Missing output discovery” (only compute missing chunks)
# - One-hot model compatibility (2025-04-05)
# - Use constant or time-varying climate inputs; bioclim optional
# - NA_FT: model files keyed by FT; biomass vectors keyed by FT
# - GLOBAL_GEC: model files keyed by CONT; biomass vectors keyed by GEC
# =============================================================================

suppressPackageStartupMessages({
  library(randomForest)
  library(stringr)
})

# ----------------------------- CLI PARSING -----------------------------------
args <- commandArgs(trailingOnly = TRUE)

get_flag <- function(flag, default = NULL) {
  # accepts flags like --input=..., --out_dir=...
  hit <- grep(paste0("^", flag, "="), args, value = TRUE)
  if (length(hit) == 0) return(default)
  sub(paste0("^", flag, "="), "", hit[1])
}

get_bool <- function(flag, default = FALSE) {
  val <- tolower(get_flag(flag, ifelse(default, "true", "false")))
  val %in% c("1","true","t","yes","y")
}

# Required / optional flags
mode         <- toupper(get_flag("--mode", "GLOBAL_GEC"))  # "NA_FT" or "GLOBAL_GEC"
input_csv    <- get_flag("--input")   # e.g., /path/Grid3km_cov_Dvec_OneHot_500Chunk_0405.csv
models_dir   <- get_flag("--models")  # e.g., /scratch/.../models/
biomass_csv  <- get_flag("--biomass") # NA_FT: FT_biomass_kg_0227_Mitra.csv; GLOBAL_GEC: AGB_by_GEZ_compiled_0228.csv
out_dir      <- get_flag("--out_dir") # e.g., /scratch/.../25y_0820
clim         <- toupper(get_flag("--clim", "CC"))  # CC, RCP45, RCP85
years        <- as.integer(get_flag("--years", "25"))
cont_filter  <- get_flag("--continent", "")       # optional filter, e.g. "NAmerica"
bioclim_csv  <- get_flag("--bioclim", "")         # optional: annual bioclim table; if absent -> constant climate
out_prefix   <- get_flag("--out_prefix", ifelse(mode == "NA_FT", "glob3km_nam_25y", "glob3km_onehot_25y"))
lock_prefix  <- paste0(".lock_", out_prefix, "_")
quiet        <- get_bool("--quiet", FALSE)

if (is.null(input_csv) || is.null(models_dir) || is.null(biomass_csv) || is.null(out_dir)) {
  stop("Missing required flags. Use --input=..., --models=..., --biomass=..., --out_dir=..., and optionally --mode=NA_FT|GLOBAL_GEC, --clim=CC|RCP45|RCP85, --years=25, --continent=NAmerica, --bioclim=CSV, --out_prefix=NAME.")
}

if (!dir.exists(out_dir)) dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

message_if <- function(...) { if (!quiet) message(...) }

# ------------------------- SLURM/CLI INDEX HANDLING --------------------------
get_array_index <- function() {
  sid <- Sys.getenv("SLURM_ARRAY_TASK_ID", unset = NA)
  if (!is.na(sid) && nzchar(sid)) return(as.integer(sid))
  # Fallback to commandArgs
  io <- suppressWarnings(as.integer(args[1]))
  if (!is.na(io)) return(io)
  NA_integer_
}

io <- get_array_index()

# ----------------------------- LOAD DATA -------------------------------------
dat <- read.csv(input_csv, check.names = FALSE)
dat$dY <- years

# Optional continent filter (useful if you ship one big CSV)
if (nzchar(cont_filter)) {
  keep <- dat$CONTINENT == cont_filter
  dat <- dat[keep, , drop = FALSE]
  if (nrow(dat) == 0) stop(sprintf("No rows left after filtering CONTINENT == '%s'.", cont_filter))
}

# Bioclim (optional). If not given, use constant climate from cov_matrix.
bioclim <- if (nzchar(bioclim_csv) && file.exists(bioclim_csv)) read.csv(bioclim_csv, check.names = FALSE) else NULL

# Biomass conversion vectors
biomass_df <- read.csv(biomass_csv, check.names = FALSE)

# ----------------------------- HELPERS ---------------------------------------
DBH_vec <- c(12.93003, 17.28223, 22.25088, 27.31658, 32.29727, 37.24331, 42.30573,
             47.27999, 52.22731, 57.30927, 62.43174, 67.25792, 90.29815)

# minimal residual structure; set to NULL unless you provide one with a CONT column
res <- NULL

# ----------------------------- MODEL LOADING ---------------------------------
load_models <- function(mode, models_dir, FT = NULL, CONT = NULL) {
  if (mode == "NA_FT") {
    if (is.null(FT)) stop("NA_FT mode requires FT.")
    # Exact filenames by FT (from original NA script)
    load(file.path(models_dir, sprintf("RF.UG.0503.ft.%s.RData", FT))); RF_up <- RF
    load(file.path(models_dir, sprintf("RF.RC.0426.ft.%s.RData", FT))); RF_rc <- RF
    load(file.path(models_dir, sprintf("RF.MT.0425.ft.%s.RData", FT))); RF_mt <- RF
    return(list(up = RF_up, rc = RF_rc, mt = RF_mt, key = paste0("FT", FT), key_type = "FT"))
  } else {
    if (is.null(CONT)) stop("GLOBAL_GEC mode requires CONT.")
    # First match by CONT (from original global script)
    up_f <- list.files(models_dir, pattern = paste0("^RF\\.UG\\..*", CONT, "\\.RData$"), full.names = TRUE)[1]
    rc_f <- list.files(models_dir, pattern = paste0("^RF\\.RC\\..*", CONT, "\\.RData$"), full.names = TRUE)[1]
    mt_f <- list.files(models_dir, pattern = paste0("^RF\\.MT\\..*", CONT, "\\.RData$"), full.names = TRUE)[1]
    if (any(is.na(c(up_f, rc_f, mt_f)) | !file.exists(c(up_f, rc_f, mt_f)))) {
      stop(sprintf("Cannot find model files for CONT='%s' in %s.", CONT, models_dir))
    }
    load(up_f); RF_up <- RF
    load(rc_f); RF_rc <- RF
    load(mt_f); RF_mt <- RF
    return(list(up = RF_up, rc = RF_rc, mt = RF_mt, key = "GEC", key_type = "GEC"))
  }
}

# ---------------------------- CORE SIMULATOR ---------------------------------
MATRIX_sim_func <- function(mode, models_dir, abund_matrix, cov_matrix, DBH_vec, bioclim,
                            CONT, FT, clim, res, biomass_df) {
  cat("-----Simulation Starts-----\n")
  nplot <- nrow(cov_matrix)
  dY    <- max(cov_matrix$dY)
  
  # Output columns (superset, includes LAT/LON/GEC/FT for maximal compatibility)
  out_cols <- c("ID","LAT","LON","GEC","FT","CONT","Year","B","N","S1","S2",
                paste0("TPH1_", 1:13),
                paste0("TPH2_", 1:13),
                paste0(rep(c("Y","AGB","UP","RC","MT"), times = dY), rep(1:dY, each = 5)))
  
  plt_vec_out <- matrix(NA, nrow = nplot, ncol = length(out_cols))
  colnames(plt_vec_out) <- out_cols
  
  # Diversity (S1/S2) for initial condition rows
  X  <- abund_matrix
  N0 <- rowSums(X)
  pi <- X / N0
  Shannon <- pi * log(pi); Shannon[is.na(Shannon)] <- 0
  Simpson <- pi^2;         Simpson[is.na(Simpson)] <- 0
  cov_matrix$S1 <- -rowSums(Shannon)
  cov_matrix$S2 <-  rowSums(Simpson)
  
  bioclim_cols <- paste0("C", 1:21)
  bioclim_s1   <- paste0("C", 1:21, "S1")
  bioclim_s2   <- paste0("C", 1:21, "S2")
  
  clim_df <- switch(clim,
                    CC    = cov_matrix[, bioclim_cols, drop = FALSE],
                    RCP45 = cov_matrix[, bioclim_s1,   drop = FALSE],
                    RCP85 = cov_matrix[, bioclim_s2,   drop = FALSE],
                    stop("clim must be CC, RCP45, or RCP85"))
  dClim <- (clim_df - cov_matrix[, bioclim_cols, drop = FALSE]) / 50
  
  bioclim_df <- if (is.null(bioclim)) cov_matrix else bioclim[cov_matrix$ID, , drop = FALSE]
  
  for (n in seq_len(nplot)) {
    # Determine model set and biomass key for this row
    cond <- cov_matrix[n, , drop = FALSE]
    if (mode == "NA_FT") {
      mdl <- load_models("NA_FT", models_dir, FT = cond$FT, CONT = NULL)
    } else {
      mdl <- load_models("GLOBAL_GEC", models_dir, FT = NULL, CONT = CONT)
    }
    
    # Initial state
    plt_vec  <- as.numeric(abund_matrix[n, ])
    plt_vec0 <- plt_vec
    # avoid all-zero (log/div-by-zero issues)
    if (sum(plt_vec) == 0) plt_vec[1] <- 1
    
    # Biomass conversion vector selection
    if (mdl$key_type == "FT") {
      bvec <- biomass_df[[paste0("FT", cond$FT)]]
    } else {
      bvec <- biomass_df[[cond$GEC]]
    }
    if (is.null(bvec)) stop("Biomass vector not found for row ", n, " (check FT/GEC and biomass_csv).")
    
    start_time <- Sys.time()
    annual_out_df <- 0  # will cbind YR, AGB, AGB_up, AGB_rc, AGB_mt (per year)
    
    for (m in seq_len(cond$dY)) {
      if (m > 1) plt_vec <- plt_vec1
      
      year <- 1999 + m
      cond$N <- sum(plt_vec)
      cond$B <- sum(plt_vec * (DBH_vec^2 / 40000) * 3.14)
      
      pi <- plt_vec / cond$N
      Shannon <- pi * log(pi); Shannon[is.na(Shannon)] <- 0
      Simpson <- pi^2;         Simpson[is.na(Simpson)] <- 0
      cond$S1 <- -sum(Shannon)
      cond$S2 <-  sum(Simpson)
      
      # Climate for this year
      cond_m <- if (is.null(bioclim)) {
        # keep as-is (constant climate already in cov_matrix)
        cond
      } else {
        bioclim_vec <- bioclim_df[n, , drop = FALSE]
        yr_attr     <- grepl(year, names(bioclim_vec))
        bioclim_year <- bioclim_vec[, yr_attr, drop = FALSE]
        names(bioclim_year) <- c(paste0("C", seq_len(ncol(bioclim_df)))[1:19], "C21", "C20")
        cbind(cond, bioclim_year)
      }
      
      # Predictions
      rc_pred <- pmax(0, predict(mdl$rc, cond_m, type = "response"))
      up_vec  <- pmax(0, predict(mdl$up, cbind(D = DBH_vec, cond_m), type = "response") / 5)
      up_vec[13] <- 0
      mt_vec  <- pmax(0, predict(mdl$mt, cbind(D = DBH_vec, cond_m), type = "response"))
      
      # Matrix update
      Y_t1   <- plt_vec
      b      <- up_vec
      a      <- 1 - b - mt_vec
      up     <- c(0, (Y_t1 * b)[-length(b)])
      stasis <- Y_t1 * a
      Y_t2   <- stasis + up
      Y_t2[1] <- Y_t2[1] + rc_pred
      plt_vec1 <- Y_t2
      
      # Optional residuals by CONT
      if (!is.null(res)) {
        res1 <- res[res$CONT == CONT, , drop = FALSE]
        if (nrow(res1) == 0) res1 <- res
        res1 <- res1[, -1, drop = FALSE]  # drop CONT col
        res_vec <- if (is.null(nrow(res1)) || nrow(res1) == 0) 0 else res1[sample(nrow(res1), 1), , drop = FALSE]
        plt_vec1 <- as.numeric(plt_vec1) + as.numeric(res_vec)
      }
      
      # Non-negativity & keep a small-tree seed to avoid NAs later
      plt_vec1[plt_vec1 < 0] <- 0
      if (sum(plt_vec1) == 0) plt_vec1[1] <- 1
      
      # Biomass accounting (Mg/ha)
      biomass_up <- sum(up * bvec) / 1000 - sum((Y_t1 * up_vec) * bvec) / 1000
      biomass_rc <- rc_pred * bvec[1] / 1000
      biomass_mt <- sum((Y_t1 * mt_vec) * bvec) / 1000
      
      AGB    <- sum(plt_vec1 * bvec) / 1000
      AGB_up <- biomass_up
      AGB_rc <- biomass_rc
      AGB_mt <- biomass_mt
      YR     <- m
      
      annual_out_df <- cbind.data.frame(annual_out_df, YR, AGB, AGB_up, AGB_rc, AGB_mt)
    }
    
    annual_out_df <- annual_out_df[, -1, drop = FALSE]
    names(annual_out_df) <- NULL
    annual_out <- as.numeric(annual_out_df)
    
    # Final stand-level metrics
    B_final <- sum(plt_vec1 * (DBH_vec^2 / 40000) * 3.14)
    N_final <- sum(plt_vec1)
    pi <- plt_vec1 / N_final
    Shannon <- pi * log(pi); Shannon[is.na(Shannon)] <- 0
    Simpson <- pi^2;         Simpson[is.na(Simpson)] <- 0
    S1_final <- -sum(Shannon)
    S2_final <-  sum(Simpson)
    
    # Compose one row (fill columns that exist in data; NA otherwise)
    row_vals <- list(
      ID   = cond$ID %||% NA,
      LAT  = cond$LAT %||% NA,
      LON  = cond$LON %||% NA,
      GEC  = cond$GEC %||% NA,
      FT   = cond$FT  %||% NA,
      CONT = cond$CONTINENT %||% cond$CONT %||% NA,
      Year = cond$dY %||% dY,
      B    = B_final,
      N    = N_final,
      S1   = S1_final,
      S2   = S2_final
    )
    
    # Helper to safely coalesce
    to_vec <- function(x, k = 13) {
      v <- as.numeric(x)
      if (length(v) != k) {
        len <- length(v); out <- rep(NA_real_, k); out[seq_len(min(k, len))] <- v[seq_len(min(k, len))]; return(out)
      }
      v
    }
    
    # Ensure TPH1_/TPH2_ are formed from initial/final states
    TPH1 <- to_vec(plt_vec0, 13)
    TPH2 <- to_vec(plt_vec1, 13)
    
    full_row <- c(
      unlist(row_vals, use.names = FALSE),
      TPH1,
      TPH2,
      annual_out
    )
    
    plt_vec_out[n, ] <- full_row
    
    elapsed <- Sys.time() - start_time
    cat(sprintf("--Plot# %d of %d -- N=%.1f -- CONT=%s -- time=%s\n",
                n, nplot, N_final, as.character(row_vals$CONT), as.character(elapsed)))
  }
  
  cat("-----Simulation ends-----\n")
  plt_vec_out
}

`%||%` <- function(a, b) if (!is.null(a) && !is.na(a)) a else b

# ----------------------- DISCOVER MISSING CHUNKS ------------------------------
# Expect a column "ChunkID" in input table
if (!"ChunkID" %in% names(dat)) stop("Input CSV must contain a 'ChunkID' column.")

N_blocks <- sort(unique(dat$ChunkID))

# Existing outputs
pattern <- paste0("^", out_prefix, "_\\d+\\.csv$")
files   <- list.files(out_dir, pattern = pattern, full.names = FALSE)
have_ids <- suppressWarnings(as.numeric(str_extract(files, paste0("(?<=", out_prefix, "_)\\d+(?=\\.csv)"))))
missing_chunks <- sort(setdiff(N_blocks, have_ids))

if (length(missing_chunks) == 0) {
  message_if("Nothing to do: all chunks present.")
  quit(save = "no", status = 0)
}

if (is.na(io) || io < 1 || io > length(missing_chunks)) {
  stop(sprintf("Provide a valid array index (1..%d) via SLURM_ARRAY_TASK_ID or CLI.", length(missing_chunks)))
}

ChunkID <- missing_chunks[io]
message_if(sprintf("Task %d processing missing ChunkID = %d", io, ChunkID))

# ------------------------------- LOCKING -------------------------------------
lockfile  <- file.path(out_dir, sprintf("%s%d", lock_prefix, ChunkID))
final_out <- file.path(out_dir, sprintf("%s_%d.csv", out_prefix, ChunkID))

if (!file.create(lockfile)) {
  message_if("Another task is already working on this chunk; exiting.")
  quit(save = "no", status = 0)
}
on.exit({ if (file.exists(lockfile)) file.remove(lockfile) }, add = TRUE)

if (file.exists(final_out)) {
  message_if("Output already exists; nothing to do.")
  quit(save = "no", status = 0)
}

# ---------------------------- PREPARE THIS CHUNK -----------------------------
df <- dat[dat$ChunkID == ChunkID, , drop = FALSE]
CONT <- unique(df$CONTINENT)
if (length(CONT) != 1) stop("Expected a single CONTINENT per ChunkID.")

abund_matrix <- df[, paste0("DBH", 1:13), drop = FALSE]
cov_matrix   <- df[, setdiff(colnames(df), colnames(abund_matrix)), drop = FALSE]

# ------------------------------- RUN -----------------------------------------
out_df <- MATRIX_sim_func(
  mode        = mode,
  models_dir  = models_dir,
  abund_matrix = abund_matrix,
  cov_matrix   = cov_matrix,
  DBH_vec      = DBH_vec,
  bioclim      = if (exists("bioclim")) bioclim else NULL,
  CONT         = CONT,
  FT           = if ("FT" %in% names(df)) unique(df$FT)[1] else NA,
  clim         = clim,
  res          = res,
  biomass_df   = biomass_df
)

# ----------------------------- ATOMIC WRITE ----------------------------------
tmp_out <- paste0(final_out, ".tmp_", Sys.getpid())
write.csv(out_df, tmp_out, row.names = FALSE)
if (!file.rename(tmp_out, final_out)) {
  file.copy(tmp_out, final_out, overwrite = TRUE)
  file.remove(tmp_out)
}
message_if("Done.")

# --------------------------------- USAGE -------------------------------------
# Examples:
# 1) GLOBAL mode (GEC biomass, models by CONT), constant climate:
# Rscript matrix_simulation.R \
#   --mode=GLOBAL_GEC \
#   --input=/scratch/gautschi/liang292/Grid3km_cov_Dvec_OneHot_500Chunk_0405.csv \
#   --models=/scratch/gautschi/liang292/models \
#   --biomass=/scratch/gautschi/liang292/AGB_by_GEZ_compiled_0228.csv \
#   --out_dir=/scratch/gautschi/liang292/25y_0820 \
#   --clim=CC --years=25 --continent=Africa --out_prefix=glob3km_onehot_25y
#
# 2) NA_FT mode (FT biomass, FT-specific model files):
# Rscript matrix_simulation.R \
#   --mode=NA_FT \
#   --input=/scratch/gautschi/liang292/Grid3km_cov_Dvec_OneHot_500Chunk_0411.csv \
#   --models=/scratch/gautschi/liang292/models \
#   --biomass=/scratch/gautschi/liang292/FT_biomass_kg_0227_Mitra.csv \
#   --out_dir=/scratch/gautschi/liang292/25y_0820 \
#   --clim=CC --years=25 --continent=NAmerica --out_prefix=glob3km_nam_25y
#
# Notes:
# - Provide SLURM_ARRAY_TASK_ID for parallel arrays, or pass a 1-based index
#   as the first CLI arg to target which missing chunk to run.
# - Output schema includes LAT/LON/GEC/FT columns when available.
# - To enable residual noise, provide a 'res' table with a 'CONT' column and
#   one column per DBH class residual. Otherwise it's deterministic.
# =============================================================================
