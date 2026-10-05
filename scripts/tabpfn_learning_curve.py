"""Locked 4000-context TabPFN3.5 and matched CatBoost; exposed reference only."""
from __future__ import annotations
import os
os.environ['TABPFN_NO_BROWSER']='1';os.environ['TABPFN_DISABLE_TELEMETRY']='1'
import time
import hashlib
import numpy as np
import pandas as pd
import torch
from dotenv import load_dotenv
from tabpfn import TabPFNClassifier
from tabpfn.constants import ModelVersion
from credit_experiment import ROOT,OUT as OLD,TARGET,CATS,SEED,data,features,read_json,write_json,make_model,probability,choose_calibration,calibrated,metrics

OUT=ROOT/'outputs/experiment_v2'

def main():
    if (OUT/'tabpfn_4000_results.json').exists():raise RuntimeError('Preserve completed auxiliary results.')
    load_dotenv(ROOT/'.env',encoding='utf-8-sig');torch.set_num_threads(2)
    subset=read_json(OUT/'tabpfn_4000_subset.json');d=data();s=pd.read_csv(OLD/'splits.csv',dtype={'group':str});y=d[TARGET].to_numpy();test=np.flatnonzero(s.partition=='test');rows=[];preds={'ID':d.ID.iloc[test].to_numpy()}
    assert set(read_json(OLD/'tabpfn_cpu_subset.json')['fit'])<=set(subset['fit'])
    for a,b in [('fit','validation'),('fit','calibration'),('validation','calibration')]:assert not set(s.group.iloc[subset[a]])&set(s.group.iloc[subset[b]])
    assert not set(s.group.iloc[subset['fit']])&set(s.group.iloc[test])
    for name in ['tabpfn_3_5_4000','catboost_4000']:
        print('START',name,'fit4000',flush=True);start=time.perf_counter()
        try:
            if name.startswith('tabpfn'):
                x=d.drop(columns=['ID',TARGET]);cats=[x.columns.get_loc(c) for c in CATS]
                model=TabPFNClassifier.create_default_for_version(ModelVersion.V3_5,device='cpu',n_estimators=2,n_jobs=2,categorical_features_indices=cats,fit_mode='fit_preprocessors',memory_saving_mode=True,random_state=SEED)
            else:x=features(d);model=make_model('catboost',{'depth':6,'l2_leaf_reg':5.},x)
            model.fit(x.iloc[subset['fit']],y[subset['fit']]);cal=probability(model,x.iloc[subset['calibration']]);kind,obj,losses=choose_calibration(cal,y[subset['calibration']],s.group.iloc[subset['calibration']].to_numpy());val=calibrated(kind,obj,probability(model,x.iloc[subset['validation']]))
            fitsec=time.perf_counter()-start;t=time.perf_counter();raw=[]
            for startrow in range(0,len(test),512):
                raw.extend(probability(model,x.iloc[test[startrow:startrow+512]]));print(name,'predicted',min(startrow+512,len(test)),flush=True)
            raw=np.asarray(raw);p=calibrated(kind,obj,raw);assert len(p)==4500 and np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
            preds[name]=p;preds[name+'__raw']=raw
            rows.append({'model':name,'status':'ok','context_rows':4000,'validation_rows':len(subset['validation']),'calibration_rows':len(subset['calibration']),'test_rows':len(test),'actual_version':'v3.5' if name.startswith('tabpfn') else 'fixed_catboost_depth6','calibration':kind,'calibration_oof_losses':losses,'validation':metrics(y[subset['validation']],val),'exposed_test_reference':metrics(y[test],p),'fit_preprocessing_calibration_seconds':fitsec,'test_batch_seconds':time.perf_counter()-t})
        except Exception as e:
            rows.append({'model':name,'status':'failed','exception_type':type(e).__name__});print('FAILED',name,type(e).__name__,flush=True)
        write_json(OUT/'tabpfn_4000_progress.json',rows)
    pd.DataFrame(preds).to_csv(OUT/'tabpfn_4000_predictions.csv',index=False)
    write_json(OUT/'tabpfn_4000_results.json',{'trials':rows,'same_val_cal_test_as_1000':True,'nested_1000_context':True,'no_unbiased_test_claim':True,'main_selection_not_changed_by_auxiliary':True,'subset_sha256':hashlib.sha256((OUT/'tabpfn_4000_subset.json').read_bytes()).hexdigest()});print(rows,flush=True)

if __name__=='__main__':main()
