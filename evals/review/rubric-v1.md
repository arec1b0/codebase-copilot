# Human review rubric v1

This packet samples 20 previously inspected development cases, four per category.
It is purposive: agreement does not estimate population accuracy or holdout quality.
All labels must be entered by a human. Never copy model ratings into labels.

## Faithfulness

Read faithfulness.md first. It displays the answer and its cited source text.
Question, reference answer and judge scores are omitted from this view.

- 2: every material factual claim is supported by the cited source text.
- 1: the answer mixes supported claims with ambiguous or unsupported details.
- 0: its central claim is contradicted or unsupported, or it supplies no factual answer.

Judge support, not completeness. A supported partial answer can receive
faithfulness 2 and relevance 1 or 0. Missing essential information affects relevance.

## Relevance

Then read relevance.md, which displays the question, reference and answer.

- 2: directly answers the question and covers its essential requirements.
- 1: partially answers the question or leaves a material point imprecise.
- 0: answers another question, uses the wrong method or premise, is wrong,
  or abstains on an answerable question.

If the question or reference is wrong or ambiguous, set reference_issue to true
and explain it in notes. Such an item requires adjudication and blocks completion.

## Recording labels

Edit labels.json only. For every item enter both integer scores from 0 through 2
and a separate evidence-based reason for each dimension. Set label_origin to
human, annotator to your reviewer identifier and reviewed_at to an RFC3339
timestamp with a timezone, for example 2026-10-19T16:00:00+00:00.

All human fields start null. Source and item checksums prevent accidental packet
drift; they are not a cryptographic signature or proof that a human reviewed it.
The views hide model ratings, but prior exposure to the historical results means
this is not an independently blinded study.

An agreement audit reports observed agreement only. It never sets calibrated to
true and never approves release thresholds automatically.
