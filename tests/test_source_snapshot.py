import json

import pytest

from creditrisk.artifacts import sha256
from tools.verify_input_sources import verify


def test_label_only_snapshot_change_cannot_reuse_old_oof(tmp_path):
    raw = tmp_path / "data/raw/kaggle_credit_card/UCI_Credit_Card.csv"
    protocol = tmp_path / "reports/v1/protocol.json"
    raw.parent.mkdir(parents=True)
    protocol.parent.mkdir(parents=True)
    raw.write_bytes(b"ID,label\n1,0\n2,1\n")
    protocol.write_text(json.dumps({"data_sha256": sha256(raw)}), encoding="utf-8")
    verify(tmp_path)
    raw.write_bytes(b"ID,label\n1,1\n2,0\n")
    with pytest.raises(ValueError, match="snapshot differs"):
        verify(tmp_path)
