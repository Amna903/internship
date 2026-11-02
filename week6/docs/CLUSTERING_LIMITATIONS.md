# Clustering limitations (D4)

Source: `backend/ml/reports/clusters.json` and `clusters.md`, reproduced by `ml.verify_release` in the Step 9 suite.

**Bottom line: on the synthetic patients, the clusters are not real structure. The app shows them as exploratory and labels them as such.**

| Evidence | Value | What it means |
|---|---|---|
| Real data, k-means silhouette at the chosen k=3 | **0.169** | Weak separation |
| The same data with each column shuffled (20 runs), median silhouette | **0.168** | Shuffling destroys any real relationship, yet scores the same, so the "clusters" are what k-means always produces |
| Planted-control data (4 groups built in on purpose): silhouette | 0.295 | Clustering *can* find structure when it exists… |
| Planted control: agreement with the truth (ARI), k-means | 0.52 | …but only partly: about half the planted structure is recovered |
| Planted control: k chosen by silhouette | 3 for k-means, 2 for Ward, but 4 were planted | The "best k" picked by the usual rule is wrong even when the answer is known |

**Limitations to state wherever clusters appear:**
1. **They describe booking patterns, not kinds of people.** They are never a personal, medical or risk category.
2. **The choice of k is unreliable:** silhouette picked the wrong k on the control data.
3. **The method matters:** k-means and Ward disagree (ARI 0.52 against 0.18 at their own chosen k).
4. **Synthetic data:** real patients would bring correlated, missing and biased data; none of this transfers.
5. **So the app shows** cluster descriptions and the PCA picture **only for the planted-control data**, and the real-data verdict as "no meaningful structure" (`GET /api/v1/clusters/`).
