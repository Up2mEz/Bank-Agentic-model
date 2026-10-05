# Reference and claim audit

Checked 2026-10-04. This is a bounded manual evidence audit for the accompanying research proposal. It is not a complete systematic review, citation-release certification, or independent replication. Source links below distinguish paper metadata, accessible content, and implementation documentation. Short excerpts identify the supporting claim; recommendations for this project remain our synthesis.

## 1. Credit scoring comparisons

**Lessmann, Stefan; Baesens, Bart; Seow, Hsin-Vonn; Thomas, Lyn C. (2015).** “Benchmarking state-of-the-art classification algorithms for credit scoring: An update of research.” *European Journal of Operational Research*, 247(1), 124–136. DOI: `10.1016/j.ejor.2015.05.030`.

- Metadata/content: [University of Southampton record](https://eprints.soton.ac.uk/377196/), [accepted manuscript](https://eprints.soton.ac.uk/377196/1/Lessmann_Benchmarking.pdf), [publisher DOI](https://doi.org/10.1016/j.ejor.2015.05.030).
- Evidence recorded from indexed manuscript content (paraphrase): the benchmark compares 41 classifiers on eight real-world credit scoring datasets. Later direct attempts to reopen the record and PDF returned HTTP 403; this does not constitute a fresh full-text reread.
- Supported use: serious credit scoring model comparison needs multiple datasets/criteria, rather than a single accuracy number.
- Boundary: this historical benchmark cannot identify the best 2026 algorithm for an unobserved Thai portfolio. Direct DOI-page resolution failed in this session; bibliographic resolution remains incomplete, not disproven.

## 2. Trees versus neural networks on tabular data

**Grinsztajn, Léo; Oyallon, Edouard; Varoquaux, Gaël (2022).** “Why do tree-based models still outperform deep learning on typical tabular data?” *NeurIPS 2022, Datasets and Benchmarks*.

- Metadata/content: [published proceedings](https://papers.neurips.cc/paper_files/paper/2022/hash/0378c7692da36807bdec87ab043cdadc-Abstract-Datasets_and_Benchmarks.html), [arXiv record](https://arxiv.org/abs/2207.08815), [published full text](https://papers.neurips.cc/paper_files/paper/2022/file/0378c7692da36807bdec87ab043cdadc-Paper-Datasets_and_Benchmarks.pdf).
- Evidence phrase: “a benchmark of 45 datasets”.
- Supported use: trees are strong candidates for the medium-sized tabular problems studied.
- Boundary: no universal theorem that neural networks always lose. The arXiv title omits “typical”; use the published title for the proceedings citation.

**McElfresh, Duncan et al. (2023).** “When Do Neural Nets Outperform Boosted Trees on Tabular Data?” *NeurIPS 2023, Datasets and Benchmarks*.

- Metadata/content: [published proceedings](https://proceedings.neurips.cc/paper_files/paper/2023/hash/f06d5ebd4ff40b40dd97e30cee632123-Abstract-Datasets_and_Benchmarks.html), [arXiv record and paper](https://arxiv.org/abs/2305.02997).
- Evidence phrase: “19 algorithms across 176 datasets”.
- Supported use: dataset characteristics and tuning matter; compare methods with documented budgets.
- Boundary: a broad benchmark does not certify a credit decision policy. “Et al.” is deliberate abbreviation; retrieve the full author list from the linked proceedings when preparing a formal bibliography.

## 3. CatBoost mechanism

**Prokhorenkova, Liudmila; Gusev, Gleb; Vorobev, Aleksandr; Dorogush, Anna Veronika; Gulin, Andrey (2018).** “CatBoost: unbiased boosting with categorical features.” *NeurIPS 2018*.

- Metadata/content: [published proceedings](https://proceedings.neurips.cc/paper/2018/hash/14491b756b3a51daac41c24863285549-Abstract.html), [arXiv record](https://arxiv.org/abs/1706.09516), [full text](https://papers.neurips.cc/paper_files/paper/2018/file/14491b756b3a51daac41c24863285549-Paper.pdf).
- Evidence phrase: “a permutation-driven alternative to the classic algorithm”.
- Supported use: ordered boosting and categorical processing address the prediction-shift problem studied in this paper.
- Boundary: this does not remove post-outcome features, incorrect historical joins, or test-set tuning. Do not substitute the different Dorogush/Ershov/Gulin library paper (`1810.11363`) as though it had these authors and this title.

## 4. Probability calibration

**Niculescu-Mizil, Alexandru; Caruana, Rich (2005).** “Predicting Good Probabilities With Supervised Learning.” *ICML*, 625–632. DOI: `10.1145/1102351.1102430`.

- Metadata/content: [author full text](https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf), [DBLP metadata](https://dblp.dagstuhl.de/rec/conf/icml/Niculescu-MizilC05.html), [DOI](https://doi.org/10.1145/1102351.1102430).
- Evidence phrase: “good accuracy or area under the ROC curve are not sufficient”.
- Supported use: ranking performance and probability quality need separate evaluation; compare sigmoid/Platt and isotonic with disjoint development data.
- Boundary: older experimental results are not a universal choice of calibrator. DOI-page opening failed; DBLP is a metadata cross-check, not the scientific evidence source.
- Current implementation evidence: [scikit-learn calibration documentation](https://scikit-learn.org/stable/modules/calibration.html) explains disjoint model/calibrator training and why Brier score alone cannot isolate calibration.

## 5. Interpretable models and explanations

**Nori, Harsha; Jenkins, Samuel; Koch, Paul; Caruana, Rich (2019).** “InterpretML: A Unified Framework for Machine Learning Interpretability.” arXiv `1909.09223`.

- Metadata/content: [author preprint](https://arxiv.org/abs/1909.09223), [official EBM documentation](https://interpret.ml/docs/ebm.html).
- Evidence phrase from the paper: “the first implementation of the Explainable Boosting Machine”.
- Supported use: EBM is a model candidate whose structure exposes additive feature/interaction contributions; check current details against official documentation.
- Boundary: preprint and software documentation, not an independent bank-specific performance result. A second independent complete bibliographic record was not established in this audit.

**Lundberg, Scott M.; Lee, Su-In (2017).** “A Unified Approach to Interpreting Model Predictions.” *NIPS 2017*.

- Metadata/content: [published proceedings](https://papers.neurips.cc/paper_files/paper/2017/hash/8a20a8621978632d76c43dfd28b67767-Abstract.html), [arXiv record and full text](https://arxiv.org/abs/1705.07874).
- Evidence phrase: “SHAP assigns each feature an importance value for a particular prediction.”
- Supported use: feature attribution for a particular model output.
- Boundary: interpreting attribution as a causal intervention is an unsupported extension. Identify whether the explanation concerns raw score, log odds, or calibrated probability.

## 6. Tabular foundation models: update old benchmark conclusions

**Hollmann, Noah; Müller, Samuel; Purucker, Lennart; Krishnakumar, Arjun; Körfer, Max; Hoo, Shi Bin; Schirrmeister, Robin Tibor; Hutter, Frank (2025).** “Accurate predictions on small data with a tabular foundation model.” *Nature*, 637, 319–326. DOI: `10.1038/s41586-024-08328-6`.

- Metadata/content: [publisher full text](https://www.nature.com/articles/s41586-024-08328-6), [PMC full text](https://pmc.ncbi.nlm.nih.gov/articles/PMC11711098/).
- Evidence phrase: “datasets with up to 10,000 samples”.
- Supported use: the reported TabPFN generation challenges an automatic assumption that GBDT must win on small tabular data.
- Boundary: this paper's size limit and performance belong to its tested generation. Neither applies automatically to all subsequent versions or our credit cohort.

**Jäger, Benjamin et al. (2026).** “TabPFN-3.5: Technical Report.” arXiv `2609.17895v2`, revised 22 September 2026. DOI: `10.48550/arXiv.2609.17895`.

- Metadata/content: [arXiv record](https://arxiv.org/abs/2609.17895), [versioned full text](https://arxiv.org/html/2609.17895v2), [developer report page](https://priorlabs.ai/technical-reports/tabpfn-3-5).
- Evidence phrase: “data with temporal or grouped splits”.
- Supported use: include the current generation in a contemporary comparison when access and compute permit.
- Boundary: developer-authored technical report, not independent validation on a Thai bank portfolio. The full 47-author list is in the linked record; it is not reconstructed from memory.
- Operational sources: [model documentation](https://docs.priorlabs.ai/models), [weights access](https://docs.priorlabs.ai/models/accessing-model-weights), [weights license v1.0](https://huggingface.co/Prior-Labs/tabpfn_3_5/blob/main/LICENSE). Separate model licensing from code licensing. Research/production purposes and output use affect permissible use; no terms were accepted and no weights were downloaded in this task.

## 7. Distributional consequences of credit ML

**Fuster, Andreas; Goldsmith-Pinkham, Paul; Ramadorai, Tarun; Walther, Ansgar (2022).** “Predictably Unequal? The Effects of Machine Learning on Credit Markets.” *The Journal of Finance*, 77(1), 5–47. DOI: `10.1111/jofi.13090`.

- Metadata/content: [publisher abstract/record](https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.13090), [author publication list](https://www.andreasfuster.com/papers), [author research summary](https://www.stone-econ.org/research/predictably-unequal-the-effect-of-machine-learning-on-credit-markets?412e8cd9_page=2).
- Supported use: evaluate heterogeneous effects and group performance, rather than overall prediction averages alone.
- Boundary: US mortgage evidence does not establish effects for Thai protected groups or a Thai credit product. A 2018 draft was located but its tables are not represented here as the final 2022 version.

## 8. Policy/data evidence is distinct from model superiority

- [BOT credit-risk supervisory manual](https://www.bot.or.th/content/dam/bot/documents/th/our-services/Member-corner/manual-of-supervision/Credit-risk-framwork-2567-attachment.PDF): read relevant rating/model/scoring text; supports data reliability, testing and purpose alignment. Does not mandate CatBoost, an LLM, or another named algorithm.
- [BCBS credit risk and ECL guidance](https://www.bis.org/bcbs/publ/d350.htm): accounting-loss context. Does not turn a binary public-dataset classifier into a complete TFRS 9 implementation.
- [UCI dataset documentation](https://archive.ics.uci.edu/dataset/350/default+of+credit+card+clients): provenance, dictionary and source license. The original descriptive claim that a neural network estimated PD best refers to the six methods in its original study; it is not evidence of a universal modern winner.
- [Home Credit 2024 Data](https://www.kaggle.com/competitions/home-credit-credit-risk-model-stability/data) and [Rules](https://www.kaggle.com/competitions/home-credit-credit-risk-model-stability/rules): inspected through browser UI. Data structure and usage restriction are separately recorded in the dataset report.

## Integrity status

Titles/authors/venues were checked against accessible records at the level stated above. Accessible papers or official content support the narrow claims used, not every possible interpretation of each work. Retraction searches returned no matching notice in the inspected results, but a complete Retraction Watch/Crossref audit was not performed. DOI resolution remains incomplete for two references. No blanket “all references fully verified” assertion is made.

No paper supplies the performance of a model trained in this workspace. All proposed model orderings, split decisions and stack selections are engineering recommendations to test, not reported experimental findings.
