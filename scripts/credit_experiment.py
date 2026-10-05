"""Reproducible, bounded UCI behavioral benchmark; never select on final test."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import platform
import time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs' / 'experiment_v1'
TARGET = 'default.payment.next.month'
CATS = ['SEX', 'EDUCATION', 'MARRIAGE', 'PAY_0', 'PAY_2', 'PAY_3', 'PAY_4', 'PAY_5', 'PAY_6']
SEED = 20261004

def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding='utf-8')

def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))

def data():
    return pd.read_csv(ROOT/'data/raw/kaggle_credit_card/UCI_Credit_Card.csv')

def metrics(y, p, weights=None):
    p = np.clip(np.asarray(p), 1e-7, 1-1e-7)
    return {'roc_auc': float(roc_auc_score(y,p,sample_weight=weights)),
            'average_precision': float(average_precision_score(y,p,sample_weight=weights)),
            'log_loss': float(log_loss(y,p,sample_weight=weights)),
            'brier': float(brier_score_loss(y,p,sample_weight=weights))}

def prepare():
    if (OUT/'protocol.json').exists():
        raise RuntimeError('Protocol already exists; preserve it. Use a new experiment directory for a new protocol.')
    d=data(); u=pd.read_csv(ROOT/'data/raw/uci_credit_card/data.csv')
    metadata=read_json(ROOT/'data/raw/uci_credit_card/uci_metadata.json')['data']
    mapping={v['name']:v['description'] for v in metadata['variables'] if v['role']=='Feature'}
    mapping['Y']=TARGET; u=u.rename(columns=mapping)[d.columns]
    mismatch=int((u.to_numpy()!=d.to_numpy()).sum())
    original=pd.read_excel(ROOT/'data/raw/uci_credit_card/default of credit card clients.xls',header=1)
    original=original.rename(columns={original.columns[-1]:TARGET})[d.columns]
    original_mismatch=int((original.to_numpy()!=d.to_numpy()).sum())
    assert d.shape==(30000,25) and mismatch==0
    assert original.shape==d.shape and original_mismatch==0
    assert d.ID.is_unique and not d.isna().any().any() and set(d[TARGET])=={0,1}
    x=d.drop(columns=['ID',TARGET]); y=d[TARGET].to_numpy()
    # Hash groups are checked against the count of exact, full-vector groups.
    groups=pd.util.hash_pandas_object(x,index=False).to_numpy()
    assert len(np.unique(groups))==len(x.drop_duplicates())
    conflict=pd.DataFrame({'group':groups,'y':y}).groupby('group').y.nunique().gt(1)
    domains={c:sorted(map(int,d[c].unique())) for c in CATS}
    audit={'rows':len(d),'columns':len(d.columns),'predictors':len(x.columns),
           'source_value_mismatches':mismatch,'original_xls_shape':list(original.shape),'original_xls_value_mismatches':original_mismatch,
           'source_dtype_differences':{c:[str(u[c].dtype),str(d[c].dtype)] for c in d.columns if u[c].dtype!=d[c].dtype},
           'missing_cells':int(d.isna().sum().sum()),'id_duplicates':int(d.ID.duplicated().sum()),
           'labels':d[TARGET].value_counts().sort_index().to_dict(),'event_rate':float(y.mean()),
           'identical_predictor_extra_rows':int(x.duplicated().sum()),'predictor_groups':int(len(np.unique(groups))),
           'conflicting_label_groups':int(conflict.sum()),'categorical_domains':domains,
           'negative_counts':{c:int(d[c].lt(0).sum()) for c in d.columns if c.startswith(('BILL_AMT','PAY_AMT'))},
           'numeric_summary':d.drop(columns=['ID']).describe(percentiles=[.01,.5,.99]).to_dict(),
           'undocumented_codes':{'EDUCATION':[0,5,6],'MARRIAGE':[0],'repayment':[-2,0]},
           'license_policy':'Kaggle metadata says CC0; retain original UCI CC BY 4.0 attribution rather than infer mirror relicensing rights.',
           'limitations':['Single 2005 Taiwan cohort; no genuine out-of-time evaluation','Target header says next month; exact default threshold unverified','Existing borrowers, not rejected/new-applicant population','Unknown repayment/category codes retained without invented mapping']}
    manifest=[]
    for folder in ['uci_credit_card','kaggle_credit_card']:
        for p in sorted((ROOT/'data/raw'/folder).glob('*')):
            if p.is_file() and p.stat().st_size:
                manifest.append({'path':str(p.relative_to(ROOT)),'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()})
    audit['files']=manifest
    OUT.mkdir(parents=True,exist_ok=True)
    write_json(OUT/'data_audit.json',audit)
    folds=np.full(len(d),-1,dtype=int)
    splitter=StratifiedGroupKFold(n_splits=20,shuffle=True,random_state=SEED)
    for fold,(_,idx) in enumerate(splitter.split(x,y,groups)): folds[idx]=fold
    assert (folds>=0).all()
    labels=np.where(folds<11,'fit',np.where(folds<14,'validation',np.where(folds<17,'calibration','test')))
    splits=pd.DataFrame({'ID':d.ID,'group':groups.astype(str),'fold':folds,'partition':labels})
    assert splits.groupby('group').partition.nunique().max()==1
    splits.to_csv(OUT/'splits.csv',index=False)
    # All splits and auxiliary CPU subsets are fixed before any model fit.
    rng=np.random.default_rng(SEED)
    aux={}
    for part,count in [('fit',1000),('validation',400),('calibration',600)]:
        pool=np.flatnonzero(labels==part)
        # A natural-prevalence stratified sample, without oversampling minorities.
        selected=[]
        for cls in [0,1]:
            cp=pool[y[pool]==cls]; n=round(count*len(cp)/len(pool))
            selected.extend(rng.choice(cp,n,replace=False).tolist())
        aux[part]=sorted(selected)
    write_json(OUT/'tabpfn_cpu_subset.json',aux)
    protocol={'experiment':'experiment_v1','seed':SEED,'created_utc':pd.Timestamp.now(tz='UTC').isoformat(),
        'task':'Within-cohort behavioral next-month dataset-label prediction; not regulatory 12-month PD',
        'data_sha256':hashlib.sha256((ROOT/'data/raw/kaggle_credit_card/UCI_Credit_Card.csv').read_bytes()).hexdigest(),
        'split_method':'20-fold StratifiedGroupKFold on identical predictor vectors; folds 0..10 fit,11..13 validation,14..16 calibration,17..19 final test',
        'splits':{part:{'rows':int((labels==part).sum()),'events':int(y[labels==part].sum()),'prevalence':float(y[labels==part].mean())} for part in ['fit','validation','calibration','test']},
        'categorical_features':CATS,'unknown_codes':'Preserve as distinct nominal levels; no guessed relabeling',
        'feature_policy':'23 original benchmark predictors, including demographics for research only; no underwriting policy endorsement',
        'tuning':'Three fixed settings each for Logistic/CatBoost/LightGBM; two EBM settings; validation raw log loss selects base settings',
        'calibration':'Choose identity/sigmoid/isotonic by 5-fold group-aware out-of-fold calibration log loss, then fit calibrator on full calibration partition',
        'champion':'Select MAIN calibrated pipeline by validation log loss AFTER calibration, before any final-test metric',
        'feature_ablation':'CatBoost behavioral-ratio candidate uses selected raw CatBoost settings; predeclared candidate',
        'auxiliary_tabpfn':'Try current V3.5; if authentication unavailable, explicitly report V2 separately. CPU subset 1000 fit/400 validation/600 calibration; compare CatBoost on identical subsets. Same final-test rows. Not a full-data rank comparison.',
        'metrics':['ROC AUC','Average Precision (not trapezoidal PR AUC)','log loss','Brier','calibration intercept/slope','subgroup counts'],
        'uncertainty':'300 group bootstrap replicates for preselected champion and paired differences against Logistic; descriptive intervals, not temporal evidence',
        'final_test_policy':'One evaluation script invocation after pipeline selection; no champion reselection from test',
        'cpu_threads':4,'no_smote_or_class_weights':True,'production_ready':False}
    write_json(OUT/'protocol.json',protocol)
    print(json.dumps({'audit':{k:audit[k] for k in ['rows','labels','missing_cells','identical_predictor_extra_rows','conflicting_label_groups']},'splits':protocol['splits']},ensure_ascii=False),flush=True)

def features(d, variant='raw'):
    x=d.drop(columns=['ID',TARGET],errors='ignore').copy()
    for c in CATS: x[c]=x[c].astype(int).astype(str)
    if variant=='behavior':
        for i in range(1,7):
            bill=x[f'BILL_AMT{i}']; positive=bill>0
            x[f'payment_bill_ratio_{i}']=x[f'PAY_AMT{i}'].div(bill.where(positive))
            x[f'nonpositive_bill_{i}']=(~positive).astype(int)
        x['recent_bill_utilization']=x.BILL_AMT1.div(x.LIMIT_BAL.where(x.LIMIT_BAL>0))
        x['bill_change_1_6']=x.BILL_AMT1-x.BILL_AMT6
    return x

def make_model(name,params,x):
    if name=='logistic':
        nums=[c for c in x if c not in CATS]
        preprocess=ColumnTransformer([('cat',OneHotEncoder(handle_unknown='ignore'),CATS),('num',StandardScaler(),nums)])
        return make_pipeline(preprocess,LogisticRegression(C=params['C'],max_iter=3000,random_state=SEED))
    if name.startswith('catboost'):
        from catboost import CatBoostClassifier
        return CatBoostClassifier(**params,iterations=600,learning_rate=.05,loss_function='Logloss',random_seed=SEED,thread_count=4,verbose=False,allow_writing_files=False,cat_features=CATS)
    if name=='lightgbm':
        from lightgbm import LGBMClassifier
        return LGBMClassifier(**params,n_estimators=500,learning_rate=.04,random_state=SEED,n_jobs=4,verbosity=-1)
    if name=='ebm':
        from interpret.glassbox import ExplainableBoostingClassifier
        return ExplainableBoostingClassifier(**params,feature_names=list(x.columns),feature_types=['nominal' if c in CATS else 'continuous' for c in x],max_rounds=1500,outer_bags=4,random_state=SEED,n_jobs=4)
    raise ValueError(name)

def input_for(model,x):
    if model.__class__.__name__=='LGBMClassifier':
        x=x.copy()
        categories=getattr(model,'credit_categories_',None)
        for c in CATS:
            values=x[c] if categories is None else x[c].where(x[c].isin(categories[c]),np.nan)
            x[c]=pd.Categorical(values,categories=None if categories is None else categories[c])
    return x

def probability(model,x):
    return model.predict_proba(input_for(model,x))[:,1]

def logit(p):
    p=np.clip(p,1e-7,1-1e-7);return np.log(p/(1-p)).reshape(-1,1)

def fit_calibrator(kind,p,y):
    if kind=='identity': return None
    if kind=='sigmoid': return LogisticRegression(C=1e6,max_iter=1000).fit(logit(p),y)
    return IsotonicRegression(out_of_bounds='clip').fit(p,y)

def calibrated(kind,obj,p):
    if kind=='identity': return p
    if kind=='sigmoid': return obj.predict_proba(logit(p))[:,1]
    return obj.predict(p)

def choose_calibration(p,y,groups):
    losses={}
    cv=list(StratifiedGroupKFold(n_splits=5,shuffle=True,random_state=SEED).split(p,y,groups))
    for kind in ['identity','sigmoid','isotonic']:
        pred=np.zeros(len(y))
        for fit,hold in cv:
            obj=fit_calibrator(kind,p[fit],y[fit]);pred[hold]=calibrated(kind,obj,p[hold])
        losses[kind]=float(log_loss(y,np.clip(pred,1e-7,1-1e-7)))
    kind=min(losses,key=losses.get)
    return kind,fit_calibrator(kind,p,y),losses

def train():
    if (OUT/'selection.json').exists(): raise RuntimeError('Training/selection already completed; preserve this run.')
    d=data();splits=pd.read_csv(OUT/'splits.csv',dtype={'group':str}); x=features(d);y=d[TARGET].to_numpy()
    idx={part:np.flatnonzero(splits.partition==part) for part in ['fit','validation','calibration','test']}
    settings={'logistic':[{'C':c} for c in [.1,1.,10.]],
        'catboost':[{'depth':v,'l2_leaf_reg':5.} for v in [4,6,8]],
        'lightgbm':[{'num_leaves':v,'min_child_samples':50,'reg_lambda':5.} for v in [15,31,63]],
        'ebm':[{'interactions':v} for v in [0,5]]}
    (OUT/'models').mkdir(exist_ok=True)
    record=[];predictions={'ID':d.ID.iloc[idx['test']].to_numpy()};best_cat_params=None
    jobs=list(settings.items())+[('catboost_behavior',[None])]
    for name,grid in jobs:
        xx=features(d,'behavior') if name=='catboost_behavior' else x
        if name=='catboost_behavior':grid=[best_cat_params]
        tuned=[];best_model=None;best_loss=float('inf');start=time.perf_counter()
        for params in grid:
            model=make_model(name,params,xx)
            fit_x=input_for(model,xx.iloc[idx['fit']])
            if name=='lightgbm':model.credit_categories_={c:list(fit_x[c].cat.categories) for c in CATS}
            model.fit(fit_x,y[idx['fit']])
            p=probability(model,xx.iloc[idx['validation']]);loss=log_loss(y[idx['validation']],p)
            tuned.append({'params':params,'validation_raw_log_loss':float(loss)})
            print(name,params,'validation raw log loss',round(loss,6),flush=True)
            if loss<best_loss:best_loss=loss;best_model=model;best_params=params
        if name=='catboost':best_cat_params=best_params
        cal_raw=probability(best_model,xx.iloc[idx['calibration']])
        kind,obj,cal_losses=choose_calibration(cal_raw,y[idx['calibration']],splits.group.iloc[idx['calibration']].to_numpy())
        val_p=calibrated(kind,obj,probability(best_model,xx.iloc[idx['validation']]))
        bundle={'model':best_model,'calibrator':obj,'calibration_kind':kind,'variant':'behavior' if name=='catboost_behavior' else 'raw','columns':list(xx.columns),'target':TARGET,'experiment':'experiment_v1'}
        joblib.dump(bundle,OUT/'models'/f'{name}.joblib')
        restored=joblib.load(OUT/'models'/f'{name}.joblib')
        probe=xx.iloc[idx['validation'][:25]]
        assert np.allclose(probability(best_model,probe),probability(restored['model'],probe),rtol=1e-10,atol=1e-12)
        if name.startswith('catboost'):best_model.save_model(str(OUT/'models'/f'{name}.cbm'))
        infer_start=time.perf_counter();raw=probability(best_model,xx.iloc[idx['test']]);inference=time.perf_counter()-infer_start
        predictions[f'{name}__raw']=raw;predictions[name]=calibrated(kind,obj,raw)
        row={'model':name,'track':'main','params':best_params,'calibration':kind,'calibration_oof_losses':cal_losses,'tuning':tuned,
             'validation_calibrated':metrics(y[idx['validation']],val_p),'fit_calibration_seconds':time.perf_counter()-start-inference,
             'test_batch_prediction_seconds':inference,'artifact_reload_parity':'passed'}
        record.append(row);write_json(OUT/'training_progress.json',record)
    champion=min(record,key=lambda r:r['validation_calibrated']['log_loss'])['model']
    write_json(OUT/'selection.json',{'champion':champion,'basis':'validation calibrated log loss; final-test metrics not accessed','candidates':record,'selected_utc':pd.Timestamp.now(tz='UTC').isoformat()})
    pd.DataFrame(predictions).to_csv(OUT/'test_predictions.csv',index=False)
    print('PRESELECTED CHAMPION',champion,flush=True)

def evaluate():
    if (OUT/'test_results.json').exists():raise RuntimeError('Final test already evaluated. No repeated selection or silent overwrite.')
    selection=read_json(OUT/'selection.json');d=data();s=pd.read_csv(OUT/'splits.csv',dtype={'group':str})
    test=d[s.partition=='test'].reset_index(drop=True);groups=s.loc[s.partition=='test','group'].to_numpy();y=test[TARGET].to_numpy()
    pred=pd.read_csv(OUT/'test_predictions.csv');assert np.array_equal(test.ID,pred.ID)
    for aux_path in [OUT/'tabpfn_test_predictions.csv',OUT/'tabpfn_v3_5_test_predictions.csv']:
        if aux_path.exists():
            aux=pd.read_csv(aux_path);assert np.array_equal(pred.ID,aux.ID)
            pred=pred.merge(aux,on='ID',validate='one_to_one')
    rows=[]
    for name in pred.columns:
        if name=='ID':continue
        p=pred[name].to_numpy();m=metrics(y,p)
        # Joint intercept/slope on held-out logits, descriptive only, not a new calibration.
        cs=LogisticRegression(C=1e6,max_iter=1000).fit(logit(p),y)
        m.update(model=name,track='auxiliary_1000_fit' if name.startswith('aux_') else 'main',gini=2*m['roc_auc']-1,
                 calibration_intercept=float(cs.intercept_[0]),calibration_slope=float(cs.coef_[0,0]))
        rows.append(m)
    champion=selection['champion'];cp=pred[champion].to_numpy();bp=pred.logistic.to_numpy()
    uniq,inverse=np.unique(groups,return_inverse=True);rng=np.random.default_rng(SEED)
    boot=[]
    for _ in range(300):
        counts=np.bincount(rng.integers(0,len(uniq),len(uniq)),minlength=len(uniq));w=counts[inverse]
        cm=metrics(y,cp,w);bm=metrics(y,bp,w)
        boot.append({**cm,'auc_minus_logistic':cm['roc_auc']-bm['roc_auc'],'log_loss_minus_logistic':cm['log_loss']-bm['log_loss']})
    ci={k:list(map(float,np.quantile([b[k] for b in boot],[.025,.975]))) for k in boot[0]}
    subgroup=[]
    for feature in ['SEX','EDUCATION','MARRIAGE']:
        for value in sorted(test[feature].unique()):
            mask=(test[feature]==value).to_numpy();yy=y[mask];pp=cp[mask]
            row={'feature':feature,'value':int(value),'rows':int(mask.sum()),'events':int(yy.sum()),'mean_prediction':float(pp.mean()),'event_rate':float(yy.mean())}
            if len(np.unique(yy))==2:row.update(metrics(yy,pp))
            subgroup.append(row)
    result={'champion_preselected':champion,'n_test':len(y),'test_events':int(y.sum()),'test_prevalence':float(y.mean()),'results':rows,'champion_bootstrap_95_intervals':ci,'bootstrap_unit':'identical-predictor group, 300 replicates; descriptive within-cohort uncertainty','subgroups':subgroup,'no_test_reselection':True,'not_temporal_validation':True}
    write_json(OUT/'test_results.json',result)
    pd.DataFrame(rows).to_csv(OUT/'metrics.csv',index=False)
    pd.DataFrame(subgroup).to_csv(OUT/'subgroups.csv',index=False)
    plot(test,pred,champion)
    print(pd.DataFrame(rows)[['model','roc_auc','average_precision','log_loss','brier']].to_string(index=False),flush=True)

def plot(test,pred,champion):
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from sklearn.calibration import calibration_curve
    from sklearn.metrics import RocCurveDisplay,PrecisionRecallDisplay
    y=test[TARGET];fig,axes=plt.subplots(1,3,figsize=(15,4.4))
    for name in ['logistic','catboost','lightgbm','ebm','catboost_behavior']:
        p=pred[name]
        RocCurveDisplay.from_predictions(y,p,name=name,ax=axes[0])
        PrecisionRecallDisplay.from_predictions(y,p,name=name,ax=axes[1])
        observed,mean=calibration_curve(y,p,n_bins=10,strategy='quantile')
        axes[2].plot(mean,observed,'o-',label=name)
    axes[2].plot([0,1],[0,1],'k--');axes[2].set(xlabel='Mean predicted probability',ylabel='Observed event rate',title='Calibration (quantile bins)');axes[2].legend(fontsize=8)
    axes[1].axhline(y.mean(),color='gray',linestyle='--');fig.suptitle(f'UCI within-cohort test | preselected: {champion} | not temporal / Thai-bank validation')
    fig.tight_layout();fig.savefig(OUT/'evaluation.png',dpi=170);plt.close(fig)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['prepare','train','evaluate']);args=parser.parse_args()
    {'prepare':prepare,'train':train,'evaluate':evaluate}[args.stage]()

if __name__=='__main__':main()
