"""Explain raw log-odds; keep calibrated probability and causal claims separate."""
import joblib
import numpy as np
import pandas as pd
from catboost import Pool,CatBoostClassifier
from credit_experiment import ROOT,OUT,CATS,data,features,read_json,probability,calibrated,write_json

if __name__=='__main__':
    chosen=read_json(OUT/'selection.json')['champion']
    if not chosen.startswith('catboost'):raise RuntimeError('This exact explanation implementation is for CatBoost only.')
    bundle=joblib.load(OUT/'models'/f'{chosen}.joblib');model=bundle['model']
    d=data();split=pd.read_csv(OUT/'splits.csv');idx=np.flatnonzero(split.partition=='validation')[:25]
    x=features(d.iloc[idx],bundle['variant'])[bundle['columns']]
    pool=Pool(x,cat_features=CATS)
    shap=model.get_feature_importance(pool,type='ShapValues')
    raw_score=model.predict(pool,prediction_type='RawFormulaVal')
    np.testing.assert_allclose(shap.sum(axis=1),raw_score,rtol=1e-9,atol=1e-10)
    native=CatBoostClassifier();native.load_model(str(OUT/'models'/f'{chosen}.cbm'))
    np.testing.assert_allclose(native.predict_proba(pool),model.predict_proba(pool),rtol=1e-10,atol=1e-12)
    raw_p=probability(model,x);final_p=calibrated(bundle['calibration_kind'],bundle['calibrator'],raw_p)
    explanations=[]
    for j in range(5):
        indices=np.argsort(np.abs(shap[j,:-1]))[::-1][:5]
        explanations.append({'source':'validation example, not a real bank customer','dataset_ID':int(d.ID.iloc[idx[j]]),
            'raw_log_odds':float(raw_score[j]),'base_log_odds':float(shap[j,-1]),'raw_probability':float(raw_p[j]),'calibrated_probability':float(final_p[j]),
            'top_raw_log_odds_contributions':[{'feature':x.columns[i],'value':str(x.iloc[j,i]),'contribution':float(shap[j,i])} for i in indices]})
    write_json(OUT/'explanations.json',{'model':chosen,'explained_output':'raw model log-odds, not causal effect','calibration_kind':bundle['calibration_kind'],'additivity_check':'passed on 25 validation rows','native_cbm_reload_parity':'passed','examples':explanations})
    write_json(OUT/'model_card.json',{'model':chosen,'experiment':'experiment_v1','intended_use':'non-commercial UCI within-cohort behavioral research and local demonstration',
        'excluded_claims':['Thai-bank readiness','new applicant/SME underwriting','regulatory 12-month PD','monetary expected loss','fairness certification','causal explanations'],
        'target':'default.payment.next.month; exact event threshold not established','features':bundle['columns'],'calibration':bundle['calibration_kind'],
        'selection':'calibrated validation log loss before final test','data_source':'Yeh 2009 UCI Default of Credit Card Clients, CC BY 4.0; Kaggle mirror cross-checked against original XLS and UCI CSV',
        'demographic_feature_policy':'Included to benchmark original 23 inputs; not permission to use in an underwriting policy',
        'artifacts':['models/'+chosen+'.joblib','models/'+chosen+'.cbm','protocol.json','data_audit.json','requirements.lock.txt at repository root']})
    print('SHAP additivity and native model reload parity passed; wrote explanations and model card')
