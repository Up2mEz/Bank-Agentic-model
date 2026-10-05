"""Score the development-selected V2 pipeline, no lending decision."""
import argparse
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from credit_experiment import TARGET,probability,calibrated
from credit_research_v2 import OUT
from credit_features_v2 import trajectory_features

def score(rows,bundle):
    if bundle['selected_pipeline']=='reference_v1':
        names=['reference_v1'];key='reference_v1'
    else:
        names=[bundle['catboost']] if bundle['weight']==1 else [bundle['lightgbm']] if bundle['weight']==0 else [bundle['catboost'],bundle['lightgbm']]
        key='candidate_blend'
    ps={}
    for name in names:
        item=bundle['models'][name];x=trajectory_features(rows,item['variant'])[item['columns']];ps[name]=probability(item['model'],x)
    if key=='reference_v1':raw=ps['reference_v1']
    elif bundle['weight']==1:raw=ps[bundle['catboost']]
    elif bundle['weight']==0:raw=ps[bundle['lightgbm']]
    else:raw=bundle['weight']*ps[bundle['catboost']]+(1-bundle['weight'])*ps[bundle['lightgbm']]
    c=bundle['calibrators'][key];p=calibrated(c['kind'],c['object'],raw)
    assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
    return pd.DataFrame({'input_row_position':np.arange(len(rows)),'model_version':'experiment_v2/'+bundle['selected_pipeline'],'raw_probability':raw,'calibrated_probability':p,'target':TARGET,'purpose':'Development research on exposed cohort; no lending decision'},index=rows.index)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('input_csv',type=Path);p.add_argument('--output',type=Path,default=OUT/'demo_scores.csv');args=p.parse_args()
    rows=pd.read_csv(args.input_csv)
    expected=['LIMIT_BAL','SEX','EDUCATION','MARRIAGE','AGE','PAY_0','PAY_2','PAY_3','PAY_4','PAY_5','PAY_6',*[f'BILL_AMT{i}' for i in range(1,7)],*[f'PAY_AMT{i}' for i in range(1,7)]]
    if set(rows)!=set(expected):raise ValueError('Exactly 23 original predictors; exclude ID/target.')
    if not np.isfinite(rows.to_numpy(dtype=float)).all():raise ValueError('All original input values must be finite.')
    for c in ['SEX','EDUCATION','MARRIAGE','AGE','PAY_0','PAY_2','PAY_3','PAY_4','PAY_5','PAY_6']:
        if not np.equal(rows[c],np.floor(rows[c])).all():raise ValueError('Category and age values must be integer.')
    bundle=joblib.load(OUT/'models/pipeline.joblib');result=score(rows,bundle);args.output.parent.mkdir(parents=True,exist_ok=True);result.to_csv(args.output,index=False);print(result.to_string(index=False))
