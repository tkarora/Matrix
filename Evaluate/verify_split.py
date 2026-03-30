import os
from google.cloud import bigquery

# Bypass internal proxy mTLS authentication blocks
os.environ['GOOGLE_API_USE_MTLS_ENDPOINT'] = 'never'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'

def verify():
    client = bigquery.Client(project="cameltrain")
    print("Verifying Test Set spatial holdout...")
    q1 = """
    SELECT COUNT(*) as overlap_count FROM (
      SELECT DISTINCT STATECD, UNITCD, COUNTYCD, PLOT FROM `cameltrain.Forest_MATRIX.fia_matrix_test_set`
    ) t
    JOIN (
      SELECT DISTINCT STATECD, UNITCD, COUNTYCD, PLOT FROM `cameltrain.Forest_MATRIX.fia_matrix_train_set`
    ) tr
      ON t.STATECD = tr.STATECD AND t.UNITCD = tr.UNITCD AND t.COUNTYCD = tr.COUNTYCD AND t.PLOT = tr.PLOT
    """
    res1 = list(client.query(q1).result())[0]
    print(f"Overlap between Test and Train sets (expect 0): {res1['overlap_count']}")

    print("Verifying Validation Set temporal holdout...")
    q2 = """
    SELECT COUNT(*) as violations
    FROM (SELECT DISTINCT STATECD, UNITCD, COUNTYCD, PLOT, YR FROM `cameltrain.Forest_MATRIX.fia_matrix_val_set`) v
    JOIN (SELECT DISTINCT STATECD, UNITCD, COUNTYCD, PLOT, YR FROM `cameltrain.Forest_MATRIX.fia_matrix_train_set`) t
      ON v.STATECD = t.STATECD AND v.UNITCD = t.UNITCD AND v.COUNTYCD = t.COUNTYCD AND v.PLOT = t.PLOT
    WHERE v.YR <= t.YR
    """
    res2 = list(client.query(q2).result())[0]
    print(f"Validation transition years occurring before/on Train years (expect 0): {res2['violations']}")

    print("Verifying Row counts...")
    q3 = """
    SELECT
      (SELECT COUNT(*) FROM `cameltrain.Forest_MATRIX.fia_matrix_test_set`) as test_rows,
      (SELECT COUNT(*) FROM `cameltrain.Forest_MATRIX.fia_matrix_val_set`) as val_rows,
      (SELECT COUNT(*) FROM `cameltrain.Forest_MATRIX.fia_matrix_train_set`) as train_rows,
      (SELECT COUNT(*) FROM `cameltrain.Forest_MATRIX.fia_matrix_training_base` b
       JOIN `cameltrain.Forest_MATRIX.fia_grid3km_covariates` g
        ON b.STATECD = g.STATECD AND b.UNITCD = g.UNITCD AND b.COUNTYCD = g.COUNTYCD AND b.PLOT = g.PLOT) as total_rows
    """
    res3 = list(client.query(q3).result())[0]
    print(f"Test= {res3['test_rows']}, Val= {res3['val_rows']}, Train= {res3['train_rows']}")
    calc_total = res3['test_rows'] + res3['val_rows'] + res3['train_rows']
    actual_total = res3['total_rows']
    print(f"Sum matches exactly? {calc_total == actual_total} ({calc_total} vs {actual_total})")

if __name__ == "__main__":
    verify()
