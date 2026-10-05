"""Check local V3.5 access without exposing credentials or using test data."""
import os
os.environ['TABPFN_NO_BROWSER']='1'
os.environ['TABPFN_DISABLE_TELEMETRY']='1'
import json
import time
from pathlib import Path
import numpy as np
import torch
from dotenv import load_dotenv
from tabpfn import TabPFNClassifier
from tabpfn.constants import ModelVersion
ROOT=Path(__file__).resolve().parents[1]
load_dotenv(ROOT/'.env',encoding='utf-8-sig')

if __name__=='__main__':
    torch.set_num_threads(4)
    rng=np.random.default_rng(42);x=rng.normal(size=(40,5));y=np.arange(40)%2
    result={'version':'v3.5','stage':'synthetic_smoke_only','token_in_environment':bool(os.environ.get('TABPFN_TOKEN'))}
    try:
        start=time.perf_counter()
        model=TabPFNClassifier.create_default_for_version(ModelVersion.V3_5,device='cpu',n_estimators=1,n_jobs=4)
        model.fit(x[:32],y[:32]);p=model.predict_proba(x[32:])
        result.update(status='ok',elapsed_seconds=time.perf_counter()-start,output_shape=list(p.shape))
    except Exception as e:
        # Do not dump the exception text, which could contain URLs or authentication data.
        result.update(status='blocked',exception=type(e).__name__)
    folder=ROOT/'outputs/diagnostics';folder.mkdir(exist_ok=True)
    previous=folder/'tabpfn_3_5_smoke.json'
    initial=folder/'tabpfn_3_5_initial_smoke.json'
    if previous.exists() and not initial.exists():initial.write_bytes(previous.read_bytes())
    previous.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result),flush=True)
