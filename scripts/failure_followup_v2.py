"""Post-selection diagnosis of unresolved slices and curve saturation; no retuning."""
import numpy as np
import pandas as pd
from credit_experiment import OUT as OLD,TARGET,data,read_json,write_json,metrics
from credit_research_v2 import OUT
from failure_analysis import slices,threshold_stats

if __name__=='__main__':
    destination=OUT/'failure_followup.json'
    if destination.exists():raise RuntimeError('Follow-up already recorded.')
    d=data();f=pd.read_csv(OUT/'folds.csv');test=d[f.original_partition=='test'].reset_index(drop=True)
    old=pd.read_csv(OLD/'test_predictions.csv');new=pd.read_csv(OUT/'candidate_blend_test_predictions.csv')
    assert np.array_equal(test.ID,old.ID) and np.array_equal(test.ID,new.ID)
    y=test[TARGET].to_numpy();rows=[]
    for name in ['no_positive_pay_code','any_positive_pay_code','PAY_0=1','bill1_nonpositive','zero_payments_3plus']:
        mask=slices(test)[name];yy=y[mask]
        for model,pp in [('legacy_v1',old.catboost_behavior.to_numpy()),('candidate',new.probability.to_numpy())]:
            p=pp[mask];rows.append({'slice':name,'model':model,'rows':int(mask.sum()),'events':int(yy.sum()),'mean_probability':float(p.mean()),'event_rate':float(yy.mean()),'metrics':metrics(yy,p),'threshold_0.5':threshold_stats(yy,p,.5)})
    curves=[]
    for path in sorted((OUT/'cv').glob('*/learning_curve_*.json')):
        result=read_json(path);hold=np.asarray(result['validation']['Logloss']);train=np.asarray(result['learn']['Logloss']);best=int(np.argmin(hold))
        curves.append({'candidate':path.parent.name,'fold':int(path.stem.split('_')[-1]),'fixed_iterations':len(hold),'heldout_min_iteration_posthoc':best+1,'heldout_min_loss':float(hold[best]),'heldout_final_loss':float(hold[-1]),'heldout_final_minus_min':float(hold[-1]-hold[best]),'train_final_loss':float(train[-1])})
    pd.DataFrame(curves).to_csv(OUT/'learning_curve_diagnostics.csv',index=False)
    chosen=read_json(OUT/'selection.json')['best_catboost']
    write_json(destination,{'slice_comparison':rows,'selected_catboost_curve_diagnostics':[r for r in curves if r['candidate']==chosen],
       'scope':'Retrospective exploratory diagnosis from exposed reference and outer CV curves. Best curve iteration is posthoc only, not used to refit, change settings or reselect. No causal or unbiased significance claim.'})
    print(destination)
