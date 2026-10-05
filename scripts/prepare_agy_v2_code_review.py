"""Supply only selected source code and protocol to the requested agy reviewer."""
import ast
from pathlib import Path
from credit_experiment import ROOT
from credit_research_v2 import OUT

pieces=['NO TOOLS. Read only supplied source code/protocol. Do not execute, browse, inspect files or edit. Thai adversarial code/scientific review: identify concrete bugs affecting data leakage, feature definitions, OOF selection, calibration, artifact scoring and reporting. Do not invent test execution. All original partitions have already been used; Round2 scores are development or exposed retrospective references, not new holdout. Grid already frozen and training running; fixes may repair bugs, not add hyperparameters or tune on results. Reference recipe uses v2 common seed and legacy v1 artifact is a separate anchor. State line references from supplied headings and recommend necessary fixes only.']
pieces.append((OUT/'protocol.json').read_text(encoding='utf-8'))
for filename,names in [('credit_features_v2.py',None),('credit_research_v2.py',{'model_for','cv_candidate','select','finalize'}),('score_v2.py',{'score'})]:
    path=ROOT/'scripts'/filename;source=path.read_text(encoding='utf-8')
    if names is None:pieces.append(f'FILE scripts/{filename}:1\n'+source)
    else:
        tree=ast.parse(source)
        for node in tree.body:
            if isinstance(node,ast.FunctionDef) and node.name in names:pieces.append(f'FILE scripts/{filename}:{node.lineno}\n'+ast.get_source_segment(source,node))
text='\n\n'.join(pieces)
assert len(text)<29000
(ROOT/'research/AGY_V2_CODE_REVIEW_PROMPT.txt').write_text(text,encoding='utf-8')
print('Prompt characters:',len(text))
