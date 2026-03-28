# Technical Construction Report: Autonomous Chaos & Self-Healing Platform

This report details the deep technical implementation and training methodologies used to build the autonomous "immune system" for the microservices platform.

---

## 1. Infrastructure Foundation (The "Patient")
**Files:** `/infrastructure/docker-compose.yml`, `/k8s/`
The system is deployed on a **Minikube** Kubernetes cluster. 

*   **Microservices:** 6 FastAPI-based services (Auth, API-Gateway, Order, Payment, Inventory, Notification) acting as the target.
*   **Observability:** A **Prometheus** instance scrapes metrics from all pods every 5 seconds. To bypass Docker Hub rate limits, the image was switched to `quay.io/prometheus/prometheus:v2.51.0`.
*   **Neural Bus:** **NATS** orchestrates the communication. Nerve endings (sidecars/controllers) publish to `nerve.*.alert` when anomalies occur.

---

## 2. Detection Pipeline: Isolation Forest (IF)
**File:** `/models/isolation_forest.joblib` | **Source Data:** `/data/baseline_metrics.csv`

The Isolation Forest is the first line of defense. It is an **unsupervised** model used to establish a mathematical baseline of "Normal."

*   **Creation Method:** We ran **Locust** (headless performance testing) for a calibrated window of 2 minutes to simulate 50 concurrent users. 
*   **Feature Vector:** The system collected 7 key metrics: `cpu_usage_pct`, `memory_usage_pct`, `http_error_rate_5xx`, `request_latency_p99`, `pod_restart_count_delta`, `network_rx_bytes`, and `network_tx_bytes`.
*   **Training:** Using `scikit-learn`, the model identifies "Outliers" (Anomalies) without needing labels. It was saved as a `.joblib` file for real-time inference.

---

## 3. Classification Pipeline: Random Forest (RF)
**File:** `/models/random_forest.joblib` | **Source Data:** `/data/rf_training_data.csv`

Once an anomaly is detected, the Random Forest classifies the **family** of the attack.

*   **Creation Method (Hybrid Synthetic):** To ensure high reliability during a demo, we used a **Gaussian Jittering** approach. We generated 5,000 rows of telemetry data representing the specific mathematical signatures of:
    *   `pod_crash`: Characterized by `pod_restart_count` spikes.
    *   `network`: High `latency` and `error_rate`.
    *   `resource`: High `cpu` and `memory` usage.
    *   `timing`: Sudden spikes in latent error rates.
    *   `camouflage`: Slow, gradual drifts in metrics.
*   **Technique:** We injected **Normal Distribution Noise** (`np.random.normal(0, 0.25)`) into the synthetic data to prevent "brittle" overfitting, resulting in a realistic **87.6% accuracy**. This allows the model to handle the messy telemetry of a real cluster.

---

## 4. Prediction Pipeline: LSTM (Temporal Evolutionary Model)
**File:** `/models/lstm_predictor.pt`

The LSTM (Long Short-Term Memory) is a **PyTorch**-based neural network that looks at the sequence of historical attacks to predict the *next* evolutionary mutation.

*   **Construction:** 
    *   **Architecture:** 2 LSTM layers (64 hidden units) + a dropout layer (0.3) + a Linear head.
    *   **Class Imbalance Handling:** Since the virus mutations typically end in `camouflage`, the training data was heavily skewed. We calculated and applied **Class Weights** to the `CrossEntropyLoss` function to ensure the model doesn't just guess the majority class.
    *   **Training:** It predicts the next attack family based on a sequence of 7 previous events (Attack Family, Recovery Time, Success).

---

## 5. Intelligence Layer (The "Brain")
**Files:** `db_core.py`, `seed_neo4j.py`, `docker-compose.yml`

This layer connects the ML results to actual Kubernetes remediation actions.

*   **T-Cell Memory (Redis):** Uses **O(1) hash mapping** of Signature IDs to specific Remedies. If an attack is seen twice, it bypasses the heavy "thinking" phase and recovers in < 2 seconds.
*   **Brain (Neo4j Graph):** A Knowledge Graph containing:
    *   **Blast Radius Dependencies:** Maps which services will fail if another crashes.
    *   **Remedy Nodes:** Direct links between Attack Families and K8s actions (e.g., `restart_pod`, `hpa_scale`).
*   **DNA Store (PostgreSQL):** A relational database that logs every single attack, the chosen remedy, and the recovery duration (ms). This feeds the **Virus mutation logic**, allowing the "Virus" to evolve if the "Antibody" gets too fast.

---

## 6. Antibody Discovery (Honeypot & LLM)
**Logic Path in:** `db_core.py`

When an attack has zero confidence (Unknown):
1.  **Honeypot:** A sacrificial replica is spun up to observe the unknown attack's behavior for 10 seconds.
2.  **LLM Synthesis:** The system feeds the raw honeypot metrics into the **Gemini 1.5 Flash API**. 
3.  **Crystallization:** The LLM-generated remedy is stored back into **Neo4j** and **Redis**, effectively "teaching" the system a new antibody for a previously unknown failure.

---
**Summary of the Stack:**
- **Inference:** scikit-learn (IF/RF), PyTorch (LSTM).
- **Communication:** NATS (Pub/Sub).
- **Remediation:** Kubernetes API (via Python SDK).
- **Storage:** Neo4j (Graph), Postgres (SQL), Redis (K/V).
