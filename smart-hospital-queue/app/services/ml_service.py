"""
ml_service.py – Machine Learning Patient Waiting-Time Prediction Service.

Responsibilities:
  - Definition of prediction target: minutes from registration/prediction until consultation starts.
  - Reproducible feature engineering without target leakage or PII.
  - Temporal train/test splitting to prevent future data leakage.
  - Random Forest Regressor training and baseline model comparison (MAE, RMSE, R²).
  - Model artifact persistence via joblib.
  - Robust inference service with in-memory model caching.
  - Safe fallback when model is not trained or data is insufficient.
  - Synthetic dataset generation clearly labelled as [SAMPLE DATA] when historical data is insufficient.
  - Strictly decoupled from QueueService: ML predicts waiting time, never alters queue priority or order.
"""

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.models import db, Department, Doctor, QueueToken
from app.services.queue_service import QueueService

logger = logging.getLogger(__name__)

# Default model artifact path
DEFAULT_MODEL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'models'))
DEFAULT_MODEL_PATH = os.path.join(DEFAULT_MODEL_DIR, 'waiting_time_model.joblib')
DEFAULT_METADATA_PATH = os.path.join(DEFAULT_MODEL_DIR, 'model_metadata.json')

# Minimum historical samples required to switch from synthetic data to real DB records.
# NOTE: 30 records is only an initial architectural threshold to trigger the pipeline,
# NOT proof or guarantee of statistically reliable real-world clinical performance.
MIN_TRAINING_SAMPLES = 30

# Feature definitions
# NOTE ON COLLINEARITY: queue_position = patients_ahead + 1. Both are retained here for
# backward compatibility with feature pipelines. Random Forest splits smoothly handle
# collinear features, but in future feature-selection passes one may be safely pruned.
CATEGORICAL_FEATURES = ['department_code', 'priority', 'registration_type']
NUMERICAL_FEATURES = [
    'priority_score',
    'queue_position',
    'patients_ahead',
    'queue_length',
    'available_doctors',
    'active_consultations',
    'hour_of_day',
    'day_of_week',
    'historical_dept_avg_wait'
]
ALL_FEATURES = CATEGORICAL_FEATURES + NUMERICAL_FEATURES
TARGET_COLUMN = 'wait_time_to_consultation'


class MedianBaselineModel:
    """
    Simple baseline predictor using historical training set medians.
    Used for objective comparison against Random Forest Regressor.
    """
    def __init__(self):
        self.global_median = 15.0
        self.dept_medians = {}

    def fit(self, X: pd.DataFrame, y: pd.Series):
        self.global_median = float(y.median()) if len(y) > 0 else 15.0
        df = X.copy()
        df['target'] = y.values
        if 'department_code' in df.columns:
            self.dept_medians = df.groupby('department_code')['target'].median().to_dict()
        return self

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        preds = []
        for _, row in X.iterrows():
            code = row.get('department_code')
            val = self.dept_medians.get(code, self.global_median)
            preds.append(val if not pd.isna(val) else self.global_median)
        return np.array(preds)


class MLService:
    """
    Centralized Waiting-Time Prediction Service.
    """
    _cached_model = None
    _cached_metadata = None
    _cached_mtime = 0

    # ── Synthetic Dataset Generator (Clearly Labelled for Dev/Testing) ─────────

    @staticmethod
    def generate_sample_dataset(n_samples: int = 500, random_state: int = 42) -> pd.DataFrame:
        """
        Generate reproducible, realistic synthetic outpatient queue events
        across all 5 hospital departments (GEN, CARD, ORTH, PED, EMG).

        LABEL: [SAMPLE DATA] - Generated exclusively for development and automated testing.
        NOT validated real-world clinical patient outcomes.
        """
        rng = np.random.RandomState(random_state)
        base_start = datetime(2026, 9, 1, 8, 0, 0)

        departments = ['GEN', 'CARD', 'ORTH', 'PED', 'EMG']
        dept_weights = [0.35, 0.20, 0.15, 0.20, 0.10]
        priorities = ['Normal', 'Medium', 'High', 'Emergency']
        prio_weights = [0.55, 0.25, 0.15, 0.05]
        reg_types = ['Walk-in', 'Online']
        reg_weights = [0.70, 0.30]

        # Department base consultation speeds (minutes)
        dept_base_consult_mins = {
            'GEN': 10.0,
            'CARD': 18.0,
            'ORTH': 14.0,
            'PED': 12.0,
            'EMG': 8.0
        }

        records = []
        for i in range(n_samples):
            # Arrival time progression over 30 days
            day_offset = int((i / n_samples) * 30)
            hour_of_day = int(rng.choice(range(8, 18), p=[0.12, 0.15, 0.15, 0.12, 0.10, 0.08, 0.08, 0.08, 0.06, 0.06]))
            minute_of_hour = int(rng.randint(0, 60))
            arrival_dt = base_start + timedelta(days=day_offset, hours=hour_of_day - 8, minutes=minute_of_hour)

            dept_code = str(rng.choice(departments, p=dept_weights))
            priority = str(rng.choice(priorities, p=prio_weights))
            reg_type = str(rng.choice(reg_types, p=reg_weights))

            prio_base_scores = {'Emergency': 1000, 'High': 500, 'Medium': 200, 'Normal': 100}
            base_score = prio_base_scores[priority]

            # Available doctors (1 to 3)
            avail_docs = int(rng.choice([1, 2, 3], p=[0.30, 0.50, 0.20]))
            active_consults = int(rng.randint(0, avail_docs + 1))

            # Queue length & position
            queue_len = int(rng.poisson(lam=6.0)) + 1
            patients_ahead = int(rng.randint(0, queue_len))
            queue_pos = patients_ahead + 1

            # Effective score with aging
            sim_wait_mins_already = int(rng.randint(0, 45))
            effective_score = base_score + (sim_wait_mins_already // 15) * 10

            # Realistic target: wait time until consultation starts
            base_consult_speed = dept_base_consult_mins[dept_code]
            # Emergency/High bypass or get served faster; Normal/Medium wait for doctor capacity
            priority_multiplier = {'Emergency': 0.15, 'High': 0.50, 'Medium': 0.85, 'Normal': 1.05}[priority]
            rate = base_consult_speed / max(1, avail_docs)

            expected_wait = (patients_ahead * rate * priority_multiplier) + rng.normal(loc=2.0, scale=3.0)
            actual_wait = max(1.0, round(float(expected_wait), 1))

            records.append({
                'created_at': arrival_dt,
                'department_code': dept_code,
                'priority': priority,
                'priority_score': effective_score,
                'queue_position': queue_pos,
                'patients_ahead': patients_ahead,
                'queue_length': queue_len,
                'available_doctors': avail_docs,
                'active_consultations': active_consults,
                'registration_type': reg_type,
                'hour_of_day': arrival_dt.hour,
                'day_of_week': arrival_dt.weekday(),
                'is_synthetic': True,
                TARGET_COLUMN: actual_wait
            })

        df = pd.DataFrame(records)
        df.sort_values('created_at', inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    # ── Database Extraction ──────────────────────────────────────────────────

    @staticmethod
    def extract_historical_dataset_from_db() -> Optional[pd.DataFrame]:
        """
        Extract completed historical consultation records from the database.
        Computes the target variable without target leakage.
        Excludes uncompleted, cancelled, or corrupted records.
        """
        tokens = QueueToken.query.filter(
            QueueToken.status.in_(['Completed', 'In-Consultation']),
            QueueToken.created_at.isnot(None)
        ).all()

        records = []
        for t in tokens:
            # Determine start time
            start_dt = t.consultation_started_at or t.called_at
            if not start_dt or not t.created_at:
                continue

            created = t.created_at
            # Timezone-safe normalization
            if created.tzinfo is not None and start_dt.tzinfo is None:
                start_dt = start_dt.replace(tzinfo=timezone.utc)
            elif created.tzinfo is None and start_dt.tzinfo is not None:
                start_dt = start_dt.astimezone(timezone.utc).replace(tzinfo=None)

            wait_mins = (start_dt - created).total_seconds() / 60.0
            if wait_mins < 0.0 or wait_mins > 720.0:  # Exclude negative or >12hr outliers
                continue

            dept_code = t.department.code if t.department else 'GEN'

            records.append({
                'created_at': created,
                'department_code': dept_code,
                'priority': t.priority,
                'priority_score': t.priority_score,
                'queue_position': 1,  # Best proxy when retrospective
                'patients_ahead': 0,
                'queue_length': 1,
                'available_doctors': 1,
                'active_consultations': 1,
                'registration_type': t.registration_type or 'Walk-in',
                'hour_of_day': created.hour,
                'day_of_week': created.weekday(),
                'is_synthetic': False,
                TARGET_COLUMN: round(float(wait_mins), 1)
            })

        if len(records) < MIN_TRAINING_SAMPLES:
            return None

        df = pd.DataFrame(records)
        df.sort_values('created_at', inplace=True)
        df.reset_index(drop=True, inplace=True)
        return df

    @classmethod
    def get_or_create_training_dataset(cls, force_synthetic: bool = False,
                                       n_synthetic: int = 500) -> Tuple[pd.DataFrame, bool]:
        """
        Retrieve training dataset. If trustworthy historical DB records are
        fewer than MIN_TRAINING_SAMPLES, falls back to clearly labelled synthetic data.

        Returns: (DataFrame, is_synthetic_flag)
        """
        if not force_synthetic:
            try:
                db_df = cls.extract_historical_dataset_from_db()
                if db_df is not None and len(db_df) >= MIN_TRAINING_SAMPLES:
                    return db_df, False
            except Exception as e:
                logger.warning("Could not extract DB historical data for ML: %s", e)

        # Fallback to reproducible synthetic development dataset
        syn_df = cls.generate_sample_dataset(n_samples=n_synthetic, random_state=42)
        return syn_df, True

    # ── Model Training & Evaluation ──────────────────────────────────────────

    @classmethod
    def train_and_evaluate(
        cls,
        dataset_df: Optional[pd.DataFrame] = None,
        save_path: str = DEFAULT_MODEL_PATH,
        metadata_path: str = DEFAULT_METADATA_PATH,
        test_size: float = 0.20,
        random_state: int = 42
    ) -> Dict[str, Any]:
        """
        Train a Random Forest Regressor and evaluate against a Median baseline.
        Uses a strict temporal train/test split (no future leakage).

        Returns evaluation metrics dictionary.
        """
        if dataset_df is None:
            dataset_df, is_synthetic = cls.get_or_create_training_dataset()
        else:
            is_synthetic = bool(dataset_df.get('is_synthetic', pd.Series([False])).iloc[0])

        if len(dataset_df) < 10:
            raise ValueError(f"Insufficient training samples: {len(dataset_df)}. Need at least 10.")

        # Ensure temporal ordering
        df = dataset_df.sort_values('created_at').reset_index(drop=True).copy()

        # Compute historical department average wait strictly on the training partition (no leakage)
        split_idx = int(len(df) * (1.0 - test_size))
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()

        dept_avg_train = train_df.groupby('department_code')[TARGET_COLUMN].mean().to_dict()
        overall_train_avg = float(train_df[TARGET_COLUMN].mean())

        # Map department statistics back
        train_df['historical_dept_avg_wait'] = train_df['department_code'].map(
            lambda c: dept_avg_train.get(c, overall_train_avg)
        )
        test_df['historical_dept_avg_wait'] = test_df['department_code'].map(
            lambda c: dept_avg_train.get(c, overall_train_avg)
        )

        X_train = train_df[ALL_FEATURES]
        y_train = train_df[TARGET_COLUMN]
        X_test = test_df[ALL_FEATURES]
        y_test = test_df[TARGET_COLUMN]

        # ── 1. Evaluate Baseline Model ───────────────────────────────────────
        baseline = MedianBaselineModel()
        baseline.fit(X_train, y_train)
        y_pred_baseline = baseline.predict(X_test)

        baseline_mae = float(mean_absolute_error(y_test, y_pred_baseline))
        baseline_rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_baseline)))

        # ── 2. Train Random Forest Regressor Pipeline ────────────────────────
        preprocessor = ColumnTransformer(
            transformers=[
                ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), CATEGORICAL_FEATURES),
                ('num', StandardScaler(), NUMERICAL_FEATURES)
            ]
        )

        rf = RandomForestRegressor(
            n_estimators=100,
            max_depth=8,
            min_samples_split=4,
            random_state=random_state,
            n_jobs=1
        )

        pipeline = Pipeline(steps=[
            ('preprocessor', preprocessor),
            ('regressor', rf)
        ])

        pipeline.fit(X_train, y_train)

        # ── 3. Evaluate Random Forest Model ──────────────────────────────────
        y_pred_rf = pipeline.predict(X_test)
        rf_mae = float(mean_absolute_error(y_test, y_pred_rf))
        rf_rmse = float(np.sqrt(mean_squared_error(y_test, y_pred_rf)))
        rf_r2 = float(r2_score(y_test, y_pred_rf)) if len(y_test) > 1 else 0.0

        # Save artifacts
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        artifact_bundle = {
            'pipeline': pipeline,
            'dept_averages': dept_avg_train,
            'overall_avg': overall_train_avg,
            'features': ALL_FEATURES,
            'target': TARGET_COLUMN,
            'trained_at': datetime.now(timezone.utc).isoformat()
        }
        joblib.dump(artifact_bundle, save_path)

        metadata = {
            'model_name': 'RandomForestRegressor',
            'trained_at': artifact_bundle['trained_at'],
            'total_samples': len(df),
            'train_samples': len(train_df),
            'test_samples': len(test_df),
            'test_split_ratio': test_size,
            'is_synthetic_dataset': is_synthetic,
            'features': ALL_FEATURES,
            'target': TARGET_COLUMN,
            'evaluation': {
                'baseline_median': {
                    'mae': round(baseline_mae, 2),
                    'rmse': round(baseline_rmse, 2)
                },
                'random_forest': {
                    'mae': round(rf_mae, 2),
                    'rmse': round(rf_rmse, 2),
                    'r2': round(rf_r2, 4)
                }
            },
            'dataset_temporal_range': {
                'start': str(df['created_at'].min()),
                'end': str(df['created_at'].max())
            }
        }

        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2)

        # Invalidate in-memory cache
        cls._cached_model = None
        cls._cached_metadata = None

        return metadata

    # ── Model Loading (Cached / Thread-Safe) ──────────────────────────────────

    @classmethod
    def load_model(cls, model_path: str = DEFAULT_MODEL_PATH,
                   metadata_path: str = DEFAULT_METADATA_PATH) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """
        Safely load the trained ML pipeline and metadata.
        Uses cached singleton to avoid reloading from disk on every request.
        """
        if not os.path.exists(model_path):
            return None, None

        try:
            mtime = os.path.getmtime(model_path)
            if cls._cached_model is not None and cls._cached_mtime == mtime:
                return cls._cached_model, cls._cached_metadata

            bundle = joblib.load(model_path)
            metadata = None
            if os.path.exists(metadata_path):
                try:
                    with open(metadata_path, 'r', encoding='utf-8') as f:
                        metadata = json.load(f)
                except Exception:
                    pass

            cls._cached_model = bundle
            cls._cached_metadata = metadata
            cls._cached_mtime = mtime
            return bundle, metadata
        except Exception as e:
            logger.error("Failed to load ML model from %s: %s", model_path, e)
            return None, None

    # ── Feature Extraction for Inference ─────────────────────────────────────

    @classmethod
    def build_features_for_token(
        cls,
        token: Optional[QueueToken],
        department_queue: Optional[list] = None,
        available_doctors: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Construct the inference feature row for a given QueueToken
        using observable queue states. Avoids any future information or PII.

        Handles missing, unpersisted, or malformed token attributes defensively.
        Enforces exact canonical ALL_FEATURES column order.
        """
        now = datetime.now(timezone.utc)
        dept_code = token.department.code if (token and token.department) else 'GEN'
        dept_id = token.department_id if token else None

        # Fetch queue if not supplied
        if department_queue is None:
            department_queue = QueueService.get_department_queue(dept_id) if dept_id else []

        # Calculate position ahead in queue
        queue_pos = 1
        for idx, t in enumerate(department_queue):
            if token and t.id == token.id:
                queue_pos = idx + 1
                break
        patients_ahead = max(0, queue_pos - 1)
        queue_len = len(department_queue)

        # Doctor availability
        if available_doctors is None:
            if dept_id:
                available_doctors = Doctor.query.filter_by(
                    department_id=dept_id,
                    is_available=True
                ).count()
            else:
                available_doctors = 1
        available_doctors = max(1, available_doctors)

        # Active consultations
        active_consults = 0
        if dept_id:
            active_consults = QueueToken.query.filter_by(
                department_id=dept_id,
                status='In-Consultation'
            ).count()

        # Model bundle averages (or defaults)
        bundle, _ = cls.load_model()
        dept_avgs = bundle.get('dept_averages', {}) if bundle else {}
        overall_avg = bundle.get('overall_avg', 15.0) if bundle else 15.0
        hist_avg = dept_avgs.get(dept_code, overall_avg)

        row = {
            'department_code': dept_code,
            'priority': (token.priority if token and token.priority else 'Normal'),
            'registration_type': (token.registration_type if token and token.registration_type else 'Walk-in'),
            'priority_score': (token.priority_score if token and token.priority_score is not None else 100),
            'queue_position': queue_pos,
            'patients_ahead': patients_ahead,
            'queue_length': queue_len,
            'available_doctors': available_doctors,
            'active_consultations': active_consults,
            'hour_of_day': now.hour,
            'day_of_week': now.weekday(),
            'historical_dept_avg_wait': hist_avg
        }
        return pd.DataFrame([row])[ALL_FEATURES]

    # ── Inference / Prediction ───────────────────────────────────────────────

    @classmethod
    def predict_waiting_time(
        cls,
        token: Optional[QueueToken],
        department_queue: Optional[list] = None,
        available_doctors: Optional[int] = None
    ) -> Optional[float]:
        """
        Predict estimated additional waiting time in minutes until consultation starts.

        Returns:
          float: estimated minutes (bounded >= 0.0)
          None: if token is None, model is not trained, or prediction fails gracefully.

        STRICT RULE: Never alters queue ordering or patient priority.
        """
        if token is None:
            return None

        bundle, _ = cls.load_model()
        if not bundle or 'pipeline' not in bundle:
            return None

        try:
            pipeline = bundle['pipeline']
            feat_df = cls.build_features_for_token(token, department_queue, available_doctors)
            raw_pred = pipeline.predict(feat_df)[0]
            # Ensure non-negative prediction
            pred_mins = max(0.0, round(float(raw_pred), 1))
            return pred_mins
        except Exception as e:
            token_num = getattr(token, 'token_number', 'UNKNOWN') if token else 'UNKNOWN'
            logger.warning("Error predicting wait time for token %s: %s", token_num, e)
            return None

    # ── Dataset CSV Export ───────────────────────────────────────────────────

    @classmethod
    def export_dataset_csv(cls, filepath: str, dataset_df: Optional[pd.DataFrame] = None) -> str:
        """
        Export training dataset to CSV for inspection/documentation without PII.
        """
        if dataset_df is None:
            dataset_df, _ = cls.get_or_create_training_dataset()

        # Select only model features + target (no patient identifiers)
        export_cols = [c for c in dataset_df.columns if c not in ['patient_name', 'phone', 'email', 'patient_code']]
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        dataset_df[export_cols].to_csv(filepath, index=False)
        return filepath
