"""Within-row, pre-outcome trajectory features. No fitted or label-based transforms."""
import numpy as np
from credit_experiment import features

PAY_CODES=['PAY_0','PAY_2','PAY_3','PAY_4','PAY_5','PAY_6']
DEMOGRAPHICS=['SEX','EDUCATION','MARRIAGE','AGE']

def trajectory_features(d,variant='trajectory'):
    x=features(d,'behavior')
    if variant=='behavior':return x
    limit=d.LIMIT_BAL.where(d.LIMIT_BAL>0)
    code=d[PAY_CODES].to_numpy(dtype=float)
    positive=np.maximum(code,0)  # Encodes documented positive codes only; not a meaning for negative/zero codes.
    x['positive_code_count']=(code>0).sum(axis=1)
    x['code_ge2_count']=(code>=2).sum(axis=1)
    x['max_positive_code']=positive.max(axis=1)
    x['mean_positive_code']=positive.mean(axis=1)
    x['latest_positive_minus_prior_mean']=positive[:,0]-positive[:,1:].mean(axis=1)
    x['latest_positive_minus_prior_max']=positive[:,0]-positive[:,1:].max(axis=1)
    x['adjacent_positive_pairs']=((code[:,:-1]>0)&(code[:,1:]>0)).sum(axis=1)
    x['recent_positive_code_count']=(code[:,:3]>0).sum(axis=1)
    bills=d[[f'BILL_AMT{i}' for i in range(1,7)]].to_numpy(dtype=float)
    payments=d[[f'PAY_AMT{i}' for i in range(1,7)]].to_numpy(dtype=float)
    for i in range(1,7):
        x[f'bill_limit_ratio_{i}']=d[f'BILL_AMT{i}']/limit
        x[f'payment_limit_ratio_{i}']=d[f'PAY_AMT{i}']/limit
    x['zero_payment_count']=(payments==0).sum(axis=1)
    x['recent_zero_payment_count']=(payments[:,:3]==0).sum(axis=1)
    x['negative_bill_count']=(bills<0).sum(axis=1)
    x['bill_std_limit']=bills.std(axis=1)/limit
    x['bill_range_limit']=(bills.max(axis=1)-bills.min(axis=1))/limit
    x['payment_std_limit']=payments.std(axis=1)/limit
    x['payment_mean_limit']=payments.mean(axis=1)/limit
    # Oldest-to-latest monthly linear summary, not a claim of linear dynamics.
    t=np.arange(6,dtype=float);t-=t.mean()
    x['bill_slope_limit']=(bills[:,::-1]@t)/(t@t)/limit
    x['payment_slope_limit']=(payments[:,::-1]@t)/(t@t)/limit
    x['recent_bill_change_limit']=(bills[:,0]-bills[:,2])/limit
    denom=np.maximum(bills,0).sum(axis=1)
    x['sum_payment_over_sum_positive_bill']=np.divide(payments.sum(axis=1),denom,out=np.full(len(d),np.nan),where=denom>0)
    if variant=='trajectory_no_demographics':x=x.drop(columns=DEMOGRAPHICS)
    return x

FEATURE_NOTES={
 'positive_codes':'Only positive documented months-of-delay codes contribute to summaries. Zero/negative original codes remain separate categorical predictors; assigning zero contribution does not label these codes paid/current.',
 'ratios':'Same-month amount ratios are numeric summaries; no claim of matched bill settlement, balance rollover, cumulative debt or minimum-payment obligation.',
 'slopes':'Six equally spaced historical monthly snapshots ordered oldest to latest; linear summary divided by positive limit, with raw amount predictors retained.',
 'negative_bills':'Preserved, not automatically error or inferred refund/overpayment. Nonpositive-denominator ratios missing plus original flags.',
 'demographics':'A sensitivity ablation drops SEX, EDUCATION, MARRIAGE and AGE; not a proof of fairness or an underwriting policy.'}
