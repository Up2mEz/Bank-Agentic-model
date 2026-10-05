"""Evaluate only a predeclared V3.5 auxiliary prediction; never reselect main model."""
import hashlib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from credit_experiment import OUT,TARGET,data,metrics,logit,write_json,read_json

if __name__=='__main__':
    destination=OUT/'tabpfn_v3_5_results.json'
    if destination.exists():raise RuntimeError('V3.5 already evaluated; preserve the result.')
    d=data();s=pd.read_csv(OUT/'splits.csv');test=d[s.partition=='test'].reset_index(drop=True)
    prediction=pd.read_csv(OUT/'tabpfn_v3_5_test_predictions.csv')
    trial=read_json(OUT/'tabpfn_v3_5_trial.json')
    assert trial['actual_version']=='v3.5'
    assert len(trial['trials'])==1 and trial['trials'][0]['status']=='ok'
    assert len(prediction)==len(test) and prediction.ID.is_unique
    assert np.array_equal(test.ID,prediction.ID)
    assert set(prediction.columns)=={'ID','aux_tabpfn_v3.5__raw','aux_tabpfn_v3.5'}
    rows=[]
    for name in prediction.columns:
        if name=='ID':continue
        p=prediction[name].to_numpy();y=test[TARGET].to_numpy()
        assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
        m=metrics(y,p)
        calibration=LogisticRegression(C=1e6,max_iter=1000).fit(logit(p),y)
        m.update(model=name,track='auxiliary_1000_fit',gini=2*m['roc_auc']-1,calibration_intercept=float(calibration.intercept_[0]),calibration_slope=float(calibration.coef_[0,0]))
        rows.append(m)
    hashes={name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ['protocol.json','tabpfn_cpu_subset.json','splits.csv','tabpfn_v3_5_test_predictions.csv','tabpfn_v3_5_trial.json','selection.json','test_results.json']}
    write_json(destination,{'results':rows,'same_locked_subset_and_test':True,'main_champion_unchanged':read_json(OUT/'selection.json')['champion'],'scope':'Predeclared auxiliary model, access delayed; no retuning after main test results','verification':{'actual_version':'v3.5','trial_status':'ok','test_rows':len(test),'test_events':int(test[TARGET].sum()),'same_test_ids_and_order':True,'unique_test_ids':True,'finite_probability_in_unit_interval':True},'artifact_sha256':hashes})
    print(pd.DataFrame(rows).to_string(index=False))
