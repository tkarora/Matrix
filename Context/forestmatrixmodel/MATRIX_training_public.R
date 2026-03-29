################################################################################
# MATRIX: Integrated Random Forest Training Pipeline (Global)
#
# Copyright (c) 2025 Jingjing Liang
#
# MIT License
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
################################################################################

#########################
## User Configuration  ##
#########################

# Update these paths for your environment before running:
data_dir       <- "D:/Summer25/MATRIX/data"
covariate_dir  <- "D:/Data/ArcGIS"
model_dir      <- "D:/Summer25/MATRIX/models"

#########################
## Package Imports     ##
#########################

library(dplyr)
library(tidyr)
library(raster)
library(sf)
library(sp)
library(rgeos)
library(reshape2)
library(randomForest)

################################################################################
# Function: cov_func2
#
# Description:
#   Extract ~40 environmental and bioclimatic attributes for plot locations.
#
# Inputs:
#   df  - data.frame with at least columns: LAT, LON
#   dir - directory where covariate GIS data are stored
#
# Output:
#   data.frame with original df columns plus extracted covariates
################################################################################

cov_func2 <- function(df, dir) {
  points_t <- df

  # Convert to spatial object (WGS84)
  coordinates(points_t) <- ~ LON + LAT
  proj4string(points_t) <- sp::CRS("+init=epsg:4326")

  coord_XY <- data.frame(coordinates(points_t))
  names(coord_XY) <- c("LON", "LAT")

  ##############################################################################
  ## Bioclimate covariates
  ##############################################################################
  cat("Processing Bioclimate Covariates...\n")

  for (i in 1:19) {
    raster_path <- file.path(dir, "Bioclimate", paste0("bio_", i, ".bil"))
    if (file.exists(raster_path)) {
      raster_layer <- raster(raster_path)
      C <- raster::extract(x = raster_layer, y = coord_XY, method = "simple", df = TRUE)
      names(C) <- c("ID", paste0("ClimCov_", i))
      points_t[[paste0("C", i)]] <- C[[2]]
    } else {
      cat("  File not found:", raster_path, "\n")
    }
  }

  # Additional covariates (AI_annual and PET_he_annual)
  additional_covariates <- list(
    C20 = file.path(dir, "Bioclimate", "AI_annual", "ai_yr"),
    C21 = file.path(dir, "Bioclimate", "PET_he_annual", "pet_he_yr")
  )

  for (cov_name in names(additional_covariates)) {
    raster_path <- additional_covariates[[cov_name]]
    if (file.exists(raster_path)) {
      raster_layer <- raster(raster_path)
      C <- raster::extract(x = raster_layer, y = coord_XY, method = "simple", df = TRUE)
      names(C) <- c("ID", cov_name)
      points_t[[cov_name]] <- C[[2]]
    } else {
      cat("  File not found:", raster_path, "\n")
    }
  }

  cat("- End Climate Covariates -\n")

  ##############################################################################
  ## Soil covariates
  ##############################################################################
  cat("Processing Soil Covariates...\n")

  raster_layer <- raster(file.path(dir, "wise_30sec_v1", "GISfiles", "wise30sec_fin"))
  C <- raster::extract(x = raster_layer, y = coord_XY, method = "simple", df = TRUE)

  raster.df <- data.frame(raster_layer@data@attributes)
  SoilCodes <- raster.df[match(C[, 2], raster.df[, 2]), 7]

  datasoil <- read.table(
    file.path(dir, "wise_30sec_v1", "Interchangeable_format", "HW30s_FULL.txt"),
    sep = ",", header = TRUE
  )

  O1 <- datasoil[match(SoilCodes, datasoil[, 1]), 20] # Bulk density
  O5 <- datasoil[match(SoilCodes, datasoil[, 1]), 26] # Total Nitrogen
  O4 <- datasoil[match(SoilCodes, datasoil[, 1]), 28] # C/N ratio
  O2 <- datasoil[match(SoilCodes, datasoil[, 1]), 44] # pH in water
  O3 <- datasoil[match(SoilCodes, datasoil[, 1]), 50] # Electrical conductivity (dS/m)

  points_t$O1 <- O1
  points_t$O2 <- O2
  points_t$O3 <- O3
  points_t$O4 <- O4
  points_t$O5 <- O5

  cat("- End Soil Covariates -\n")

  ##############################################################################
  ## Anthropogenic covariates
  ##############################################################################
  cat("Processing Anthropogenic Covariates...\n")

  # Human footprint 2009
  raster_layer <- raster(file.path(dir, "HumFootPrint", "hfp2009"))
  H <- raster::extract(x = raster_layer, y = coord_XY, method = "simple", df = TRUE)
  names(H) <- c("ID", "Anthr")
  points_t$H1 <- H$Anthr

  # Human footprint 1993 (change relative to 2009)
  raster_layer <- raster(file.path(dir, "HumFootPrint", "hfp1993"))
  H2 <- raster::extract(x = raster_layer, y = coord_XY, method = "simple", df = TRUE)
  names(H2) <- c("ID", "Anthr")
  points_t$H2 <- H$Anthr - H2$Anthr

  # Roadless areas
  raster_layer <- raster(file.path(dir, "RoadlessAreas", "roadlesskm2"))
  H <- raster::extract(x = raster_layer, y = coord_XY, method = "simple", df = TRUE)
  names(H) <- c("ID", "Anthr")
  points_t$H3 <- H$Anthr
  points_t$H3[is.na(points_t$H3)] <- 0

  # Protected areas
  raster_layer <- raster(file.path(dir, "ProtectedAreas", "WDPA_ras"))
  H <- raster::extract(x = raster_layer, y = coord_XY, method = "simple", df = TRUE)
  names(H) <- c("ID", "Anthr")
  points_t$H4 <- H$Anthr
  points_t$H4[is.na(points_t$H4)] <- 0

  cat("- End Anthropogenic Covariates -\n")

  ##############################################################################
  ## Topographic covariates
  ##############################################################################
  cat("Processing Topographic Covariates...\n")

  topo_files <- c(
    T1  = "aspectcosine_1KMmn_GMTEDmd.tif",
    T2  = "aspectsine_1KMmn_GMTEDmd.tif",
    T3  = "dx_1KMmn_GMTEDmd.tif",
    T4  = "dxx_1KMmn_GMTEDmd.tif",
    T5  = "dy_1KMmn_GMTEDmd.tif",
    T6  = "dyy_1KMmn_GMTEDmd.tif",
    T7  = "pcurv_1KMmn_GMTEDmd.tif",
    T8  = "roughness_1KMmn_GMTEDmd.tif",
    T9  = "slope_1KMmn_GMTEDmd.tif",
    T10 = "tcurv_1KMmn_GMTEDmd.tif",
    T11 = "tpi_1KMmn_GMTEDmd.tif",
    T12 = "tri_1KMmn_GMTEDmd.tif"
  )

  for (nm in names(topo_files)) {
    raster_path <- file.path(dir, "TopoGlobal", topo_files[[nm]])
    raster_layer <- raster(raster_path)
    C <- raster::extract(x = raster_layer, y = coord_XY, method = "simple", df = TRUE)
    names(C) <- c("ID", "TOPO")
    points_t[[nm]] <- C$TOPO
  }

  cat("- End Topographic Covariates -\n")

  ##############################################################################
  ## Ecoregions (GEZ)
  ##############################################################################
  cat("Processing Ecoregions (GEZ)...\n")

  shapefile_path <- file.path(dir, "GEZ", "gez_2010_wgs84.shp")
  if (file.exists(shapefile_path)) {
    shapefile_layer <- st_read(shapefile_path, quiet = TRUE)
    shapefile_layer <- st_make_valid(shapefile_layer)

    coord_XY_sf <- st_as_sf(coord_XY, coords = c("LON", "LAT"),
                            crs = st_crs(shapefile_layer))
    joined_data <- st_join(coord_XY_sf, shapefile_layer)

    # Keep first 4 columns from GEZ layer (e.g., gez_code, gez_name, etc.)
    points_t <- cbind.data.frame(points_t, st_drop_geometry(joined_data)[, 1:4])
  } else {
    cat("  Shapefile not found:", shapefile_path, "\n")
  }

  cat("- End Ecoregions -\n")

  ##############################################################################
  ## Continents
  ##############################################################################
  cat("Processing Continents...\n")

  shapefile_path <- file.path(dir, "continents", "continent_GFB2.shp")
  if (file.exists(shapefile_path)) {
    shapefile_layer <- st_read(shapefile_path, quiet = TRUE)
    shapefile_layer <- st_make_valid(shapefile_layer)

    coord_XY_sf <- st_as_sf(coord_XY, coords = c("LON", "LAT"),
                            crs = st_crs(shapefile_layer))
    joined_data <- st_join(coord_XY_sf, shapefile_layer)

    points_t <- cbind.data.frame(points_t, st_drop_geometry(joined_data))
  } else {
    cat("  Shapefile not found:", shapefile_path, "\n")
  }

  cat("- End Continents -\n")

  ##############################################################################
  ## Return final data frame
  ##############################################################################
  df_cov <- as.data.frame(points_t)
  return(df_cov)
}

################################################################################
# Function: replace_rows_with_nearest
#
# Description:
#   For rows flagged by NA_flag == 1, replace selected covariate columns with
#   values from the geographically nearest non-flagged plot.
#
# Inputs:
#   df      - data.frame with LAT, LON, NA_flag, and covariate columns
#   lat_col - name of latitude column (default "LAT")
#   lon_col - name of longitude column (default "LON")
#
# Output:
#   data.frame with missing rows imputed by nearest neighbor
################################################################################

replace_rows_with_nearest <- function(df,
                                      lat_col = "LAT",
                                      lon_col = "LON") {

  # Convert to SpatialPointsDataFrame
  coords <- df[, c(lon_col, lat_col)]
  coordinates(df) <- ~ LON + LAT
  proj4string(df) <- sp::CRS("+init=epsg:4326")

  flagged_rows <- which(df$NA_flag == 1)
  valid_rows   <- which(df$NA_flag == 0)

  target_columns <- c(
    paste0("C", 1:21),
    paste0("O", 1:5),
    paste0("H", 1:4),
    paste0("T", 1:12),
    "gez_code", "CONTINENT"
  )

  for (row_index in flagged_rows) {
    distances <- spDistsN1(
      sp::coordinates(df)[valid_rows, , drop = FALSE],
      sp::coordinates(df)[row_index, , drop = FALSE],
      longlat = TRUE
    )
    nearest_index <- valid_rows[which.min(distances)]

    df@data[row_index, target_columns] <- df@data[nearest_index, target_columns]
  }

  as.data.frame(df)
}

################################################################################
# Function: MATRIX_RF_func
#
# Description:
#   Train continent-specific Random Forest models with one-hot GEZ encoding.
#
# Inputs:
#   train_df - training data.frame (contains Y, CONTINENT, GEZ dummy variables, etc.)
#   dir      - directory to save final models and tuning results
#   Mod      - model name ("MT" = mortality, "UG" = upgrowth, "RC" = recruitment)
#   Y        - name of response variable ("M", "dD", "R")
#   CONT     - character vector of continents to model (e.g., c("AF", "AS"))
#
# Outputs:
#   - RF_<Mod>_finetune.csv (per-continent hyperparameter grid and RMSE)
#   - RF.<Mod>.<date>.CONT.<continent>.RData (fitted RF models)
#   - RF_<Mod>_summary_<date>.csv (performance summary)
################################################################################

MATRIX_RF_func <- function(train_df, dir, Mod, Y, CONT) {
  date <- format(Sys.Date(), "%m%d")

  # Standardize response column name
  names(train_df)[names(train_df) == Y] <- "Y"

  attr_remove <- c("PlotID")
  df <- train_df[, !colnames(train_df) %in% attr_remove]
  df <- na.omit(df)

  param    <- NULL
  RMSE_all <- NULL

  for (continent in CONT) {
    df1 <- subset(df, CONTINENT == continent)

    # Subset to continent-specific GEZ dummy variables
    gez_prefix <- paste0("GEZ_label", continent)
    df2 <- df1 %>%
      dplyr::filter(CONTINENT == continent) %>%
      dplyr::select(dplyr::starts_with(gez_prefix))

    df2 <- cbind.data.frame(df1[, 1:48], df2)
    df2 <- df2[, !colnames(df2) %in% c("CONTINENT")]

    # Hyperparameter tuning
    n            <- 10   # iterations
    prop         <- 0.001
    max_ntree    <- 200
    max_nodesize <- 5
    max_mtry     <- 5

    sample_idx <- sample.int(
      n = nrow(df2),
      size = max(1000, floor(prop * nrow(df2))),
      replace = TRUE
    )
    train_df1 <- df2[sample_idx, ]

    sample_idx <- sample.int(
      n = nrow(train_df1),
      size = floor(0.5 * nrow(train_df1)),
      replace = FALSE
    )

    test  <- train_df1[sample_idx, ]
    train <- train_df1[-sample_idx, ]

    RMSE_RF <- NULL
    RMSE    <- NULL
    HyperP  <- NULL

    for (i in seq_len(n)) {
      m <- 0
      RMSE_RF <- numeric(0)

      for (j in seq(10, max_ntree, length.out = 20)) {
        for (k in seq(1, max_nodesize, 1)) {
          for (l in seq(1, max_mtry, 1)) {
            m <- m + 1

            RF <- randomForest(
              Y ~ ., data = train,
              importance = FALSE,
              proximity  = FALSE,
              ntree      = round(j),
              nodesize   = k,
              mtry       = l
            )

            pred <- predict(RF, test, type = "response")
            RMSE_RF[m] <- sqrt(sum((test$Y - pred)^2) / length(test$Y))
            HyperP <- rbind(HyperP, c(round(j), k, l, continent))
          }
        }
      }

      if (i == 1) {
        RMSE <- data.frame(RMSE_RF)
      } else {
        RMSE <- cbind(RMSE, RMSE_RF)
      }

      cat("CONT:", continent, "iter:", i, "\n")
    }

    HyperP <- as.data.frame(HyperP)
    names(HyperP) <- c("ntree", "nodesize", "mtry", "CONT")

    RMSE1 <- cbind.data.frame(HyperP, rowMeans(RMSE))
    names(RMSE1)[ncol(RMSE1)] <- "RMSE_mean"

    min_row <- which.min(RMSE1$RMSE_mean)

    ntree_best    <- as.numeric(RMSE1[min_row, "ntree"])
    nodesize_best <- as.numeric(RMSE1[min_row, "nodesize"])
    mtry_best     <- as.numeric(RMSE1[min_row, "mtry"])

    RMSE_all <- rbind(RMSE_all, RMSE1)

    RF <- randomForest(
      Y ~ ., data = df2,
      importance = FALSE,
      proximity  = FALSE,
      ntree      = ntree_best,
      nodesize   = nodesize_best,
      mtry       = mtry_best
    )

    save(
      RF,
      file = file.path(dir, paste0("RF.", Mod, ".", date, ".CONT.", continent, ".RData"))
    )

    Rsq      <- RF$rsq[length(RF$rsq)]
    mse      <- RF$mse[length(RF$mse)]
    Pred_avg <- predict(RF, data.frame(t(colMeans(df2))), type = "response")

    out <- c(Rsq, mse, Pred_avg, continent)
    param <- rbind.data.frame(param, out)

    cat("CONT:", continent, "Rsq:", Rsq, "Prd:", Pred_avg, "\n")
    cat("  ntree", ntree_best, "node_size", nodesize_best, "mtry", mtry_best, "\n")
  }

  names(param) <- c("Rsq", "mse", "prd", "CONT")

  write.csv(
    param,
    file = file.path(dir, paste0("RF_", Mod, "_summary_", date, ".csv")),
    row.names = FALSE
  )

  write.csv(
    RMSE_all,
    file = file.path(dir, paste0("RF_", Mod, "_finetune.csv")),
    row.names = FALSE
  )
}

################################################################################
#                               MAIN WORKFLOW                                  #
################################################################################

##########################################
# Step 1: Read global treelist data      #
##########################################

dat <- read.csv(file.path(data_dir, "GFB3_globe_step4_0721.csv"))

# DBH group tags
D_threshold <- 5      # cm
DBHseq      <- seq(D_threshold, 70, 5)

dat$D_GP <- cut(dat$PrevDBH, breaks = DBHseq, right = FALSE)
dat$D_GP <- ifelse(is.na(dat$D_GP) & dat$PrevDBH >= 70, length(DBHseq), dat$D_GP)
dat$D_GP <- ifelse(is.na(dat$D_GP) & dat$PrevDBH < D_threshold, 0, dat$D_GP)

##########################################
# Step 2: Plot-level attributes          #
##########################################

# Plot basal area and total number of trees
B <- tapply(
  3.14 * ifelse(is.na(dat$PrevDBH), 0, dat$PrevDBH)^2 / 40000 * dat$TPH,
  dat$PlotID, sum
)

N <- tapply(
  ifelse(dat$D_GP >= 1, dat$TPH, 0),
  dat$PlotID, sum
)

# DBH abundance matrix
X <- tapply(
  ifelse(dat$D_GP >= 1, dat$TPH, 0),
  list(dat$PlotID, dat$D_GP), sum
)

X[is.na(X)] <- 0

# Shannon and Simpson size-diversity indices
N_plot <- rowSums(X)
pi_mat <- X / N_plot

ln_pi       <- log(pi_mat)
Shannon     <- pi_mat * ln_pi
Shannon[is.na(Shannon)] <- 0
S1 <- -rowSums(Shannon)

Simpson     <- pi_mat^2
Simpson[is.na(Simpson)] <- 0
S2 <- rowSums(Simpson)

PLT <- cbind.data.frame(B, N = N_plot, S1, S2)
PLT$PlotID <- row.names(PLT)
row.names(PLT) <- NULL

LAT <- tapply(dat$Latitude, dat$PlotID, mean)
LON <- tapply(dat$Longitude, dat$PlotID, mean)

PLT <- cbind.data.frame(PLT, LAT, LON)

##########################################
# Step 3: Extract covariates             #
##########################################

PLT_cov <- cov_func2(PLT, dir = covariate_dir)

PLT_cov$NA_flag <- apply(PLT_cov, 1, function(row) {
  ifelse(any(is.na(row)), 1, 0)
})

# Remove unnecessary columns
PLT_cov <- PLT_cov[, !(names(PLT_cov) %in% c(
  "optional", "gez_abbrev", "geometry", "gez_name", "CONT"
))]

# Replace missing values using nearest neighbor
PLT_cov <- replace_rows_with_nearest(PLT_cov, lat_col = "LAT", lon_col = "LON")

##########################################
# Step 4: Merge tree list + plot attrs   #
##########################################

dat_merge <- merge(dat, PLT_cov, by = "PlotID")
dat_merge$NA_flag <- NULL
names(dat_merge)[names(dat_merge) == "gez_code"] <- "GEZ"

write.csv(
  dat_merge,
  file = file.path(data_dir, "GFB3_globe_step5_0722.csv"),
  row.names = FALSE
)

################################################################################
#                       TRAIN UPGROWTH MODEL (UG)                              #
################################################################################

setwd(model_dir)

df <- dat_merge

dat_ug <- subset(df, df$flag_dD == "FALSE")

attr_remove <- c(
  "PlotID", "Latitude", "Longitude", "TPH", "Species",
  "DBH", "YR", "PrevYR", "DSN", "TreeID", "Status", "dY",
  "flag_dD", "B1", "B2", "B_flag", "harvest_ratio", "harvest_flag",
  "D_GP", "LAT", "LON"
)

train_df <- dat_ug[, !colnames(dat_ug) %in% attr_remove]
names(train_df)[names(train_df) == "PrevDBH"] <- "D"

write.csv(
  train_df,
  file = file.path(data_dir, "UG_globe_0712.csv"),
  row.names = FALSE
)

Mod <- "UG"
Y   <- "dD"

# One-hot encode GEZ by continent
df1 <- train_df %>%
  mutate(GEZ_label = paste(CONTINENT, GEZ, sep = "_")) %>%
  mutate(GEZ_label = factor(GEZ_label)) %>%
  bind_cols(model.matrix(~ GEZ_label - 1, data = .) %>% as.data.frame())

colnames(df1) <- make.names(colnames(df1))
df1$GEC <- paste0(df1$CONTINENT, "_", df1$GEZ)

train_df_clean <- df1[!grepl("NA", df1$GEC), ]
CONT <- "AF" # or unique(train_df_clean$CONTINENT) for all continents

attr_remove <- c("GEZ", "GEC", "GEZ_label", "Biome")
dat_rf_ug   <- train_df_clean[, !colnames(train_df_clean) %in% attr_remove]

MATRIX_RF_func(dat_rf_ug, model_dir, Mod, Y, CONT)

################################################################################
#                       TRAIN MORTALITY MODEL (MT)                             #
################################################################################

df <- dat_merge

df$M <- ifelse(df$Status == 1, 1, 0)
df$D <- df$PrevDBH

dat_mt <- df[, c("PlotID", "Latitude", "Longitude",
                 "S1", "S2", "B", "N", "D", "M", "dY", "TPH")]
dat_mt <- na.omit(dat_mt)
dat_mt <- dat_mt[dat_mt$B > 0 & dat_mt$B <= quantile(dat_mt$B, 0.9999, na.rm = TRUE), ]

DBHseq <- seq(10, 70, 2) # 2-cm DBH classes
dat_mt$D_GP <- cut(dat_mt$D, breaks = DBHseq, right = FALSE)
dat_mt$D_GP <- ifelse(is.na(dat_mt$D_GP) & dat_mt$D >= 70, length(DBHseq), dat_mt$D_GP)
dat_mt$D_GP <- ifelse(is.na(dat_mt$D_GP) & dat_mt$D < 10, 0, dat_mt$D_GP)

# Mortality matrix by DBH class
Xm <- tapply(ifelse(dat_mt$M == 1, dat_mt$TPH, 0),
             list(dat_mt$PlotID, dat_mt$D_GP), sum)
Xm[is.na(Xm)] <- 0
Xm <- Xm[, -1, drop = FALSE] # remove < D_min

X_all <- tapply(dat_mt$TPH,
                list(dat_mt$PlotID, dat_mt$D_GP), sum)
X_all[is.na(X_all)] <- 0
X_all <- X_all[, -1, drop = FALSE]

dY_plot <- tapply(dat_mt$dY, dat_mt$PlotID, mean)

AnnualMort <- Xm / X_all
AnnualMort <- sweep(AnnualMort, 1, dY_plot, `/`)
colnames(AnnualMort) <- seq(10, 70, 2) + 1
AnnualMort[is.na(AnnualMort)] <- -9999

PlotID <- row.names(AnnualMort)
AM     <- cbind.data.frame(PlotID, AnnualMort)

# Long format
df_long <- melt(AM, id.vars = "PlotID",
                variable.name = "Header", value.name = "M")
names(df_long)[1:2] <- c("PlotID", "D")

df_long[df_long == -9999] <- NA
df_long <- na.omit(df_long)

# Plot-level characteristics
dat_plot <- df[!duplicated(df$PlotID), c(1, 22:72)]
dat_plot$GEC <- paste0(dat_plot$CONTINENT, "_", dat_plot$GEZ)

mort_df <- merge(df_long, dat_plot, by = "PlotID")
write.csv(
  mort_df,
  file = file.path(data_dir, "MT_globe_0722.csv"),
  row.names = FALSE
)

train_df_mt <- mort_df

Mod <- "MT"
Y   <- "M"

df1_mt <- train_df_mt %>%
  mutate(GEZ_label = factor(GEC)) %>%
  bind_cols(model.matrix(~ GEZ_label - 1, data = .) %>% as.data.frame())

colnames(df1_mt) <- make.names(colnames(df1_mt))

train_df_clean_mt <- df1_mt[!grepl("NA", df1_mt$GEC), ]
CONT <- unique(train_df_clean_mt$CONTINENT)

attr_remove <- c("GEZ", "GEC", "GEZ_label", "PlotID", "LAT", "LON")
dat_rf_mt   <- train_df_clean_mt[, !colnames(train_df_clean_mt) %in% attr_remove]

MATRIX_RF_func(dat_rf_mt, model_dir, Mod, Y, CONT)

################################################################################
#                       TRAIN RECRUITMENT MODEL (RC)                           #
################################################################################

df1 <- df

df1$D <- ifelse(is.na(df1$PrevDBH) & df1$DBH <= 20, 0, df1$PrevDBH)
df1$D <- ifelse(is.na(df1$D) & df1$DBH > 20, 999, df1$D)

attr_remove <- c(
  "Latitude", "Longitude", "Species", "YR",
  "PrevDBH", "PrevYR", "DSN", "TreeID", "Status", "dD", "flag_dD",
  "B1", "B2", "B_flag", "harvest_ratio", "harvest_flag", "D_GP"
)
df1 <- df1[, !colnames(df1) %in% attr_remove]

df1$D[is.na(df1$D)]   <- 999
df1$DBH[is.na(df1$DBH)] <- 0

# Plot-level recruitment (threshold 10 cm DBH)
R <- tapply(
  ifelse(df1$D < 10 & df1$DBH >= 10, df1$TPH / df1$dY, 0),
  df1$PlotID, sum
)

LAT <- tapply(df1$LAT, df1$PlotID, mean)
LON <- tapply(df1$LON, df1$PlotID, mean)
B   <- tapply(df1$B,   df1$PlotID, mean)
N   <- tapply(df1$N,   df1$PlotID, mean)
S1  <- tapply(df1$S1,  df1$PlotID, mean)
S2  <- tapply(df1$S2,  df1$PlotID, mean)

dat_rc <- cbind.data.frame(LAT, LON, B, N, S1, S2, R)
dat_rc$PlotID <- row.names(dat_rc)
row.names(dat_rc) <- NULL

df_cov_rc <- cov_func2(dat_rc, dir = covariate_dir)

PLT_cov_rc <- df_cov_rc
PLT_cov_rc$NA_flag <- apply(df_cov_rc, 1, function(row) {
  ifelse(any(is.na(row)), 1, 0)
})

PLT_cov_rc <- replace_rows_with_nearest(PLT_cov_rc, lat_col = "LAT", lon_col = "LON")

df_cov1 <- PLT_cov_rc[, c(3:50, 53, 56)]

write.csv(
  df_cov1,
  file = file.path(data_dir, "RC_globe_0722.csv"),
  row.names = FALSE
)

Mod <- "RC"
Y   <- "R"

train_df_rc <- df_cov1
names(train_df_rc)[49] <- "GEZ"

df1_rc <- train_df_rc %>%
  mutate(GEZ_label = paste(CONTINENT, GEZ, sep = "_")) %>%
  mutate(GEZ_label = factor(GEZ_label)) %>%
  bind_cols(model.matrix(~ GEZ_label - 1, data = .) %>% as.data.frame())

colnames(df1_rc) <- make.names(colnames(df1_rc))
df1_rc$GEC <- paste0(df1_rc$CONTINENT, "_", df1_rc$GEZ)

train_df_clean_rc <- df1_rc[!grepl("NA", df1_rc$GEC), ]
CONT <- unique(train_df_clean_rc$CONTINENT)

attr_remove <- c("GEZ", "GEC", "GEZ_label")
dat_rf_rc   <- train_df_clean_rc[, !colnames(train_df_clean_rc) %in% attr_remove]

MATRIX_RF_func(dat_rf_rc, model_dir, Mod, Y, CONT)

################################################################################
#             EXPORT PLOT-LEVEL DATA FOR PUBLIC SHARING                        #
################################################################################

dat_pub <- read.csv(file.path(data_dir, "GFB3_globe_step4_0721.csv"))

B_pub <- tapply(
  3.14 * ifelse(is.na(dat_pub$PrevDBH), 0, dat_pub$PrevDBH)^2 / 40000 * dat_pub$TPH,
  dat_pub$PlotID, sum
)

N_pub <- tapply(
  ifelse(dat_pub$DBH >= 0, dat_pub$TPH, 0),
  dat_pub$PlotID, sum
)

DBHseq_pub <- seq(10, 70, 5)  # 5-cm DBH classes
dat_pub$D_GP <- cut(dat_pub$DBH, breaks = DBHseq_pub, right = FALSE)
dat_pub$D_GP <- ifelse(is.na(dat_pub$D_GP) & dat_pub$DBH >= 70, length(DBHseq_pub), dat_pub$D_GP)
dat_pub$D_GP <- ifelse(is.na(dat_pub$D_GP) & dat_pub$DBH < 10, 0, dat_pub$D_GP)

X_pub <- tapply(
  ifelse(dat_pub$D_GP >= 1, dat_pub$TPH, 0),
  list(dat_pub$PlotID, dat_pub$D_GP), sum
)
X_pub[is.na(X_pub)] <- 0

pi_pub      <- X_pub / N_pub
ln_pi_pub   <- log(pi_pub)
Shannon_pub <- pi_pub * ln_pi_pub
Shannon_pub[is.na(Shannon_pub)] <- 0
S1_pub      <- -rowSums(Shannon_pub)

Simpson_pub      <- pi_pub^2
Simpson_pub[is.na(Simpson_pub)] <- 0
S2_pub           <- rowSums(Simpson_pub)

PLT_pub <- cbind.data.frame(B = B_pub, N = N_pub, S1 = S1_pub, S2 = S2_pub, X_pub)
PLT_pub$PlotID <- row.names(PLT_pub)
row.names(PLT_pub) <- NULL

LAT_pub <- tapply(dat_pub$Latitude, dat_pub$PlotID, mean)
LON_pub <- tapply(dat_pub$Longitude, dat_pub$PlotID, mean)

LAT_pub <- round(LAT_pub, 1)
LON_pub <- round(LON_pub, 1)

PLT_pub <- cbind.data.frame(PLT_pub, LAT = LAT_pub, LON = LON_pub)

PLT_pub <- PLT_pub[, c(19:21, 1:18)]
names(PLT_pub)[8:21] <- paste0("D", names(PLT_pub)[8:21])

thresholds <- quantile(PLT_pub$B, 0.99, na.rm = TRUE)
dat_out    <- subset(PLT_pub, PLT_pub$B <= thresholds)

# dat_out can now be written and shared as a public plot-level dataset:
# write.csv(dat_out, file = file.path(data_dir, "MATRIX_plot_level_public.csv"), row.names = FALSE)

# End of script
