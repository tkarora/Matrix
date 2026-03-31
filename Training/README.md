# Matrix Model Retraining Pipeline

This directory is the dedicated workspace for the **Dynamic Matrix Retraining Pipeline**.
---

## 📐 Training Principles Overview

The Forest Matrix Model relies on learning the transition probabilities of a forest stand density matrix. Instead of static, fixed constants, the model uses **three density-dependent, non-linear Random Forest (RF) models** to predict vital demographic rates.

### 🌳 The Three Demographic Targets

The pipeline learns three distinct biological processes independently:

1.  **Upgrowth ($UG$) — Diameter Increment**
    *   **Level:** Individual tree transitions.
    *   **Target $Y$:** Annualized diameter increment (`dD`).
    *   **Predictors:** Plot density metrics ($B$, $N$, Diversity $S1$/$S2$), climate (Bio1-21), soil (O1-5), topography (T1-12), and regional dummy variables.
2.  **Mortality ($MT$) — Size-Class Mortality Probability**
    *   **Level:** Plot-aggregated 2-cm DBH classes.
    *   **Target $Y$:** Annual probability of tree death within that specific size bin.
    *   **Formula:** `(Total Dead TPH / Total Living TPH) / census_interval_years`.
3.  **Recruitment ($RC$) — Sapling Influx Rate**
    *   **Level:** Plot-aggregate totales.
    *   **Target $Y$:** Ingrowth flux of saplings breaching the 10cm DBH threshold (`TPH / year`).

---

## 📉 Loss Function: Minimizing RMSE

During hyperparameter tuning and model training, the primary loss metric being minimized is the **Root Mean Square Error (RMSE)**.

### 🏷️ Tuning Mechanism
The trainer executes a programmatic subset grid search over the algorithm parameters:
-   **`ntree`**: The size of the forest ensemble (e.g., searching up to 200 trees).
-   **`nodesize`**: The minimum node depth.
-   **`mtry`**: The predictors sampled per node split.

The algorithm randomly subsets available longitudinal plots, splits them into a standard 50/50 Train-Test slice, and computes the deviation between predicting outcomes and ground truth.

$$ \text{RMSE} = \sqrt{\frac{\sum_{i=1}^{n} (y_{\text{true}} - y_{\text{pred}})^2}{n}} $$

Configurations that minimize the **mean Test RMSE across multiple iterations** are selected as the final runners to train the continent-wide models.

---

## 🔄 Independent vs Joint (End-to-End) Estimation

There are two distinct architectural philosophies for training the state transition models. Choosing between them changes the training logic and compute profile drastically:

### 1. Independent (Modular) Estimation [Current Approach]
The current codebase trains the three components ($UG$, $MT$, $RC$) in complete isolation from one another. 

*   **Principle:** Measure biological ground truths for each component independent of local feedbacks.
*   **Target $Y$:** Individual tree diameter increases (for $UG$), specific class death rates (for $MT$), and plot recruitment count per year (for $RC$).
*   **Implications:** 
    *   **Pros:** Highly efficient, statistically isolated (biologically consistent "pure" rules), and very easy to interpret. 
    *   **Cons:** Errors can accumulate when the trio is combined in sequential forward-simulation loops (no natural error cancellation).

### 2. Joint (Combined/End-to-End) Estimation
An alternative approach would be to tune hyper-parameters of the three models jointly to minimize the final predicted **DBH or biomass density error** at the end of a multi-year simulation.

*   **Principle:** Optimize the trio to work "best together" by treating the sequential simulator as the loss function.
*   **Target $Y$:** Aggregate Plot Density or Basal Area after $X$ years.
*   **Implications:**
    *   **Pros:** Better systemic coherence and stability over long-term multi-decadal forecasting.
    *   **Cons:** Exploding computational cost (requires running nested 25-year simulation loops during every hyperparameter step), non-differentiability (Random Forests are not easily back-propagatable), and risk of biological degeneracy (errors cancelling out via unrealistic solutions).

---

## 🛑 Limitations of Random Forests for Demography

While Random Forests are incredibly powerful for discovering complex non-linear patterns, they have key theoretical limitations when applied to biological simulation:

### 1. Zero Extrapolation (The Climate Change Ceiling)
Random Forests cannot predict values outside the range of their training data. 
*   **Implication:** If a historical plot has seen temperatures up to $30^\circ C$, and a future scenario reaches $35^\circ C$, the Random Forest will simply use the prediction for $30^\circ C$. It cannot "see" the cliff edge of biological tolerance if it hasn't happened in training data.

### 2. Discontinuous (Stepped) Landscapes
The predictive surface of a decision tree consists of discrete "boxes" or plateaus rather than smooth gradients. 
*   **Implication:** A tree might predict the *exact same* mortality for a stand with a Basal Area of $10.1 m^2/ha$ and $12.5 m^2/ha$, but then jump suddenly at $12.6 m^2/ha$. This can lead to jerky artifacts in sequential annual simulations.

### 3. Non-Differentiability
Standard Random Forests are hard logic splitters ($x > c$). You cannot calculate continuous derivatives (gradients) through a tree.
*   **Implication (Why End-to-End training is impossible):** To train an end-to-end model, you must use gradients to nudge weights smoothly. Because Random Forests yield a derivative of zero (or undefined), you cannot use standard Deep Learning optimizers like **Backpropagation Through Time (BPTT)**. The only way to find the "best trio" is a brute-force black-box search (guessing parameters), which is computationally impossible when nested inside a multi-year simulation loop. To do true joint training, you must pivot to differentiable models like Neural Networks.


### 4. No Biological Constraints (Conservation-Blind)
Trees are purely statistical, not rule-driven.
*   **Implication:** Without manual clipping, a Random Forest might predict negative mortality or negative recruitment if it overfits an outlier in the data. They do not know naturally that trees cannot "un-die" or pop out of thin air.

---

## 🛰️ Future Scope: Custom Parameters

As we move toward a custom retraining pipeline, this module will manage:
-   **Custom Coordinates (Unseen Forests):** Adapting pipelines to pull site-specific environmental telemetry.
-   **Custom Variables:** Integrating pollutant loads or micro-telemetry beyond the classic ~40 standard Bio/Soil/Topo variables.
-   **Cloud Native Orchestration:** Bridging `R` statistical accuracy with BigQuery massive horizontal scale.
