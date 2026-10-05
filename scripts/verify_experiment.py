"""Meaningful integrity checks for split leakage, snapshot parity and saved scoring."""
import json
import subprocess
import sys
from pathlib import Path
import numpy as np
import pandas as pd
from credit_experiment import OUT,ROOT,TARGET,data,read_json

def main():
    d=data();s=pd.read_csv(OUT/'splits.csv',dtype={'group':str});audit=read_json(OUT/'data_audit.json')
    assert audit['source_value_mismatches']==0 and audit['original_xls_value_mismatches']==0
    assert set(s.ID)==set(d.ID) and s.ID.is_unique
    assert s.groupby('group').partition.nunique().max()==1
    parts={p:set(s.loc[s.partition==p,'ID']) for p in s.partition.unique()}
    for i,p in enumerate(parts):
        for q in list(parts)[i+1:]:assert not parts[p]&parts[q]
    selection=read_json(OUT/'selection.json');results=read_json(OUT/'test_results.json')
    assert selection['champion']==results['champion_preselected'] and results['no_test_reselection']
    assert all(r['artifact_reload_parity']=='passed' for r in selection['candidates'])
    pred=pd.read_csv(OUT/'test_predictions.csv');assert set(pred.ID)==parts['test']
    assert np.isfinite(pred.drop(columns='ID').to_numpy()).all()
    assert ((pred.drop(columns='ID')>=0)&(pred.drop(columns='ID')<=1)).all().all()
    sample=d[d.ID.isin(pred.ID)].head(5).drop(columns=['ID',TARGET])
    sample.to_csv(OUT/'demo_input.csv',index=False)
    subprocess.run([sys.executable,str(ROOT/'scripts/score.py'),str(OUT/'demo_input.csv')],check=True)
    scores=pd.read_csv(OUT/'demo_scores.csv');expected=pred.set_index('ID').loc[d[d.ID.isin(pred.ID)].head(5).ID,selection['champion']]
    np.testing.assert_allclose(scores.calibrated_probability,expected,rtol=1e-9,atol=1e-12)
    evidence={'cross_source_numeric_cell_parity':'passed for UCI CSV + original XLS + Kaggle CSV','id_and_exact_predictor_group_separation':'passed','all_partitions_disjoint':'passed','all_main_artifact_reload_parity':'passed','probability_domain':'passed','demo_vs_saved_test_predictions':'passed','preselected_champion_preserved':'passed'}
    (OUT/'verification.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
    print(json.dumps(evidence),flush=True)

if __name__=='__main__':main()
