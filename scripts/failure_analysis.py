"""Retrospective failure analysis; never creates a fresh test claim."""
from pathlib import Path
import hashlib
import joblib
import numpy as np
import pandas as pd
from sklearn.metrics import confusion_matrix, precision_recall_curve
from credit_experiment import ROOT, OUT, TARGET, data, features, probability, calibrated, metrics, read_json, write_json

DEST=ROOT/'outputs/failure_analysis_v1'

def individual_loss(y,p):
    p=np.clip(p,1e-7,1-1e-7)
    return -(y*np.log(p)+(1-y)*np.log1p(-p))

def threshold_stats(y,p,threshold):
    tn,fp,fn,tp=confusion_matrix(y,p>=threshold,labels=[0,1]).ravel()
    return {'threshold':float(threshold),'tn':int(tn),'fp':int(fp),'fn':int(fn),'tp':int(tp),
            'recall':float(tp/(tp+fn)),'precision':float(tp/(tp+fp)) if tp+fp else 0.,
            'flagged_rate':float((tp+fp)/len(y)),'false_positive_rate':float(fp/(fp+tn))}

def slices(d):
    pay=d[['PAY_0','PAY_2','PAY_3','PAY_4','PAY_5','PAY_6']].to_numpy()
    ans={f'PAY_0={v}':(d.PAY_0==v).to_numpy() for v in sorted(d.PAY_0.unique())}
    ans.update({'any_positive_pay_code':(pay>0).any(axis=1),'no_positive_pay_code':~(pay>0).any(axis=1),
                'recent_code_ge_2':(d.PAY_0>=2).to_numpy(),'any_code_ge_2':(pay>=2).any(axis=1),
                'bill1_nonpositive':(d.BILL_AMT1<=0).to_numpy(),
                'zero_payments_3plus':(d[[f'PAY_AMT{i}' for i in range(1,7)]]==0).sum(axis=1).ge(3).to_numpy(),
                'utilization_gt_1':(d.BILL_AMT1/d.LIMIT_BAL>1).to_numpy(),
                'utilization_le_0.3':(d.BILL_AMT1/d.LIMIT_BAL<=.3).to_numpy(),
                'unknown_education_or_marriage':(d.EDUCATION.isin([0,5,6])|d.MARRIAGE.eq(0)).to_numpy()})
    for col in ['SEX','EDUCATION','MARRIAGE']:
        ans.update({f'{col}={v}':(d[col]==v).to_numpy() for v in sorted(d[col].unique())})
    return ans

def main():
    if (DEST/'summary.json').exists():raise RuntimeError('Preserve completed failure analysis.')
    DEST.mkdir(parents=True,exist_ok=True)
    d=data();s=pd.read_csv(OUT/'splits.csv',dtype={'group':str});selection=read_json(OUT/'selection.json')
    champ=selection['champion'];pred={};models={}
    for name in ['logistic','catboost','lightgbm','ebm',champ]:
        bundle=joblib.load(OUT/'models'/f'{name}.joblib');models[name]=bundle
        ix=np.flatnonzero(s.partition=='validation');x=features(d,bundle['variant'])
        pred[name]=calibrated(bundle['calibration_kind'],bundle['calibrator'],probability(bundle['model'],x.iloc[ix]))
    validation=d.iloc[ix].reset_index(drop=True);vy=validation[TARGET].to_numpy();vp=pred[champ]
    precision,recall,thresholds=precision_recall_curve(vy,vp)
    valid=np.flatnonzero(recall[:-1]>=.7);threshold=float(thresholds[valid[-1]])
    parts={'validation':(validation,pd.DataFrame(pred))}
    ti=np.flatnonzero(s.partition=='test');test=d.iloc[ti].reset_index(drop=True)
    test_pred=pd.read_csv(OUT/'test_predictions.csv');assert np.array_equal(test.ID,test_pred.ID)
    for path in ['tabpfn_test_predictions.csv','tabpfn_v3_5_test_predictions.csv']:
        extra=pd.read_csv(OUT/path);assert np.array_equal(test.ID,extra.ID)
        test_pred=test_pred.merge(extra,on='ID',validate='one_to_one')
    parts['old_test_reference']=(test,test_pred)
    aggregate={};slice_rows=[];bins=[];capacities=[];examples=[];complement=[]
    for part,(frame,ps) in parts.items():
        y=frame[TARGET].to_numpy();p=ps[champ].to_numpy();loss=individual_loss(y,p)
        aggregate[part]={'rows':len(y),'events':int(y.sum()),'metrics':metrics(y,p),
          'threshold_0.5':threshold_stats(y,p,.5),'validation_recall70_threshold':threshold_stats(y,p,threshold),
          'loss_share_events':float(loss[y==1].sum()/loss.sum()),
          'top10pct_loss_share':float(np.sort(loss)[-int(np.ceil(len(y)*.1)):].sum()/loss.sum())}
        for name,mask in slices(frame).items():
            n=int(mask.sum());events=int(y[mask].sum())
            if not n:continue
            row={'partition':part,'slice':name,'rows':n,'events':events,'event_rate':float(y[mask].mean()),
                 'mean_prediction':float(p[mask].mean()),'mean_log_loss':float(loss[mask].mean()),
                 'total_loss_share':float(loss[mask].sum()/loss.sum()),
                 'fn_at_0.5':int(((y==1)&(p<.5)&mask).sum()),'fp_at_0.5':int(((y==0)&(p>=.5)&mask).sum()),
                 'small_slice':n<200 or events<30}
            if len(np.unique(y[mask]))==2:row.update(metrics(y[mask],p[mask]))
            slice_rows.append(row)
        for lo,hi in zip(np.arange(0,1,.1),np.arange(.1,1.1,.1)):
            mask=(p>=lo)&(p<hi if hi<1 else p<=1)
            if mask.sum():bins.append({'partition':part,'low':lo,'high':min(hi,1.),'rows':int(mask.sum()),'mean_prediction':float(p[mask].mean()),'event_rate':float(y[mask].mean()),'events':int(y[mask].sum())})
        for fraction in [.1,.2,.3,.4,.5]:
            k=int(np.ceil(len(y)*fraction));order=np.argsort(-p,kind='stable')[:k];captured=int(y[order].sum())
            capacities.append({'partition':part,'review_capacity':fraction,'flagged_rows':k,'events_captured':captured,'recall':captured/int(y.sum()),'precision':captured/k,'non_events_flagged':k-captured})
        for j in np.argsort(-loss)[:50]:
            examples.append({'partition':part,'ID':int(frame.ID.iloc[j]),'label':int(y[j]),'probability':float(p[j]),'log_loss':float(loss[j]),'PAY_0':int(frame.PAY_0.iloc[j]),'LIMIT_BAL':int(frame.LIMIT_BAL.iloc[j]),'BILL_AMT1':int(frame.BILL_AMT1.iloc[j]),'PAY_AMT1':int(frame.PAY_AMT1.iloc[j])})
        for name in [c for c in ps if c!='ID' and c!=champ and not c.endswith('__raw')]:
            q=ps[name].to_numpy();qloss=individual_loss(y,q)
            hard=loss>=np.quantile(loss,.9)
            complement.append({'partition':part,'model':name,'probability_correlation':float(np.corrcoef(p,q)[0,1]),
              'whole_log_loss':float(qloss.mean()),'champion_top_loss_decile_mean_loss':float(qloss[hard].mean()),
              'champion_top_loss_decile_better_rows':int((qloss[hard]<loss[hard]).sum()),'rows_in_decile':int(hard.sum())})
    for name,rows in [('slices',slice_rows),('calibration_bins',bins),('capacity',capacities),('largest_losses',examples),('complementarity',complement)]:
        pd.DataFrame(rows).to_csv(DEST/f'{name}.csv',index=False)
    original=d.drop(columns=['ID',TARGET]);group=pd.util.hash_pandas_object(original,index=False).astype(str)
    gg=pd.DataFrame({'g':group,'y':d[TARGET]}).groupby('g').y.agg(['size','nunique','sum'])
    contradictory=gg[gg['nunique']>1]
    ambiguity={'conflicting_exact_vector_groups':len(contradictory),'rows_in_those_groups':int(contradictory['size'].sum()),
       'minimum_deterministic_classification_errors_on_observed_exact_groups':int(np.minimum(contradictory['sum'],contradictory['size']-contradictory['sum']).sum()),
       'interpretation':'Observed feature/label ambiguity, not a proven population Bayes-error floor; do not relabel or delete these records.'}
    write_json(DEST/'summary.json',{'champion':champ,'threshold_chosen_from_validation_for_recall70':threshold,'partitions':aggregate,'exact_vector_ambiguity':ambiguity,
      'scope':'Retrospective analysis of already used validation and already opened test; not new unbiased evidence. Slices overlap; do not sum their loss shares.',
      'sha256':{name:hashlib.sha256((OUT/name).read_bytes()).hexdigest() for name in ['protocol.json','selection.json','test_results.json','splits.csv']}})
    pd.DataFrame({'ID':validation.ID,**pred}).to_csv(DEST/'validation_predictions.csv',index=False)
    print(aggregate,flush=True)

if __name__=='__main__':main()
