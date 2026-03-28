"""
Model Loader — loads pre-trained models from Chaos_Platform_Assets/models/
DO NOT modify the model files. Load and use them directly.

Models:
  isolation_forest.joblib   — sklearn IsolationForest, trained on baseline_metrics.csv
  random_forest.joblib      — sklearn RandomForestClassifier, 5 classes, 87.6% accuracy
  lstm_predictor.pt         — PyTorch LSTM, 2-layer 64-hidden, predicts next attack family
"""

import logging
import os
from pathlib import Path

import joblib
import numpy as np

logger = logging.getLogger(__name__)

# Path relative to this file: ../../Chaos_Platform_Assets/models/
_THIS_DIR   = Path(__file__).parent
_MODELS_DIR = _THIS_DIR.parent / "Chaos_Platform_Assets" / "models"

# RF class mapping (order must match training data labels from rf_training_data.csv)
RF_CLASSES = ["pod_crash", "network", "resource", "timing", "camouflage"]

# LSTM attack family → integer index
FAMILY_TO_IDX = {f: i for i, f in enumerate(RF_CLASSES)}
IDX_TO_FAMILY = {i: f for f, i in FAMILY_TO_IDX.items()}


class ModelLoader:
    """
    Loads isolation_forest.joblib, random_forest.joblib, lstm_predictor.pt
    from Chaos_Platform_Assets/models/.

    Falls back to rule-based logic if files are missing.
    """

    def __init__(self, models_dir: Path = _MODELS_DIR):
        self.models_dir = models_dir
        self.if_model   = None
        self.rf_model   = None
        self.lstm_model = None
        self._torch_available = False

    def load_all(self):
        """Load all three models. Logs warnings but does not crash on failure."""
        self._load_isolation_forest()
        self._load_random_forest()
        self._load_lstm()

    # ─── Loaders ─────────────────────────────────────────────────────────────

    def _load_isolation_forest(self):
        path = self.models_dir / "isolation_forest.joblib"
        if not path.exists():
            logger.warning(f"⚠️  IF model not found at {path} — using score=0 fallback")
            return
        try:
            self.if_model = joblib.load(path)
            logger.info(f"✅ IsolationForest loaded from {path}")
        except Exception as e:
            logger.error(f"❌ Failed to load IF model: {e}")

    def _load_random_forest(self):
        path = self.models_dir / "random_forest.joblib"
        if not path.exists():
            logger.warning(f"⚠️  RF model not found at {path} — using rule-based fallback")
            return
        try:
            self.rf_model = joblib.load(path)
            logger.info(f"✅ RandomForest loaded from {path}")
        except Exception as e:
            logger.error(f"❌ Failed to load RF model: {e}")

    def _load_lstm(self):
        path = self.models_dir / "lstm_predictor.pt"
        if not path.exists():
            logger.warning(f"⚠️  LSTM model not found at {path} — prediction disabled")
            return
        try:
            import torch
            self._torch_available = True

            # Rebuild the exact same architecture used during training
            # (2 LSTM layers, 64 hidden, dropout 0.3, linear head over 5 classes)
            class LSTMPredictor(torch.nn.Module):
                def __init__(self, input_size=3, hidden_size=64, num_layers=2, num_classes=5):
                    super().__init__()
                    self.lstm = torch.nn.LSTM(
                        input_size, hidden_size, num_layers,
                        batch_first=True, dropout=0.3
                    )
                    self.fc = torch.nn.Linear(hidden_size, num_classes)

                def forward(self, x):
                    out, _ = self.lstm(x)
                    return self.fc(out[:, -1, :])

            model = LSTMPredictor()
            state = torch.load(path, map_location="cpu", weights_only=True)
            model.load_state_dict(state)
            model.eval()
            self.lstm_model = model
            logger.info(f"✅ LSTM loaded from {path}")
        except Exception as e:
            logger.error(f"❌ Failed to load LSTM model: {e}")

    # ─── Inference API ────────────────────────────────────────────────────────

    def if_score(self, feature_vec: list[float]) -> float:
        """
        Returns anomaly score in range [0, 1].
        sklearn decision_function returns negative-is-anomaly;
        we invert and normalize to [0,1].
        """
        if self.if_model is None:
            return 0.0
        try:
            arr = np.array(feature_vec, dtype=np.float32).reshape(1, -1)
            raw = self.if_model.decision_function(arr)[0]
            # Typical range is roughly [-0.5, 0.5]; invert so higher = more anomalous
            score = float(np.clip(0.5 - raw, 0.0, 1.0))
            return score
        except Exception as e:
            logger.error(f"IF inference error: {e}")
            return 0.0

    def rf_classify(self, feature_vec: list[float]) -> tuple[str, float]:
        """
        Returns (attack_family_label, confidence_score).
        Falls back to rule-based logic if model unavailable.
        """
        if self.rf_model is None:
            return self._rule_based_classify(feature_vec)
        try:
            arr = np.array(feature_vec, dtype=np.float32).reshape(1, -1)
            label_idx = int(self.rf_model.predict(arr)[0])
            probas    = self.rf_model.predict_proba(arr)[0]
            confidence = float(probas[label_idx])
            # Convert numeric label to family name
            if hasattr(self.rf_model, "classes_"):
                label = str(self.rf_model.classes_[label_idx])
            else:
                label = RF_CLASSES[label_idx] if label_idx < len(RF_CLASSES) else "unknown"
            return label, confidence
        except Exception as e:
            logger.error(f"RF inference error: {e}")
            return self._rule_based_classify(feature_vec)

    def lstm_predict(self, history: list[dict]) -> tuple[str | None, float]:
        """
        Predict next attack family from sequence of past events.
        history: list of dicts with keys: family, recovery_time, success
        Returns (predicted_family, confidence) or (None, 0.0) on failure.
        """
        if self.lstm_model is None or not self._torch_available:
            return None, 0.0
        try:
            import torch
            import torch.nn.functional as F

            # Encode: family_idx, normalized_recovery_time, success_flag
            seq = []
            for h in history[-7:]:   # last 7 events max
                fam_idx    = FAMILY_TO_IDX.get(h.get("family", "pod_crash"), 0)
                rec_time   = min(h.get("recovery_time", 18000) / 20000.0, 1.0)
                success    = 1.0 if h.get("success", True) else 0.0
                seq.append([fam_idx / 4.0, rec_time, success])

            if len(seq) < 2:
                return None, 0.0

            tensor = torch.tensor([seq], dtype=torch.float32)  # shape [1, seq_len, 3]
            with torch.no_grad():
                logits  = self.lstm_model(tensor)
                probas  = F.softmax(logits, dim=-1)[0]
                idx     = int(torch.argmax(probas).item())
                conf    = float(probas[idx].item())

            return IDX_TO_FAMILY.get(idx, "pod_crash"), conf
        except Exception as e:
            logger.error(f"LSTM inference error: {e}")
            return None, 0.0

    # ─── Rule-based fallback ──────────────────────────────────────────────────

    @staticmethod
    def _rule_based_classify(features: list[float]) -> tuple[str, float]:
        """
        Deterministic fallback matching db_core.infer_remedy_from_metrics logic.
        features = [cpu, mem, err_rate, latency, restarts, net_rx, net_tx]
        """
        cpu, mem, err_rate, latency, restarts = features[:5]
        if restarts > 0.5:
            return "pod_crash", 0.80
        if err_rate > 0.3 or latency > 2.0:
            return "network",   0.75
        if cpu > 80 or mem > 85:
            return "resource",  0.78
        return "pod_crash", 0.50
