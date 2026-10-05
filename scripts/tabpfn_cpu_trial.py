"""Explicit auxiliary comparison: same fixed 1000-row context, not full-data ranking."""
from __future__ import annotations
import os
os.environ['TABPFN_NO_BROWSER']='1'
os.environ['TABPFN_DISABLE_TELEMETRY']='1'
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
import torch
from dotenv import load_dotenv
from tabpfn import TabPFNClassifier
from tabpfn.constants import ModelVersion
from credit_experiment import ROOT, OUT, CATS, TARGET, SEED, data, features, make_model, probability, choose_calibration, calibrated, metrics, write_json, read_json
load_dotenv(ROOT/'.env',encoding='utf-8-sig')

def main():
    import argparse
    parser=argparse.ArgumentParser();parser.add_argument('--version',choices=['v3.5']);args=parser.parse_args()
    suffix='_v3_5' if args.version else ''
    if (OUT/f'tabpfn{suffix}_trial.json').exists(): raise RuntimeError('Auxiliary trial already recorded; do not overwrite.')
    torch.set_num_threads(4)
    d=data();s=pd.read_csv(OUT/'splits.csv',dtype={'group':str});subset=read_json(OUT/'tabpfn_cpu_subset.json')
    test=np.flatnonzero(s.partition=='test');y=d[TARGET].to_numpy()
    diagnostics=read_json(ROOT/'outputs/diagnostics/tabpfn_3_5_smoke.json')
    version=ModelVersion.V3_5 if args.version or diagnostics['status']=='ok' else ModelVersion.V2
    numeric=d.drop(columns=['ID',TARGET]);cats=[numeric.columns.get_loc(c) for c in CATS]
    rows=[];predictions={'ID':d.ID.iloc[test].to_numpy()}
    for name in (['tabpfn'] if args.version else ['tabpfn','catboost']):
        start=time.perf_counter()
        status={'name':name,'version':version.value if name=='tabpfn' else 'catboost_fixed_depth6','fit_rows':len(subset['fit']),'validation_rows':len(subset['validation']),'calibration_rows':len(subset['calibration']),'test_rows':len(test)}
        try:
            if name=='tabpfn':
                x=numeric
                model=TabPFNClassifier.create_default_for_version(version,device='cpu',n_estimators=2,n_jobs=4,categorical_features_indices=cats,fit_mode='fit_preprocessors',memory_saving_mode=True,random_state=SEED)
            else:
                x=features(d)
                model=make_model('catboost',{'depth':6,'l2_leaf_reg':5.},x)
            print('START',name,version.value,'fit',len(subset['fit']),flush=True)
            model.fit(x.iloc[subset['fit']],y[subset['fit']])
            cal_p=probability(model,x.iloc[subset['calibration']])
            kind,obj,losses=choose_calibration(cal_p,y[subset['calibration']],s.group.iloc[subset['calibration']].to_numpy())
            val_p=calibrated(kind,obj,probability(model,x.iloc[subset['validation']]))
            fit_time=time.perf_counter()-start
            t=time.perf_counter()
            test_p=[]
            for offset in range(0,len(test),512):
                test_p.extend(probability(model,x.iloc[test[offset:offset+512]]))
                print(name,'predicted',min(offset+512,len(test)),flush=True)
            test_p=np.asarray(test_p)
            predictions[f'aux_{name}_{version.value if name=="tabpfn" else "1000"}__raw']=test_p
            predictions[f'aux_{name}_{version.value if name=="tabpfn" else "1000"}']=calibrated(kind,obj,test_p)
            status.update(status='ok',calibration=kind,calibration_oof_losses=losses,validation_calibrated=metrics(y[subset['validation']],val_p),fit_calibration_seconds=fit_time,test_batch_prediction_seconds=time.perf_counter()-t,n_estimators=2 if name=='tabpfn' else 600)
        except Exception as e:
            status.update(status='failed',exception=type(e).__name__)
            print('FAIL',name,type(e).__name__,flush=True)
        rows.append(status)
    pd.DataFrame(predictions).to_csv(OUT/f'tabpfn{suffix}_test_predictions.csv',index=False)
    write_json(OUT/f'tabpfn{suffix}_trial.json',{'track':'auxiliary_cpu_subset','full_data_comparison':False,'v3_5_attempt':diagnostics,'actual_version':version.value,'trials':rows})
    print(json.dumps(rows,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
