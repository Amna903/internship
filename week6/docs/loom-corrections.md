# Loom corrections (Week 4 review follow-up, about 5 minutes)

Re-record only these segments, as a Part C that names the timestamps it corrects. Simple spoken English. Every
number comes from [evidence-replay.md](evidence-replay.md), and each segment says which file to show.

**Before recording:** open `docs/evidence-replay.md`, `backend/ml/reports/clusters.md`,
`backend/ml/reports/metrics.md`, `backend/assistant/eval/relevance_report.md`, and a terminal in `backend/`.
No Ollama needed: everything below replays committed results.

---

## C1. Correcting Part A 3:41 and 3:58: clustering (≈1:15)

**Show:** `clusters.md`, the real-data table, then the positive-control table.

> In Part A I mixed two things up, so let me correct them. PR-AUC and permutation importance belong to the
> prediction model. They say nothing about clustering. Also, PR-AUC is not accuracy. It measures how well
> the model ranks the no-shows, which are only 16% of visits, above everyone else.
>
> For clustering, the measure is the silhouette score, compared with the same score on shuffled data.
> On the real synthetic patients, K-Means scored 0.169 against a shuffled bar of 0.173. Ward scored 0.130
> against 0.163. Neither beat the shuffled data, so there are **no supported patient clusters** in this
> data. I also said K-Means was "better" in general. That's not what the results show.
>
> The PCA view on the dashboard is a **positive control**: data where I planted four habits on purpose,
> and it's labelled that way. There K-Means partly recovered them (ARI 0.518), and Ward less so at its
> chosen k (0.179). And the 0.5 cut-off I used for "partly" was picked after I saw the result, so it's borderline.
> So K-Means did better on this one control. It doesn't show K-Means is better in general.

## C2. Correcting Part B 2:39–2:48: leakage and overfitting (≈1:00)

**Show:** the "Split guards" paragraph in `evidence-replay.md`, then the train-versus-validation table in
`metrics.md`.

> I said "no leakage" and "no overfitting". Those are claims I can't prove, so here's what I actually checked.
> The split is grouped by patient, 60/20/20, and a test checks that no patient appears in two parts. IDs,
> the label and the true probability are never features. The imputer and the scaler learn from training
> rows only, and the cross-validation folds are grouped by patient too. No single feature is suspiciously
> strong: the best one alone scores 0.618 AUC.
>
> On overfitting: the served model scores 0.287 PR-AUC on training rows and 0.276 on validation, a gap of
> 0.011. My warning bar, fixed before training, was 0.05. So the measured gap is small. These checks lower
> the risk. They don't prove there's none.
>
> And from Part B at 0:43: 17 of 18 frozen cases passed. A6 is still the failure, and I'm keeping it.

## C3. Correcting Part B 3:57: the negation/idiom fix, shown (≈0:45)

**Show:** terminal: `DJANGO_SETTINGS_MODULE=config.settings_test python scripts/demo_idiom_fix.py`.

> Here's the fix I only described before. This is the original failing phrase: the correct answer about
> rescheduling, against a quote that says "at no cost". Before the fix, the polarity check saw "no" and
> blocked it. After the fix, it's answered. This is the changed check: exactly two phrases from the
> policies. "No fee" is deliberately not on it, and here's why: a flipped fee is still caught. And these
> are the regression tests, passing.

## C4. New: relevance check, and what still fails (≈1:15)

**Show:** `relevance_report.md`: the top table, then "Citation validity is not entailment", then "What this check
does not fix".

> The review pointed out that my checks verified the quotes but never checked that the answer answered
> the question. I added new development cases with the same policy words but a different intent, plus
> answers that reverse a clause. I froze a separate set before writing the check. The check asks two
> things: is the answer about the same policy topic, and does it contain the kind of fact asked for, like
> an amount, a time or a count. I chose it on the development cases only.
>
> On the frozen set, scored once, it stopped 5 of 12 bad replies, up from 1, and kept all 6 correct ones.
>
> Here's a failure that's still there. "Each appointment can be rescheduled at least twice", citing "at most
> twice", is answered. The citation is real; the meaning is wrong. A valid citation is not proof the answer
> is true. So I don't call this assistant fully verified: it's cited and word-checked. And the original
> injection examples, U1, U2 and U9b, still get past this check. The similarity floor is still what stops them.

## C5. Evidence replay (≈0:30)

**Show:** `evidence-replay.md`, scrolling the table.

> Finally, every number I've quoted is in this table, with the report it comes from and the command that
> regenerates it. A test fails if any of them stops matching its report.

---

## Cue list

Correction
PR-AUC≠accuracy
Silhouette
Shuffled
NoClusters
Control
Borderline
Guards
Gap0.011
17of18
Idiom
Before
After
NoFee
Tests
Relevance
Frozen
5of12
AtLeast
NotVerified
Floor
Replay
