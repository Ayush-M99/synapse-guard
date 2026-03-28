"""
DARWIN Training Data Generator (§5, §16)

Generates labeled datasets for:
1. Random Forest classifier — 7-feature + delta vectors labeled by attack family
2. LSTM model — synthetic attack sequences for temporal prediction

Run BEFORE the demo to pre-train models.
Usage: python generate_training_data.py
"""

import os
import csv
import json
import random
import logging
import numpy as np

try:
    import joblib
    from sklearn.ensemble import IsolationForest, RandomForestClassifier
    SKLEARN_AVAILABLE = True
except ImportError:
    SKLEARN_AVAILABLE = False

try:
    import torch
    import torch.nn as nn
    import torch.optim as optim
    PYTORCH_AVAILABLE = True
except ImportError:
    PYTORCH_AVAILABLE = False

logging.basicConfig(level=logging.INFO, format="[TRAINING] %(message)s")
log = logging.getLogger("training")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.path.join(SCRIPT_DIR, "..", "models")
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")
os.makedirs(MODEL_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# FEATURE PROFILES PER ATTACK FAMILY
# ═══════════════════════════════════════════════════════════════

# 7 features: [cpu, memory, error_rate, latency_p99, restarts, net_rx, net_tx]
ATTACK_PROFILES = {
    "pod_crash": {
        "mean": [25, 30, 0.45, 0.5, 2.0, 5000, 5000],
        "std":  [10, 10, 0.15, 0.2, 1.0, 2000, 2000],
    },
    "network": {
        "mean": [20, 25, 0.35, 3.5, 0.2, 500, 500],
        "std":  [8, 8, 0.12, 1.5, 0.3, 300, 300],
    },
    "resource": {
        "mean": [85, 80, 0.20, 1.2, 0.5, 6000, 6000],
        "std":  [10, 10, 0.08, 0.5, 0.3, 2000, 2000],
    },
    "timing": {
        "mean": [40, 45, 0.50, 1.8, 1.5, 4000, 4000],
        "std":  [15, 15, 0.18, 0.8, 0.8, 1500, 1500],
    },
    "cost": {
        "mean": [50, 35, 0.10, 0.4, 0.1, 3000, 3000],
        "std":  [12, 10, 0.05, 0.2, 0.1, 1000, 1000],
    },
}

NORMAL_PROFILE = {
    "mean": [15, 20, 0.02, 0.08, 0.0, 4000, 4000],
    "std":  [5, 5, 0.01, 0.03, 0.0, 1000, 1000],
}


# ═══════════════════════════════════════════════════════════════
# 1. GENERATE RANDOM FOREST TRAINING DATA
# ═══════════════════════════════════════════════════════════════

def generate_rf_data(samples_per_family: int = 200):
    """Generate labeled dataset for Random Forest attack classifier."""
    log.info(f"Generating RF training data ({samples_per_family} samples/family)...")

    rows = []
    for family, profile in ATTACK_PROFILES.items():
        for _ in range(samples_per_family):
            features = []
            for i in range(7):
                val = max(0, np.random.normal(profile["mean"][i], profile["std"][i]))
                features.append(round(val, 4))

            # Deltas (current - 30s_ago, current - 60s_ago)
            delta_30s = [round(random.uniform(-0.3, 0.3) * f + random.gauss(0, 0.05), 4) for f in features]
            delta_60s = [round(random.uniform(-0.5, 0.5) * f + random.gauss(0, 0.08), 4) for f in features]

            downstream_affected = random.choice([0, 1]) if family in ["pod_crash", "network"] else 0

            row = features + delta_30s + delta_60s + [downstream_affected, family]
            rows.append(row)

    # Also generate normal baseline samples (labeled "normal")
    for _ in range(samples_per_family):
        features = []
        for i in range(7):
            val = max(0, np.random.normal(NORMAL_PROFILE["mean"][i], NORMAL_PROFILE["std"][i]))
            features.append(round(val, 4))
        delta_30s = [round(random.gauss(0, 0.02), 4) for _ in features]
        delta_60s = [round(random.gauss(0, 0.03), 4) for _ in features]
        row = features + delta_30s + delta_60s + [0, "normal"]
        rows.append(row)

    random.shuffle(rows)

    # Write CSV
    header = (
        [f"feature_{i}" for i in range(7)] +
        [f"delta_30s_{i}" for i in range(7)] +
        [f"delta_60s_{i}" for i in range(7)] +
        ["downstream_affected", "label"]
    )
    csv_path = os.path.join(DATA_DIR, "rf_training_data.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)

    log.info(f"  ✓ RF data: {len(rows)} samples → {csv_path}")
    return csv_path


# ═══════════════════════════════════════════════════════════════
# 2. TRAIN ISOLATION FOREST
# ═══════════════════════════════════════════════════════════════

def train_isolation_forest():
    """Train IF on normal baseline data."""
    if not SKLEARN_AVAILABLE:
        log.warning("sklearn not available — skipping IF training")
        return

    log.info("Training Isolation Forest...")

    # Generate normal baseline data
    X_normal = []
    for _ in range(500):
        features = [
            max(0, np.random.normal(m, s))
            for m, s in zip(NORMAL_PROFILE["mean"], NORMAL_PROFILE["std"])
        ]
        X_normal.append(features)

    X = np.array(X_normal)
    model = IsolationForest(
        n_estimators=100,
        contamination=0.05,
        random_state=42,
    )
    model.fit(X)

    model_path = os.path.join(MODEL_DIR, "isolation_forest.joblib")
    joblib.dump(model, model_path)
    log.info(f"  ✓ IF model → {model_path}")


# ═══════════════════════════════════════════════════════════════
# 3. TRAIN RANDOM FOREST CLASSIFIER
# ═══════════════════════════════════════════════════════════════

def train_random_forest(csv_path: str):
    """Train RF classifier on labeled data."""
    if not SKLEARN_AVAILABLE:
        log.warning("sklearn not available — skipping RF training")
        return

    log.info("Training Random Forest classifier...")

    # Load data
    X, y = [], []
    with open(csv_path) as f:
        reader = csv.reader(f)
        header = next(reader)
        for row in reader:
            features = [float(v) for v in row[:-1]]
            label = row[-1]
            if label != "normal":  # RF only classifies attack types
                X.append(features)
                y.append(label)

    X = np.array(X)
    y = np.array(y)

    model = RandomForestClassifier(
        n_estimators=100,
        max_depth=12,
        random_state=42,
        class_weight="balanced",
    )
    model.fit(X, y)

    model_path = os.path.join(MODEL_DIR, "random_forest.joblib")
    joblib.dump(model, model_path)
    log.info(f"  ✓ RF model → {model_path}")
    log.info(f"    Accuracy (train): {model.score(X, y):.4f}")
    log.info(f"    Classes: {list(model.classes_)}")


# ═══════════════════════════════════════════════════════════════
# 4. GENERATE LSTM SEQUENCES AND TRAIN
# ═══════════════════════════════════════════════════════════════

FAMILY_IDS = {"pod_crash": 0, "network": 1, "resource": 2, "timing": 3, "cost": 4}
SERVICE_IDS = {"auth-service": 0, "api-gateway": 1, "order-service": 2,
               "payment-service": 3, "inventory-service": 4, "notification-service": 5}
NUM_FAMILIES = 5
NUM_SERVICES = 6
INPUT_SIZE = NUM_FAMILIES + 1 + 1 + NUM_SERVICES  # 13


def generate_lstm_sequences(num_sequences: int = 500, seq_length: int = 10):
    """Generate synthetic attack sequences for LSTM training."""
    log.info(f"Generating LSTM sequences ({num_sequences} sequences)...")

    families = list(FAMILY_IDS.keys())
    services = list(SERVICE_IDS.keys())

    # Transition matrix (what follows what)
    transitions = {
        "pod_crash": [0.10, 0.30, 0.25, 0.20, 0.15],
        "network":   [0.20, 0.10, 0.20, 0.30, 0.20],
        "resource":  [0.15, 0.20, 0.10, 0.30, 0.25],
        "timing":    [0.10, 0.15, 0.25, 0.10, 0.40],
        "cost":      [0.15, 0.20, 0.30, 0.25, 0.10],
    }

    sequences = []
    labels = []

    for _ in range(num_sequences):
        seq = []
        current_family = random.choice(families)

        for step in range(seq_length):
            fid = FAMILY_IDS[current_family]
            service = random.choice(services)
            sid = SERVICE_IDS[service]
            recovery_time = random.uniform(1000, 25000)
            success = random.random() > 0.15

            # One-hot encode
            family_onehot = [0.0] * NUM_FAMILIES
            family_onehot[fid] = 1.0
            service_onehot = [0.0] * NUM_SERVICES
            service_onehot[sid] = 1.0

            timestep = family_onehot + [recovery_time / 30000.0, 1.0 if success else 0.0] + service_onehot
            seq.append(timestep)

            # Transition
            probs = transitions[current_family]
            current_family = np.random.choice(families, p=probs)

        # Label is the next family + service after sequence
        next_fid = FAMILY_IDS[current_family]
        next_sid = SERVICE_IDS[random.choice(services)]

        sequences.append(seq)
        labels.append((next_fid, next_sid))

    log.info(f"  ✓ Generated {num_sequences} sequences of length {seq_length}")
    return sequences, labels


def train_lstm(sequences, labels):
    """Train LSTM on generated sequences."""
    if not PYTORCH_AVAILABLE:
        log.warning("PyTorch not available — skipping LSTM training")
        return

    log.info("Training LSTM model...")

    # Import model definition
    from lstm_predictor import AttackLSTM

    X_tensor = torch.FloatTensor(sequences)
    y_family = torch.LongTensor([l[0] for l in labels])
    y_service = torch.LongTensor([l[1] for l in labels])

    model = AttackLSTM()
    optimizer = optim.Adam(model.parameters(), lr=0.001)
    family_criterion = nn.CrossEntropyLoss()
    service_criterion = nn.CrossEntropyLoss()

    model.train()
    epochs = 50
    batch_size = 32

    for epoch in range(epochs):
        indices = torch.randperm(len(X_tensor))
        total_loss = 0
        n_batches = 0

        for i in range(0, len(indices), batch_size):
            batch_idx = indices[i:i+batch_size]
            x_batch = X_tensor[batch_idx]
            y_f_batch = y_family[batch_idx]
            y_s_batch = y_service[batch_idx]

            family_logits, service_logits = model(x_batch)
            loss = family_criterion(family_logits, y_f_batch) + service_criterion(service_logits, y_s_batch)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            n_batches += 1

        if (epoch + 1) % 10 == 0:
            avg_loss = total_loss / n_batches
            log.info(f"  Epoch {epoch+1}/{epochs} — Loss: {avg_loss:.4f}")

    model_path = os.path.join(MODEL_DIR, "lstm_predictor.pt")
    torch.save({
        "model_state_dict": model.state_dict(),
        "input_size": INPUT_SIZE,
        "hidden_size": 64,
        "num_layers": 2,
    }, model_path)
    log.info(f"  ✓ LSTM model → {model_path}")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("\n" + "═" * 50)
    log.info("  DARWIN TRAINING DATA GENERATOR")
    log.info("═" * 50)

    # 1. RF training data
    csv_path = generate_rf_data(samples_per_family=200)

    # 2. Train Isolation Forest
    train_isolation_forest()

    # 3. Train Random Forest
    train_random_forest(csv_path)

    # 4. LSTM sequences + training
    sequences, labels = generate_lstm_sequences(num_sequences=500, seq_length=10)
    train_lstm(sequences, labels)

    log.info("\n" + "═" * 50)
    log.info("  ✅ ALL MODELS TRAINED SUCCESSFULLY")
    log.info(f"  Model directory: {MODEL_DIR}")
    log.info("═" * 50)
