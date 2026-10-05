"""Run an explicitly requested native agy supplied-material review, no shell."""
import argparse
import json
import shutil
import subprocess
from pathlib import Path

p=argparse.ArgumentParser();p.add_argument('prompt');p.add_argument('output_prefix');args=p.parse_args()
prompt=Path(args.prompt).read_text(encoding='utf-8');dest=Path(args.output_prefix)
dest.parent.mkdir(parents=True,exist_ok=True)
executable=shutil.which('agy')
if not executable:raise RuntimeError('agy not available on PATH')
with Path(str(dest)+'.txt').open('w',encoding='utf-8') as out,Path(str(dest)+'.stderr.txt').open('w',encoding='utf-8') as err:
    try:
        result=subprocess.run([executable,'--print',prompt,'--mode','plan'],stdout=out,stderr=err,encoding='utf-8',timeout=300)
        code=result.returncode
    except subprocess.TimeoutExpired:
        code='timeout'
content=Path(str(dest)+'.txt').read_text(encoding='utf-8')
record={'exit_code':code,'nonempty_stdout':bool(content.strip()),'scope':'Review of supplied prompt material; no independent file/data inspection asserted','stdout_chars':len(content)}
Path(str(dest)+'.status.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record))
