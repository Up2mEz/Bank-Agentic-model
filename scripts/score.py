"""Local research scoring; loads only trusted locally generated joblib artifacts."""
import argparse
import json
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from credit_experiment import OUT, TARGET, features, probability, calibrated, read_json

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('input_csv',type=Path)
    parser.add_argument('--output',type=Path,default=OUT/'demo_scores.csv')
    args=parser.parse_args()
    selection=read_json(OUT/'selection.json');name=selection['champion']
    bundle=joblib.load(OUT/'models'/f'{name}.joblib')
    rows=pd.read_csv(args.input_csv)
    expected=['LIMIT_BAL','SEX','EDUCATION','MARRIAGE','AGE','PAY_0','PAY_2','PAY_3','PAY_4','PAY_5','PAY_6',*[f'BILL_AMT{i}' for i in range(1,7)],*[f'PAY_AMT{i}' for i in range(1,7)]]
    if set(rows.columns)!=set(expected):raise ValueError('Supply exactly the 23 original predictors; no ID, target or extra columns.')
    if not np.isfinite(rows.to_numpy(dtype=float)).all():raise ValueError('Missing or non-finite input requires review; do not silently impute.')
    for c in ['SEX','EDUCATION','MARRIAGE','AGE','PAY_0','PAY_2','PAY_3','PAY_4','PAY_5','PAY_6']:
        if not np.equal(rows[c],np.floor(rows[c])).all():raise ValueError(f'{c} must be an integer code/value')
    x=features(rows,bundle['variant'])[bundle['columns']]
    raw=probability(bundle['model'],x)
    p=calibrated(bundle['calibration_kind'],bundle['calibrator'],raw)
    result=pd.DataFrame({'model_version':f'experiment_v1/{name}','raw_probability':raw,'calibrated_probability':p,'target':TARGET,'purpose':'UCI behavioral research benchmark; no approval decision'})
    args.output.parent.mkdir(parents=True,exist_ok=True);result.to_csv(args.output,index=False)
    print(result.to_string(index=False))

if __name__=='__main__':main()
