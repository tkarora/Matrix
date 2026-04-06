import pandas as pd
import numpy as np
from google.cloud import bigquery

covariate_columns = [
    'LAT', 'LON',
    'C1', 'C2', 'C3', 'C4', 'C5', 'C6', 'C7', 'C8', 'C9', 'C10', 'C11', 'C12', 'C13', 'C14', 'C15', 'C16', 'C17', 'C18', 'C19', 'C20', 'C21',
    'O1', 'O2', 'O3', 'O4', 'O5',
    'H1', 'H2', 'H3', 'H4',
    'T1', 'T2', 'T3', 'T4', 'T5', 'T6', 'T7', 'T8', 'T9', 'T10', 'T11', 'T12'
]

def prepare_data_pandas(csv_path, ft) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    print(f"Loading local input CSV: {csv_path}")
    df_full = pd.read_csv(csv_path)
    
    if 'FT' in df_full.columns:
        df_full = df_full[df_full['FT'] == ft]
        print(f"Filtered to Forest Type {ft}, rows: {len(df_full)}")
        
    # 1. Upgrowth
    df_ug = df_full.dropna(subset=['PrevDBH', 'DBH'])
    df_ug = df_ug[df_ug['dY'] > 0]
    df_ug['dD'] = (df_ug['DBH'] - df_ug['PrevDBH']) / df_ug['dY']
    
    # 2. Mortality
    df_mt_base = df_full.dropna(subset=['PrevDBH']).copy()
    df_mt_base['DBH_class'] = (df_mt_base['PrevDBH'] // 2) * 2
    df_mt_base['Dead_TPH'] = np.where(df_mt_base['Status'] == 1, df_mt_base['TPH'], 0)
    
    agg_funcs_mt = {
        'Dead_TPH': 'sum',
        'TPH': 'sum',
        'dY': 'mean',
    }
    for col in covariate_columns:
        if col in df_mt_base.columns:
            agg_funcs_mt[col] = 'mean'
            
    df_mt = df_mt_base.groupby(['PlotID', 'DBH_class']).agg(agg_funcs_mt).reset_index()
    df_mt['M'] = (df_mt['Dead_TPH'] / df_mt['TPH']) / df_mt['dY']
    
    # 3. Recruitment
    df_rc_base = df_full.copy()
    df_rc_base['RC_contrib'] = np.where((df_rc_base['PrevDBH'] < 10) & (df_rc_base['DBH'] >= 10), df_rc_base['TPH'] / df_rc_base['dY'], 0)
    
    agg_funcs_rc = {
        'RC_contrib': 'sum',
    }
    for col in covariate_columns:
        if col in df_rc_base.columns:
            agg_funcs_rc[col] = 'mean'
            
    df_rc = df_rc_base.groupby('PlotID').agg(agg_funcs_rc).reset_index()
    df_rc.rename(columns={'RC_contrib': 'R'}, inplace=True)
    
    return df_ug, df_mt, df_rc

def prepare_data_bq(project, ft, limit=None, split="train") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    print(f"Querying BigQuery for Forest Type {ft} from split {split}...")
    client = bigquery.Client(project=project)
    
    # Query for Upgrowth
    query_ug = f"""
        SELECT *, (DBH - PrevDBH) / dY as dD
        FROM `cameltrain.Forest_MATRIX.fia_matrix_{split}_set`
        WHERE FT = {ft}
          AND PrevDBH IS NOT NULL AND DBH IS NOT NULL AND dY > 0
    """
    if limit:
        query_ug += f" LIMIT {limit}"
        
    print("Running Upgrowth query...")
    df_ug = client.query(query_ug).to_dataframe()
    
    # Query for Mortality
    query_mt = f"""
        WITH Binned AS (
            SELECT
                PlotID,
                FLOOR(PrevDBH / 2) * 2 AS DBH_class,
                TPH,
                Status,
                dY,
                LAT, LON, C1, C2, C3, C4, C5, C6, C7, C8, C9, C10, C11, C12, C13, C14, C15, C16, C17, C18, C19, C20, C21,
                O1, O2, O3, O4, O5, H1, H2, H3, H4, T1, T2, T3, T4, T5, T6, T7, T8, T9, T10, T11, T12
            FROM `cameltrain.Forest_MATRIX.fia_matrix_{split}_set`
            WHERE FT = {ft} AND PrevDBH IS NOT NULL
        )
        SELECT
            PlotID,
            DBH_class,
            SAFE_DIVIDE(SUM(CASE WHEN Status = 1 THEN TPH ELSE 0 END), SUM(TPH)) / AVG(dY) AS M,
            AVG(LAT) as LAT, AVG(LON) as LON,
            AVG(C1) as C1, AVG(C2) as C2, AVG(C3) as C3, AVG(C4) as C4, AVG(C5) as C5, AVG(C6) as C6, AVG(C7) as C7, AVG(C8) as C8, AVG(C9) as C9, AVG(C10) as C10, AVG(C11) as C11, AVG(C12) as C12, AVG(C13) as C13, AVG(C14) as C14, AVG(C15) as C15, AVG(C16) as C16, AVG(C17) as C17, AVG(C18) as C18, AVG(C19) as C19, AVG(C20) as C20, AVG(C21) as C21,
            AVG(O1) as O1, AVG(O2) as O2, AVG(O3) as O3, AVG(O4) as O4, AVG(O5) as O5,
            AVG(H1) as H1, AVG(H2) as H2, AVG(H3) as H3, AVG(H4) as H4,
            AVG(T1) as T1, AVG(T2) as T2, AVG(T3) as T3, AVG(T4) as T4, AVG(T5) as T5, AVG(T6) as T6, AVG(T7) as T7, AVG(T8) as T8, AVG(T9) as T9, AVG(T10) as T10, AVG(T11) as T11, AVG(T12) as T12
        FROM Binned
        GROUP BY PlotID, DBH_class
    """
    if limit:
        query_mt += f" LIMIT {limit}"
        
    print("Running Mortality query...")
    df_mt = client.query(query_mt).to_dataframe()
    
    # Query for Recruitment
    query_rc = f"""
        SELECT
            PlotID,
            SUM(CASE WHEN PrevDBH < 10 AND DBH >= 10 THEN TPH / dY ELSE 0 END) AS R,
            AVG(LAT) as LAT, AVG(LON) as LON,
            AVG(C1) as C1, AVG(C2) as C2, AVG(C3) as C3, AVG(C4) as C4, AVG(C5) as C5, AVG(C6) as C6, AVG(C7) as C7, AVG(C8) as C8, AVG(C9) as C9, AVG(C10) as C10, AVG(C11) as C11, AVG(C12) as C12, AVG(C13) as C13, AVG(C14) as C14, AVG(C15) as C15, AVG(C16) as C16, AVG(C17) as C17, AVG(C18) as C18, AVG(C19) as C19, AVG(C20) as C20, AVG(C21) as C21,
            AVG(O1) as O1, AVG(O2) as O2, AVG(O3) as O3, AVG(O4) as O4, AVG(O5) as O5,
            AVG(H1) as H1, AVG(H2) as H2, AVG(H3) as H3, AVG(H4) as H4,
            AVG(T1) as T1, AVG(T2) as T2, AVG(T3) as T3, AVG(T4) as T4, AVG(T5) as T5, AVG(T6) as T6, AVG(T7) as T7, AVG(T8) as T8, AVG(T9) as T9, AVG(T10) as T10, AVG(T11) as T11, AVG(T12) as T12
        FROM `cameltrain.Forest_MATRIX.fia_matrix_{split}_set`
        WHERE FT = {ft}
        GROUP BY PlotID
    """
    if limit:
        query_rc += f" LIMIT {limit}"
        
    print("Running Recruitment query...")
    df_rc = client.query(query_rc).to_dataframe()
    
    return df_ug, df_mt, df_rc
