# Week 4 study guide

A plain-English walk through every part of Week 4. For each part: what it does, why it was built that
way, what else was considered and rejected, and an everyday example. The numbers come from the
committed reports; the links go to them.

---

## Part 1: Supervised learning (predicting no-shows)

### The task

Given a fictional appointment (how far ahead it was booked, the time, the channel, the patient's past
appointments), estimate how likely the patient is to miss it. The result only suggests a reminder.
It never decides anything about the person.

**Everyday example:** a hairdresser who notices that people who booked two months ahead often forget,
and sends them an extra text message. Nobody is refused a haircut.

### Why fake (synthetic) data

- **Chosen:** a generator with a known formula (seed 42).
- **Rejected: a public dataset.** Real health data brings privacy and licence problems, and we would
  never know the "true" answer to compare against.
- **Rejected: data made up by an LLM.** It looks realistic but has no reliable, known pattern inside.
- **Gain:** because we planted the formula, we can compute the best possible score (the "oracle
  ceiling", PR-AUC 0.321) and see how close each model gets.

### Three model families

| Model | Plain idea | Everyday example |
|---|---|---|
| Logistic regression | Adds up weighted clues into one score | A checklist: +2 for "booked far ahead", −1 for "reminder sent" |
| Random forest | Many simple decision trees vote | Asking 300 friends, each with their own yes/no rules, and taking the vote |
| Gradient boosting | Trees built one after another, each fixing the last one's mistakes | A student who reviews only the questions they got wrong last time |

### Measuring: why PR-AUC, not accuracy

Only about 16% of appointments are missed. A model that says "everyone will attend" is 84% accurate
and completely useless.

- **Chosen: PR-AUC.** It asks: among the appointments you flag, how many are real misses, and how many
  real misses do you find?
- **Rejected: accuracy.** It rewards ignoring the rare class.

**Everyday example:** a smoke alarm that never rings is "right" 99.9% of the time, and worthless.

### Splitting the data: by patient

- **Chosen:** each patient goes entirely into training, validation or test.
- **Rejected: a random split of appointments.** The same patient would appear in both training and
  test, so the model could recognise the person instead of learning the pattern.

**Everyday example:** a teacher who uses the homework questions in the exam. The scores look great and
mean nothing.

### Choosing a model: cross-validation and the one-standard-error rule

- **What changed:** in Step 3, models were first chosen by one validation score. But two models only
  0.0002 apart swapped places between my Mac and the Linux CI machine. One score was too noisy to choose
  between close models.
- **Chosen: 5-fold cross-validation**, grouped by patient and stratified. The model is trained 5 times
  on different parts and the scores averaged. Any model within **one standard error** of the best counts
  as tied, and the simplest of the tied models wins.
- **Rejected: always take the top score.** That picks noise.

**Everyday example:** judging a footballer on five matches, not one lucky game. If two players are
within normal match-to-match variation of each other, pick the one who is easier to coach.

### Releasing: champion and challenger

- **Rule:** the served model (the champion, v1.0.0) is replaced only if the new choice (the challenger)
  beats it by more than one standard error, on the same folds.
- **Week 4 result:** challenger 0.275 against champion 0.283. It didn't win, so **v1.0.0 stays.**
- **Lesson:** "prefer simpler" made sense between logistic regression and trees. But between two
  logistic regressions, both are equally explainable, so preferring the one with fewer inputs cost
  accuracy for nothing.
- **The rule is frozen** in `ml/release_rule.py`, so it can't be bent after seeing results.

**Everyday example:** a sports team keeps its goalkeeper unless the new one is clearly better, not just
better in one training session.

### The test set and the fresh holdout (the mentor's point)

- The test set should be used **once, at the end**. Ours was scored in Week 3, and in Week 4 it
  influenced the release decision. So its numbers are now **exploratory**, not a clean final grade.
- **Fix:** a fresh holdout (2,000 new patients, different seed) is locked away. A test makes sure no
  code can open it.

**Everyday example:** a sealed exam paper. Once you've peeked at it, it can't measure you fairly
again, so you need a new sealed paper.

### Explaining the model: permutation importance

- **Chosen: permutation importance.** Shuffle one column and see how much the score drops. A big drop
  means that column mattered.
- **Also shuffled as a group:** "past appointments" and "past no-shows" go together. Shuffled
  separately, each would look less important than the pair really is.
- **Rejected: the forest's built-in importance only.** It favours columns with many distinct values,
  even useless ones. It's shown for comparison only.

**Everyday example:** to see how much salt matters in a soup, cook it once without salt and taste the
difference.

---

## Part 2: Unsupervised learning (clustering)

### The idea

Group patients by booking habits (lead time, telehealth share, channel, appointment hour, number of
appointments) without telling the computer what the groups are.

- **Excluded on purpose:** age, distance, outcomes and past no-shows. Clusters must describe *booking
  patterns*, never *kinds of people*.

### Two methods

| Method | Plain idea | Everyday example |
|---|---|---|
| K-Means | Pick k centres, assign everyone to the nearest one, move the centres, repeat | Placing k ice-cream vans on a beach so everyone walks the least |
| Ward (agglomerative) | Start with everyone alone, keep merging the two closest groups | Building a family tree from the bottom up |

- **Not chosen: DBSCAN.** (Reasoning written for this guide; the choice wasn't recorded at the time.) It needs a distance setting that is hard to choose with mixed features, and it
  labels many points as "noise". It would have been harder to explain.

### Is there any real structure? Compare with shuffled data

- **Silhouette score:** how well separated the clusters are, from −1 to 1.
- **The trap:** clustering always returns clusters, even on random noise. So we shuffle the data to
  destroy any real pattern, cluster it again, and set the bar at what noise reaches.
- **Real data result: no structure.** K-Means scored 0.169 against a shuffled bar of 0.173. Ward scored
  0.130 against 0.163.
- **Why:** the generator draws each engagement column independently for each appointment. There are no
  habits to find. Most of the "split" (63%) came from the number of appointments.

**Everyday example:** seeing animals in clouds. Your brain always finds shapes, so you need a test
for whether a shape is really there.

### The positive control

- **Problem:** "no structure found" might mean our method is broken.
- **Fix:** a separate small dataset with **four habits planted on purpose** (seed 7). Does the method
  find them?
- **Result:** K-Means **partly** found them (ARI 0.52, where 1 is perfect and 0 is chance). Ward scored
  0.18 at its chosen k.

**Everyday example:** testing a metal detector by burying a coin yourself first. If it can't find your
coin, its "nothing here" means nothing.

### PCA, for the picture

- **Chosen:** PCA squeezes 6 features into 2, so we can draw them. The two axes keep 61% of the variation.
- **The plot uses the control data**, labelled as such, because real-data clusters would be misleading.

**Everyday example:** a shadow of a 3D object on a wall. You lose some detail, but you can see the shape.

---

## Part 3: The clinic policy assistant (local LLM with retrieval)

### The idea: retrieval-augmented generation (RAG)

1. Find the policy passages closest to the question.
2. Give only those passages to the model.
3. Ask it to answer from them and quote its sources.

- **Rejected: fine-tuning a model on the policies.** It's expensive, the policies would be hidden
  inside the model, and every policy change would need retraining.
- **Rejected: pasting all policies into every prompt.** It doesn't scale, and the model is more likely
  to mix things up.

**Everyday example:** an open-book exam where you must write the page number next to each answer.

### Local model, not a hosted API

- **Chosen:** Ollama running `llama3.2:3b` and `nomic-embed-text` on the laptop. No data leaves the machine.
- **Rejected: a hosted API** (more capable). The brief forbids sending patient data to external LLMs.
  A local model makes that rule true by design, not by promise.
- **Cost:** slower, less capable, and the answers vary more. That's why we need the checks below.

### Embeddings and search

- **Embedding:** turns text into 768 numbers, so that similar meanings get similar numbers.
- **Search:** cosine similarity in NumPy over the approved chunks.
- **Not used: a vector database** (pgvector, Chroma). (Reasoning written for this guide; not a recorded
  decision.) With 6 small documents it adds a moving part and nothing else.
- **Each vector stores which embedder made it.** If the embedder changes, old vectors are skipped and
  reported, and re-indexing happens only through an admin command, never quietly during a request.

**Everyday example:** a library catalogue where books on similar topics sit on nearby shelves, so you
walk to the right shelf without knowing the exact title.

### The similarity floor and top-k

- **Floor (0.70):** if no passage is at least this similar, the answer is "insufficient information",
  and **the model is not called.**
- **Top-k (2):** how many passages the model sees.
- **Both were tuned on 11 development questions only**, never on the evaluation cases.

**Everyday example:** a shop assistant who says "we don't sell that" instead of guessing, when nothing
on the shelves is close.

### The biggest design decision: the server decides, not the model

- **What happened (Step 9):** the 3B model was asked to label its own answer. It wrote the right answer
  with the right quote, then labelled it "insufficient information", three times out of three.
- **Chosen:** the model returns only `answer`, `citations` and `refused`. **The server decides the
  status** from things it can check:
  - **the citation is real:** the passage was given to the model, and the quote is really in it;
  - **numbers:** every number in the answer appears in the quotes ("48 hours" against a quote saying
    "24 hours" is blocked);
  - **substance:** at least two key terms, so no one-word answers;
  - **polarity:** the answer doesn't add or drop a "not";
  - **groundedness:** enough of the answer's words come from the quotes (threshold 0.61);
  - **no leaks:** the answer doesn't repeat the system prompt.
- **Rejected: trusting the model's label.** It was wrong in a measurable way.

**Everyday example:** a teacher checks a student's footnotes against the actual book, instead of
asking the student "is your essay correct?"

### Medical questions are refused first

- **Chosen:** a server-side check refuses medical questions **before** any search or model call.
- **Also:** the model can set `refused`. That's two layers (defence in depth).
- **Rejected: relying on the model to refuse.** Small models can be talked out of it.

### Uploads: pending until approved

- **Chosen:** uploaded documents are checked (UTF-8 `.txt`/`.md` only, with the content checked, not
  just the extension) and arrive as **pending**. They become searchable only after an admin approves them.
- **Why:** an uploaded file could contain an attack ("ignore your rules…"). Approval is the gate.

**Everyday example:** a noticeboard where anyone can hand in a notice, but staff pin it up only after
reading it.

---

## Part 4: Testing the assistant honestly

### Dev set versus frozen evaluation

- **Dev set (11 questions):** used for tuning. You're allowed to look at it as often as you like.
- **Frozen evaluation (18 cases, 12 written by me):** fixed with a SHA-256 hash **before** tuning.
  Tuning code never reads it.
- **Why:** if you tune on the exam questions, the exam stops measuring anything.

### Settings A and B, named before the run

- A (shipped: top-k 2) and B (top-k 4) were written down before any case ran. **A ships whatever B
  scores.** The comparison is for reporting only.
- **Result:** both passed 17 of 18. With 18 cases, a difference of 1–2 would be noise anyway.

### Three runs per case, majority vote

The model varies between runs, even at a low temperature. Each case runs with seeds 42, 43 and 44, and
passes if 2 of the 3 runs pass.

**Everyday example:** best of three in a game, so one lucky or unlucky throw doesn't decide it.

### The honest surprise: the floor did most of the work

- 10 of the 12 cases that shouldn't be answered were stopped by the floor, **before the model**. So the
  17/18 said little about the model's resistance to attacks.
- **What I did:**
  1. a "which defence decided it" table;
  2. a diagnostic run with the floor off;
  3. a **red-team set** written after the evaluation, with attacks hidden inside normal questions.
- **Result:** five attacks reached the model, and **none leaked**.
- **What the floor-off run exposed** (recorded, not fixed on eval results): some true but off-topic
  answers, a terse answer to an ambiguous question, and a false polarity block.
- **Rejected: changing the checks after seeing the results.** That would turn the evaluation into
  tuning. The gaps are listed in [known_gaps.md](../backend/assistant/eval/known_gaps.md) for the next
  dev round.

**Everyday example:** a security guard at the front door stopped every test intruder, so the alarm
inside was never tested. You have to test the alarm separately.

---

## Part 5: How the work was run

- **A checklist before every step.** I approved it before any code was written.
- **Rules before results.** Tuning rules, evaluation settings and the release rule were all written
  before running.
- **CI as the gate.** No step started until the previous push was green.
- **A draft PR** until all the evidence was linked (the mentor's third point).
- **Decisions in files, not chat:** `REQUIREMENTS.md`, `ai-workflow.md`, and the generated reports.

### A trade-off to fix: weekly folders

Each week is a full copy of the previous one. That kept reviews separate, but it duplicates code, and
the brief asks to extend one application (Week 6 integrates everything). **Plan:** one codebase, with a
git tag for each week.

**Everyday example:** photocopying your whole notebook every week instead of adding new pages and
bookmarking where each week starts.

---

## Quick self-test

1. Why is accuracy a bad metric here?
2. Why split by patient?
3. What does "within one standard error" protect against?
4. Why did v1.0.0 stay?
5. Why is the old test set now "exploratory"?
6. Why compare clustering scores with shuffled data?
7. What does the positive control prove?
8. Why doesn't the model decide its own status?
9. Name three server checks and what each one catches.
10. Why did the first evaluation say little about prompt injection, and what fixed that?
