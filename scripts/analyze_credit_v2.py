"""Compare locked development results and exposed references, no reselection."""
import hashlib
import joblib
import numpy as np
import pandas as pd
from credit_experiment import ROOT,OUT as OLD,TARGET,CATS,data,metrics,read_json,write_json
from credit_research_v2 import OUT,SEED
from credit_features_v2 import trajectory_features,DEMOGRAPHICS
from failure_analysis import slices,individual_loss,threshold_stats
from score_v2 import score
from sklearn.metrics import precision_recall_curve

def paired_bootstrap(y,a,b,groups,repetitions=300):
    unique,inverse=np.unique(groups,return_inverse=True);rng=np.random.default_rng(SEED);rows=[]
    for _ in range(repetitions):
        count=np.bincount(rng.integers(0,len(unique),len(unique)),minlength=len(unique));w=count[inverse]
        ma=metrics(y,a,w);mb=metrics(y,b,w);rows.append({k:ma[k]-mb[k] for k in ma})
    return {k:np.quantile([r[k] for r in rows],[.025,.975]).tolist() for k in rows[0]}

def main():
    if (OUT/'analysis.json').exists():raise RuntimeError('Analysis already recorded; preserve it.')
    d=data();f=pd.read_csv(OUT/'folds.csv',dtype={'group':str});selection=read_json(OUT/'selection.json');proto=read_json(OUT/'protocol.json')
    for path,digest in proto['sha256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    fit=np.flatnonzero(f.original_partition=='fit');oof=pd.read_csv(OUT/'selected_oof.csv');assert np.array_equal(oof.ID,d.ID.iloc[fit])
    for config in proto['candidate_grid']:
        ps=pd.read_csv(OUT/'cv'/config['name']/'oof.csv');assert np.array_equal(ps.ID,d.ID.iloc[fit]);assert np.isfinite(ps.probability).all() and ps.probability.between(0,1).all()
        for k in range(3):assert not set(f.group[(f.original_partition=='fit')&(f.cv_fold==k)])&set(f.group[(f.original_partition=='fit')&(f.cv_fold!=k)])
    # A changed ID or target must not change engineered predictors.
    probe=d.iloc[:40].copy();changed=probe.copy();changed['ID']=-1;changed[TARGET]=1-changed[TARGET]
    for variant in ['behavior','trajectory','trajectory_no_demographics']:
        pd.testing.assert_frame_equal(trajectory_features(probe,variant),trajectory_features(changed,variant))
        pd.testing.assert_frame_equal(trajectory_features(probe,variant),pd.concat([trajectory_features(probe.iloc[[j]],variant) for j in range(len(probe))]))
    assert not set(DEMOGRAPHICS)&set(trajectory_features(probe,'trajectory_no_demographics').columns)
    old_results=read_json(OLD/'test_results.json');legacy=next(r for r in old_results['results'] if r['model']=='catboost_behavior')
    aux=read_json(OUT/'tabpfn_4000_results.json');aux_predictions=pd.read_csv(OUT/'tabpfn_4000_predictions.csv');aux_test=np.flatnonzero(f.original_partition=='test')
    assert np.array_equal(aux_predictions.ID,d.ID.iloc[aux_test])
    for trial in aux['trials']:
        if trial['status']!='ok':continue
        p=aux_predictions[trial['model']].to_numpy();assert np.isfinite(p).all() and ((p>=0)&(p<=1)).all()
        recomputed=metrics(d[TARGET].to_numpy()[aux_test],p)
        for key,value in recomputed.items():assert np.isclose(value,trial['exposed_test_reference'][key],rtol=1e-6,atol=1e-7)
    intervals={'selected_oof_minus_cv_reference':paired_bootstrap(d[TARGET].to_numpy()[fit],oof.candidate.to_numpy(),oof.reference.to_numpy(),f.group.iloc[fit].to_numpy())}
    part_predictions={};rows=[];capacities=[];thresholds=[]
    validation=np.flatnonzero(f.original_partition=='validation');test=np.flatnonzero(f.original_partition=='test')
    v2val=pd.read_csv(OUT/'candidate_blend_validation_predictions.csv');assert np.array_equal(v2val.ID,d.ID.iloc[validation]);vy=d[TARGET].to_numpy()[validation]
    precision,recall,ts=precision_recall_curve(vy,v2val.probability);threshold=float(ts[np.flatnonzero(recall[:-1]>=.7)[-1]])
    oldval=pd.read_csv(ROOT/'outputs/failure_analysis_v1/validation_predictions.csv');oldtest=pd.read_csv(OLD/'test_predictions.csv')
    for part,ix,old in [('validation',validation,oldval),('test',test,oldtest)]:
        candidate=pd.read_csv(OUT/f'candidate_blend_{part}_predictions.csv');ref=pd.read_csv(OUT/f'reference_v1_{part}_predictions.csv');frame=d.iloc[ix].reset_index(drop=True);y=frame[TARGET].to_numpy()
        assert np.array_equal(frame.ID,candidate.ID) and np.array_equal(frame.ID,old.ID) and np.array_equal(frame.ID,ref.ID)
        ps={'candidate':candidate.probability.to_numpy(),'cv_reference_refit':ref.probability.to_numpy(),'legacy_v1_champion':old.catboost_behavior.to_numpy()};part_predictions[part]=ps
        intervals[f'exposed_{part}_candidate_minus_legacy_v1']=paired_bootstrap(y,ps['candidate'],ps['legacy_v1_champion'],f.group.iloc[ix].to_numpy())
        for name,mask in slices(frame).items():
            if mask.sum()<30 or len(np.unique(y[mask]))<2:continue
            cm=metrics(y[mask],ps['candidate'][mask]);bm=metrics(y[mask],ps['legacy_v1_champion'][mask])
            rows.append({'partition':'exposed_'+part,'slice':name,'rows':int(mask.sum()),'events':int(y[mask].sum()),'candidate_log_loss':cm['log_loss'],'legacy_log_loss':bm['log_loss'],'log_loss_delta':cm['log_loss']-bm['log_loss'],'candidate_auc':cm['roc_auc'],'legacy_auc':bm['roc_auc'],'small_slice':mask.sum()<200 or y[mask].sum()<30})
        for name,p in ps.items():
            thresholds.append({'partition':'exposed_'+part,'model':name,'operating_point':'threshold_0.5',**threshold_stats(y,p,.5)})
            if name=='candidate':thresholds.append({'partition':'exposed_'+part,'model':name,'operating_point':'validation_recall70_threshold',**threshold_stats(y,p,threshold)})
            for capacity in [.1,.2,.3,.4,.5]:
                k=int(np.ceil(len(y)*capacity));top=np.argsort(-p,kind='stable')[:k];events=int(y[top].sum())
                capacities.append({'partition':'exposed_'+part,'model':name,'capacity':capacity,'flagged':k,'events_captured':events,'recall':events/int(y.sum()),'precision':events/k})
    bundle=joblib.load(OUT/'models/pipeline.joblib');demo=d.drop(columns=['ID',TARGET]).iloc[test[:12]];result=score(demo,bundle)
    assert np.array_equal(result.index,demo.index)
    assert read_json(OUT/'reference_results.json')['selection_sha256']==hashlib.sha256((OUT/'selection.json').read_bytes()).hexdigest()
    key='candidate' if bundle['selected_pipeline']=='blend' else 'cv_reference_refit'
    assert np.allclose(result.calibrated_probability,part_predictions['test'][key][:12],rtol=1e-10,atol=1e-12)
    demo.to_csv(OUT/'demo_input.csv',index=False);result.to_csv(OUT/'demo_scores.csv',index=False)
    # Aggregate feature influence is a model diagnostic, not causal attribution.
    cb=bundle['models'][bundle['catboost']]['model'];columns=bundle['models'][bundle['catboost']]['columns']
    importance=pd.DataFrame({'feature':columns,'prediction_values_change':cb.get_feature_importance()}).sort_values('prediction_values_change',ascending=False);importance.to_csv(OUT/'catboost_feature_importance.csv',index=False)
    pd.DataFrame(rows).to_csv(OUT/'failure_slices_comparison.csv',index=False);pd.DataFrame(capacities).to_csv(OUT/'capacity_comparison.csv',index=False);pd.DataFrame(thresholds).to_csv(OUT/'threshold_comparison.csv',index=False)
    analysis={'legacy_v1_metrics':legacy,'paired_bootstrap_95_difference_intervals':intervals,'bootstrap_replicates':300,'bootstrap_unit':'exact predictor-vector group','interval_scope':'Descriptive conditional on selected pipeline; does not account for model selection, overlapping-fold training dependence, or prior exposure. Not independent significance evidence.',
      'selected_pipeline':selection['selected_pipeline'],'gate_passed':selection['promotion_gate_passed'],'candidate_recall70_threshold':threshold,
      'reference_seed_note':'CV reference uses same recipe as v1 but common v2 seed20261005; legacy v1 artifact has seed20261004. Report both anchors rather than silently equating weights.',
      'verification':{'v1_artifacts_and_data_hashes_unchanged':True,'all_nine_oof_same_ids_finite_probabilities':True,'cv_groups_disjoint':True,'id_target_excluded_from_features':True,'single_row_batch_feature_parity':True,'no_demographics_variant_excludes_four_columns':True,'pipeline_reload_scoring_prediction_parity':True,'auxiliary_ids_probabilities_and_recomputed_metrics_match':True,'selection_frozen_before_reference_evaluation':read_json(OUT/'reference_results.json')['selection_unchanged'],'references_are_exposed':True}}
    write_json(OUT/'analysis.json',analysis);plot(part_predictions,d,validation,test,selection);print(analysis['verification'],flush=True)

def plot(ps,d,val,test,selection):
    import matplotlib;matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from sklearn.calibration import calibration_curve
    fig,axes=plt.subplots(2,2,figsize=(12,8))
    cap=pd.read_csv(OUT/'capacity_comparison.csv');ss=cap[cap.partition=='exposed_test']
    for name,color in [('legacy_v1_champion','#65758b'),('candidate','#147d92')]:
        q=ss[ss.model==name];axes[0,0].plot(q.capacity*100,q.recall*100,'o-',label=name,color=color)
        observed,predicted=calibration_curve(d[TARGET].to_numpy()[test],ps['test'][name],n_bins=10,strategy='quantile');axes[0,1].plot(predicted,observed,'o-',label=name,color=color)
    axes[0,0].set(xlabel='Reviewed records (%)',ylabel='Events captured (%)',title='Exposed test: capacity trade-off');axes[0,0].legend(fontsize=8)
    axes[0,1].plot([0,1],[0,1],'--',color='gray');axes[0,1].set(xlabel='Mean predicted risk',ylabel='Observed event rate',title='Exposed test: calibration');axes[0,1].legend(fontsize=8)
    folds=[pd.read_csv(OUT/'cv'/c['name']/'oof.csv').probability.to_numpy() for c in read_json(OUT/'protocol.json')['candidate_grid']]
    names=[c['name'] for c in read_json(OUT/'protocol.json')['candidate_grid']];ix=np.flatnonzero(pd.read_csv(OUT/'folds.csv').original_partition=='fit');loss=[metrics(d[TARGET].to_numpy()[ix],p)['log_loss'] for p in folds]
    axes[1,0].barh(names,loss,color=['#65758b' if n=='reference_v1' else '#147d92' for n in names]);axes[1,0].invert_yaxis();axes[1,0].set(xlabel='OOF log loss (lower is better)',title='Development model-selection scores');axes[1,0].set_xlim(min(loss)-.004,max(loss)+.002);axes[1,0].tick_params(axis='y',labelsize=8)
    name=selection['best_catboost'];path=OUT/'cv'/name/'learning_curve_0.json'
    if path.exists():
        curve=read_json(path)
        for part,values in curve.items():axes[1,1].plot(np.arange(1,len(values['Logloss'])+1),values['Logloss'],label=part)
        axes[1,1].legend(fontsize=8);axes[1,1].set(xlabel='Fixed iterations',ylabel='Log loss',title=f'Fold 0 curve: {name}')
    fig.suptitle('Round 2 development research - no new independent holdout',fontsize=13);fig.tight_layout();fig.savefig(OUT/'development_diagnostics.png',dpi=160);plt.close(fig)

if __name__=='__main__':main()
