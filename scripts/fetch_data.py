"""Fetch public original and Kaggle mirror; preserve existing snapshots."""
import hashlib
import json
import zipfile
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]

def fetch(url,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists() or path.stat().st_size==0:
        response=requests.get(url,timeout=(15,120));response.raise_for_status()
        temporary=path.with_suffix(path.suffix+'.partial')
        temporary.write_bytes(response.content);temporary.replace(path)
    print(path.relative_to(ROOT),path.stat().st_size,hashlib.sha256(path.read_bytes()).hexdigest())

def unzip(path,folder):
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            target=(folder/name).resolve()
            if not target.is_relative_to(folder.resolve()):raise ValueError('Unsafe archive path')
        archive.extractall(folder)

if __name__=='__main__':
    u=ROOT/'data/raw/uci_credit_card';k=ROOT/'data/raw/kaggle_credit_card'
    fetch('https://archive.ics.uci.edu/api/dataset?id=350',u/'uci_metadata.json')
    metadata=json.loads((u/'uci_metadata.json').read_text())['data']
    fetch(metadata['data_url'],u/'data.csv')
    fetch('https://archive.ics.uci.edu/static/public/350/default%2Bof%2Bcredit%2Bcard%2Bclients.zip',u/'original.zip')
    fetch('https://www.kaggle.com/api/v1/datasets/view/uciml/default-of-credit-card-clients-dataset',k/'kaggle_metadata.json')
    fetch('https://www.kaggle.com/api/v1/datasets/download/uciml/default-of-credit-card-clients-dataset',k/'kaggle_credit_card.zip')
    unzip(u/'original.zip',u);unzip(k/'kaggle_credit_card.zip',k)
