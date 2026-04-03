# Evaluation Analysis Guide: Attributing Model Error to Input Quality

This guide provides BigQuery SQL drafts to help analyze how much of the simulation error (RMSE) can be attributed to the quality of spatial inputs (distance to nearest grid point) versus the model dynamics themselves.

---

## 📐 1. Understanding Plot Distances

The evaluation table `cameltrain.Forest_MATRIX.fia_grid_3km_eval` **automatically preserves** the pre-computed distance (in meters) between a physical FIA plot and its nearest neighbor in the 3km covariate grid. You do not need to recalculate this!

### Query: Global Median Distance of Evaluation Plots
 Run this to see how far, on average, your evaluation plots were shifted to match the climate/soil grid.

```sql
WITH distinct_plots AS (
    SELECT DISTINCT ID, Distance_Meters
    FROM `cameltrain.Forest_MATRIX.fia_grid_3km_eval`
)
SELECT 
    APPROX_QUANTILES(Distance_Meters, 100)[OFFSET(50)] AS median_distance_meters
FROM distinct_plots;
```

---

## 🧠 2. Correlating Error with Distance

The evaluation engine uploads metrics to `cameltrain.Forest_MATRIX.forest_matrix_fia_runs` at the **per-plot transition granularity**. This allows you to join errors directly with distances!

### Query: Pearson Correlation between RMSE and Distance
Run this to see if "farther" plots yield higher errors (Linear Correlation Coefficient). 
- Close to `1.0`: Resolution fuzzing causes the error.
- Close to `0.0`: The error is likely in the model dynamics, not the spatial match!

```sql
WITH plot_metrics AS (
    SELECT 
        ID, 
        AVG(RMSE) AS avg_rmse
    FROM `cameltrain.Forest_MATRIX.forest_matrix_fia_runs`
    GROUP BY ID
),
plot_distances AS (
    SELECT DISTINCT ID, Distance_Meters
    FROM `cameltrain.Forest_MATRIX.fia_grid_3km_eval`
)
SELECT 
    CORR(m.avg_rmse, d.Distance_Meters) AS pearson_correlation_rmse_distance
FROM plot_metrics m
JOIN plot_distances d ON m.ID = d.ID;
```

---

## 📈 3. Stratified Error Buckets (Advanced)
If you want to see if errors spike past a certain distance threshold (e.g. 5km), you can bucket them:

```sql
WITH plot_metrics AS (
    SELECT ID, AVG(RMSE) AS avg_rmse
    FROM `cameltrain.Forest_MATRIX.forest_matrix_fia_runs`
    GROUP BY ID
),
plot_distances AS (
    SELECT DISTINCT ID, Distance_Meters
    FROM `cameltrain.Forest_MATRIX.fia_grid_3km_eval`
)
SELECT 
    CASE 
        WHEN d.Distance_Meters < 1609 THEN 'Under 1 Mile'
        WHEN d.Distance_Meters < 5000 THEN '1-5 KM'
        ELSE 'Over 5 KM'
    END AS distance_bucket,
    COUNT(DISTINCT m.ID) AS plot_count,
    AVG(m.avg_rmse) AS avg_rmse
FROM plot_metrics m
JOIN plot_distances d ON m.ID = d.ID
GROUP BY 1
ORDER BY avg_rmse DESC;
```
