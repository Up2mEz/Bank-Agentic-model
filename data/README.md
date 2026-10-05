# Data provenance

The experiment uses I-Cheng Yeh's **Default of Credit Card Clients** dataset:
[UCI dataset](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients),
[DOI 10.24432/C55S3H](https://doi.org/10.24432/C55S3H), CC BY 4.0.
The public [Kaggle mirror](https://www.kaggle.com/datasets/uciml/default-of-credit-card-clients-dataset)
was compared against both the original XLS and UCI CSV: zero differing cells.
See `reports/v1/data_audit.json` for the snapshots, hashes and exact checks.

Raw files are downloaded locally with `python scripts/fetch_data.py` and are excluded
from Git. Files under `reports/v2` with IDs, vector-group hashes or OOF probabilities
are **derived research data**, attributed to the same UCI source. Group hashes identify
identical observed feature vectors; they do not establish borrower identity.

The mirror metadata says CC0. This project retains original UCI CC BY attribution
rather than assuming the uploader can relicense the original data. The raw dataset,
third-party libraries and TabPFN weights retain their own licenses and terms.

Dataset limits: Taiwan, 2005, existing cardholders, next-month dataset outcome;
the precise default threshold is unverified. There is no Thai-bank cohort, rejected
applicant cohort or new independent temporal test in this repository.
