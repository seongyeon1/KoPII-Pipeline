# KoPII: Korean PII Detection and Organization-Aware Generalization for Enterprise Documents

**Working draft — 2026-09-21. Not a submission-ready manuscript.**

Authors, affiliations, venue, and acknowledgements are intentionally unspecified. The empirical results below belong to the archived September 15 adoption study, not to the new package implementation. The privacy–utility study remains unexecuted.

## Abstract

Korean enterprise documents contain personal identifiers alongside organizational information useful for document retrieval and task assignment. We present KoPII, a modular implementation that separates span detection, external organizational context resolution, and replacement policies. The implementation supports Korean BIO token classifiers, two GLiNER-family adapters, and deterministic rules, together with masking, document-scoped pseudonyms, and organization-based replacement. An archived adoption study compared a Korean-fine-tuned RoBERTa checkpoint with two initially considered public PII models on 2,006 Korean dialogue-derived records and 580 synthetic negative records. The Korean model achieved 91.10% exact typed-span F1 on the common evaluation categories. These results are conditional on the evaluated configurations: the candidates were not adapted or tuned for Korean, and their default word boundaries could not exactly represent many annotated Korean names. We release a reusable processing package and experiment infrastructure, and specify controlled experiments to distinguish data, boundary, and replacement-policy effects. Improved downstream utility and reduced re-identification risk are research questions, not established findings of this draft.

## 1. Introduction

Document processing systems need to restrict exposure of personal information while retaining the information required for authorized tasks. A document may identify an employee by name even when its downstream use requires only the responsible organizational unit. Replacing every name with one marker removes this distinction, whereas retaining a team label may reveal additional identifying context. The choice should therefore be evaluated as a task-dependent trade-off.

The initial engineering investigation considered NVIDIA GLiNER-PII and Fastino GLiNER2-PII for adoption. Evaluation in Korean motivated a comparison with a Korean-fine-tuned RoBERTa checkpoint and an analysis of particle boundaries and false positives. This is the context of the archived comparison; it does not establish the optimal ranking of these model families.

This draft contributes an explicit, reproducible system decomposition and reports the bounded adoption study. The proposed research contribution is an empirical account of Korean boundary handling and organization-aware generalization. Evidence for a superior privacy–utility trade-off is pending. We do not introduce a new transformer architecture or claim that context-preserving anonymization is a new task.

## 2. Related Work

GLiNER uses a bidirectional transformer for flexible entity extraction, providing a relevant model family for promptable PII detection. The architecture paper should not be conflated with the language coverage or tuning of particular PII checkpoints. [Zaratiana et al., 2024](https://aclanthology.org/2024.naacl-long.300/)

TAB evaluates text anonymization with annotations and metrics that account for privacy and retained utility beyond ordinary entity detection. This motivates separating exact detection metrics from document-level privacy outcomes. [Pilán et al., 2022](https://aclanthology.org/2022.cl-4.19/)

RAT-Bench assesses re-identification risk using direct and indirect identifiers and an attacker model. Its demographic setting should not be transferred directly to Korean organizations. [Krčo et al., 2026](https://arxiv.org/abs/2602.12806)

Adaptive Text Anonymization studies strategies tailored to privacy requirements and downstream utility. Our proposed focus is a Korean, directory-grounded implementation and controlled study; novelty relative to adaptive and knowledge-based approaches requires a fuller literature review. [Loiseau et al., 2026](https://arxiv.org/abs/2602.20743)

**Before submission:** extend this section with original sources for the Korean corpora, KLUE pretraining, synthetic PII generation, Korean de-identification, entity linking ambiguity, and organization-aware generalization. Cite the actual upstream datasets, not only the combined Hub upload.

## 3. Task and Assumptions

For an input string x, a detector predicts spans (start, end, type, score) using half-open Unicode character offsets. A resolver maps selected name surfaces to organizational context or an unresolved status. A policy transforms detected spans into generic markers, document-scoped pseudonyms, or organization labels. The output includes transformed text and replacement offsets.

The intended downstream task initially concerns the responsible organization, not recovery of a named person's identity. An organization label is not assumed to be non-identifying: team size, title, time, and project context may enable identity inference. A directory is available to the processing service; whether an attacker has the same directory must be specified per experiment.

Name matching does not constitute unique-person identification. Multiple employees with the same name and team may resolve to one organizational label. Different teams remain ambiguous even if their parent unit is the same. Pseudonyms identify a surface within a document, not a unique person in the world.

## 4. Data

### 4.1 Archived resource

The published Korean PII collection comprises 100,851 records: 78,963 training, 9,994 validation, 9,888 internal test, and 2,006 separate KDPII-derived evaluation records. It combines public Korean material, modified public contexts, templated business documents, and negative examples. Some source values remain from public material; the complete collection is not purely synthetic.

The 2,006-record evaluation segment contains 458 dialogues and 1,548 utterance-derived records. These are dependent observations. The 580 negative records are a subset of the internal test material and share the synthetic generation family with training data.

### 4.2 New research data protocol

Source documents and their derivatives must share a group ID. Template families and source groups should be separated before tuning. The existing test has already informed error analysis, so final claims about improvements require an untouched evaluation set or an explicit limitation on independence.

The package's six-template fixture generator is only for execution tests. It neither reconstructs the historical corpus nor supplies a credible new business-document benchmark. Provenance, annotation instructions, annotator agreement, licensing, group mapping, and independent evaluation data remain required before submission.

## 5. Method

### 5.1 Detection adapters

A common adapter returns original-text character spans. The Korean token-classification adapter uses a fast tokenizer and overlapping token windows, selecting predictions with more surrounding context for duplicated token offsets. GLiNER adapters expose model revision, label prompts, threshold, character-window size, overlap, and batch size. They remove exact duplicate predictions while retaining nonidentical conflicting spans for evaluation. The current adapters do not implement a Korean-specific GLiNER boundary change.

### 5.2 Organizational context and replacement

Resolution is independent of model weights. The reference implementation uses an explicitly fictional CSV directory with team, division, and center fields. Application-specific database resolvers can implement the same bulk interface.

Runtime overlapping detections cover their union. If types conflict, the merged region receives a generic PII marker. This coverage-oriented runtime behavior is distinct from raw detector evaluation. Organization resolution is applied to person-name spans only. Unresolved context falls back to a keyed document-scoped pseudonym where configured, and otherwise a generic marker. The method does not guarantee anonymity or grammatical particle correction.

### 5.3 Research execution

The runner records configuration, immutable model revision, data hash, source hash, major package versions, and execution environment. Checkpoints contain predicted positions without copying document text. Run identity changes reject continuation; checkpoint writes are atomic and concurrent writers are excluded.

Exact typed-span precision, recall, F1/F5, label-agnostic character coverage, full-span coverage, and negative-document error rates are reported separately. Optional intervals resample whole source groups. The current runner measures per-document wall time only as a diagnostic, not a production latency benchmark.

### 5.4 New training baseline versus archived training

The new training implementation is a fixed-epoch cross-entropy baseline with overflow token windows and post-training development evaluation. It is not a reproduction of the archived Focal-loss training with F5 checkpoint selection and truncated 256-token inputs. These choices must be controlled in new ablations rather than silently attributed to the historical checkpoint.

## 6. Archived Adoption Study

The study was conducted on September 15, 2026, on Apple M4 Pro using PyTorch MPS, with the same evaluation records for all three models. Exact F1 uses 13 corresponding categories on the 2,006 KDPII-derived records; negative-document errors use the separate 580 records. Exact matches require both boundaries and type. Model/data revisions and execution details are preserved in the linked report.

| Checkpoint | Exact F1 | Person-name recall | Negative documents with a false positive |
|---|---:|---:|---:|
| Korean RoBERTa | 91.10% | 96.05% | 0 / 580 |
| NVIDIA GLiNER-PII | 8.73% | 12.43% | 559 / 580 |
| Fastino GLiNER2-PII | 19.87% | 18.36% | 182 / 580 |

Source: [archived report](../docs/public/benchmark-results.md) and [aggregate data](../docs/public/benchmark-results.json). These values were not recomputed using the new package. Historical and new windowing/overlap behavior differ, and the records do not establish performance on an untouched business-document test set.

Of 354 annotated names, 244 were not exactly representable by the two candidates' default word boundaries. This supports investigating a boundary constraint but does not quantify its causal contribution to the total gap. Character recall was 88.53% for NVIDIA and 81.45% for Fastino; broad overprediction can increase coverage without improving exact extraction.

The candidate label prompts and thresholds were not tuned on Korean validation data, and the candidates were not fine-tuned on the same Korean corpus. Their initial deployment suitability in this setting is therefore the supported interpretation, not universal model superiority. The study does not measure production HTTP behavior, organizational matching accuracy, downstream utility, or re-identification risk.

## 7. Planned Controlled Experiments — No Results Yet

- **E1: data composition.** Public-only, public plus synthetic business text, and public plus synthetic negatives, with matched or reported training budgets and at least three prespecified seeds.
- **E2: candidate adaptation.** Initial settings, validation-tuned prompts/thresholds, Korean boundary handling, and same-data adaptation where supported. Change one component at a time and record search budgets.
- **E3: policy effects.** Masking, document pseudonyms, and team/division/center generalization. First use gold spans to isolate policy effects; then use predicted spans for end-to-end errors.

For E3, hold retrieval and answering systems fixed across policies. Measure responsible-organization answer accuracy and retrieval Recall@k. Separately evaluate identity inference under explicit attacker knowledge and candidate sets. Synthetic-directory findings must remain labeled as controlled synthetic findings.

**Figures to produce from measurements:** data-composition ablation; boundary versus coverage errors; utility versus identity-inference success across policy levels. No unmeasured numeric cells or projected improvements are included in this draft.

## 8. Limitations and Data Governance

The observed advantage is conditional on an asymmetric adaptation setting and on a partly dependent evaluation corpus. Synthetic negatives do not represent all operational false positives. Directory errors, small teams, homonyms, stale hierarchies, and indirect identifiers remain material risks. No mathematical anonymity, differential privacy, or legal compliance guarantee is established.

The public release contains fictional organization examples, not a customer directory or customer document corpus. Publication permissions for each upstream dataset and model must be checked independently of the repository's MIT code license. The original document store, access controls, and any preprocessing before PII detection remain application responsibilities.

## 9. Reproducibility and Submission Status

The package, pinned checkpoint configurations, evaluation runner, fixture generator, and new training baseline are executable. Runtime tests, neural smoke inference, and a minimal training pass verify software behavior only. They are not evidence for E1–E3 hypotheses.

The submission remains incomplete until independent data preparation, adaptation comparisons, policy/attacker experiments, statistical analysis, and a full literature review are completed. [Research plan](../research/PLAN.md) tracks these requirements. Bibliographic metadata is provided in [references.bib](references.bib).
