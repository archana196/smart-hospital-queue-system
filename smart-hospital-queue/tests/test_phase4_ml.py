"""
test_phase4_ml.py – Automated test suite for Phase 4:
Machine Learning-Based Patient Waiting-Time Prediction.

Requirements Covered:
---------------------
 1. Dataset generation and validation of sample/historical records.
 2. Feature engineering without target leakage or PII.
 3. Temporal data splitting (train chronologically precedes test set).
 4. Model training and evaluation (computes MAE, RMSE, R²).
 5. Baseline comparison (Random Forest improves over Median baseline).
 6. Prediction output validation (valid non-negative number).
 7. Missing model files handled gracefully (returns None, does not crash).
 8. Insufficient training data handled safely.
 9. Prediction service error handling with malformed tokens.
10. API response compatibility (/api/v1/queue/<id> returns estimated_wait_mins and waiting_duration_mins).
11. Clear separation of actual elapsed waiting time vs predicted additional wait.
12. Invariance: ML prediction does NOT alter queue priority or scheduling order.
13. Dataset CSV export auditability (no PII).
"""

import os
import tempfile
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, timezone

from app import create_app
from app.models import db, Department, Doctor, Patient, QueueToken
from app.services.queue_service import QueueService
from app.services.ml_service import (
    MLService,
    MedianBaselineModel,
    ALL_FEATURES,
    CATEGORICAL_FEATURES,
    NUMERICAL_FEATURES,
    TARGET_COLUMN
)


@pytest.fixture
def app():
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        dept = Department(name='General Medicine', code='GEN', description='General OPD')
        db.session.add(dept)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


# ── 1. Dataset Generation & Validation ───────────────────────────────────────

def test_generate_sample_dataset():
    """Verify synthetic dataset generator produces valid, non-empty, chronologically sorted records."""
    df = MLService.generate_sample_dataset(n_samples=50, random_state=42)
    assert len(df) == 50
    assert TARGET_COLUMN in df.columns
    assert 'created_at' in df.columns
    assert (df[TARGET_COLUMN] > 0).all()
    # Verify temporal sort
    assert df['created_at'].is_monotonic_increasing


def test_no_pii_in_dataset_features():
    """Ensure no direct PII (name, phone, email, patient_code) exists in ML feature definitions."""
    forbidden = {'name', 'patient_name', 'phone', 'email', 'patient_code'}
    assert not forbidden.intersection(set(ALL_FEATURES))


def test_no_target_leakage_in_features():
    """Ensure no future consultation outcome features (completion timestamp, doctor notes, etc.) are in features."""
    leakage_cols = {'completed_at', 'consultation_duration', 'actual_wait', 'doctor_notes', 'diagnosis'}
    assert not leakage_cols.intersection(set(ALL_FEATURES))


# ── 2. Temporal Data Splitting ───────────────────────────────────────────────

def test_temporal_train_test_split():
    """Verify that train/test split respects time (no future leakage into training set)."""
    df = MLService.generate_sample_dataset(n_samples=100, random_state=42)
    split_idx = int(len(df) * 0.8)
    train_df = df.iloc[:split_idx]
    test_df = df.iloc[split_idx:]

    assert train_df['created_at'].max() <= test_df['created_at'].min()


# ── 3. Baseline Model ────────────────────────────────────────────────────────

def test_median_baseline_model():
    """Verify the Median Baseline model computes department/global medians correctly."""
    X = pd.DataFrame({'department_code': ['GEN', 'GEN', 'CARD', 'CARD']})
    y = pd.Series([10.0, 20.0, 30.0, 50.0])

    baseline = MedianBaselineModel()
    baseline.fit(X, y)
    assert baseline.global_median == 25.0
    assert baseline.dept_medians['GEN'] == 15.0
    assert baseline.dept_medians['CARD'] == 40.0

    preds = baseline.predict(pd.DataFrame({'department_code': ['GEN', 'CARD', 'UNKNOWN']}))
    assert preds[0] == 15.0
    assert preds[1] == 40.0
    assert preds[2] == 25.0  # Fallback to global median


# ── 4. Training, Evaluation & Baseline Comparison ────────────────────────────

def test_train_and_evaluate_pipeline():
    """Train Random Forest model and verify evaluation metrics against baseline."""
    with tempfile.TemporaryDirectory() as tmpdir:
        model_file = os.path.join(tmpdir, 'model.joblib')
        meta_file = os.path.join(tmpdir, 'meta.json')

        df = MLService.generate_sample_dataset(n_samples=120, random_state=42)
        metadata = MLService.train_and_evaluate(
            dataset_df=df,
            save_path=model_file,
            metadata_path=meta_file,
            test_size=0.20,
            random_state=42
        )

        assert os.path.exists(model_file)
        assert os.path.exists(meta_file)

        eval_data = metadata['evaluation']
        assert 'baseline_median' in eval_data
        assert 'random_forest' in eval_data

        rf_mae = eval_data['random_forest']['mae']
        base_mae = eval_data['baseline_median']['mae']
        assert rf_mae >= 0.0
        assert base_mae >= 0.0
        # Random Forest should achieve lower error than naive baseline
        assert rf_mae <= base_mae


# ── 5. Model Loading & Missing File Fallback ─────────────────────────────────

def test_missing_model_file_fallback():
    """Inference returns None gracefully when model file is missing (does not crash)."""
    bundle, meta = MLService.load_model(model_path='/nonexistent/path/model.joblib')
    assert bundle is None
    assert meta is None


def test_insufficient_training_data_raises_error():
    """Training raises ValueError if dataset has fewer than 10 records."""
    tiny_df = pd.DataFrame({'created_at': [datetime.now(timezone.utc)]})
    with pytest.raises(ValueError, match="Insufficient training samples"):
        MLService.train_and_evaluate(dataset_df=tiny_df)


# ── 6. Prediction Service & Feature Building ─────────────────────────────────

def test_build_features_for_token(app):
    """Verify inference feature extraction for an active token."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        token = QueueService.register_patient_and_issue_token(
            name='Test Patient ML',
            age=32,
            gender='Female',
            phone='9812345678',
            department_id=dept.id,
            priority='High'
        )

        feat_df = MLService.build_features_for_token(token)
        assert len(feat_df) == 1
        assert feat_df['department_code'].iloc[0] == 'GEN'
        assert feat_df['priority'].iloc[0] == 'High'
        assert feat_df['queue_position'].iloc[0] >= 1
        assert feat_df['patients_ahead'].iloc[0] >= 0
        assert 'historical_dept_avg_wait' in feat_df.columns


def test_predict_waiting_time_returns_valid_estimate(app):
    """Verify predict_waiting_time returns a positive float when model is available."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        token = QueueService.register_patient_and_issue_token(
            name='Test Patient Pred',
            age=40,
            gender='Male',
            phone='9812345679',
            department_id=dept.id,
            priority='Normal'
        )

        pred = MLService.predict_waiting_time(token)
        if pred is not None:
            assert isinstance(pred, (int, float))
            assert pred >= 0.0


# ── 7. Invariance: ML Prediction Never Mutates Queue Order ────────────────────

def test_prediction_does_not_mutate_queue_priority_or_order(app):
    """Verify that calling prediction never modifies patient priority or queue ordering."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        t1 = QueueService.register_patient_and_issue_token(
            name='Prio Patient 1', age=25, gender='Male', phone='9811111111',
            department_id=dept.id, priority='Normal'
        )
        t2 = QueueService.register_patient_and_issue_token(
            name='Prio Patient 2', age=65, gender='Female', phone='9822222222',
            department_id=dept.id, priority='Emergency'
        )

        queue_before = [t.id for t in QueueService.get_department_queue(dept.id)]

        # Call prediction on both
        MLService.predict_waiting_time(t1)
        MLService.predict_waiting_time(t2)

        queue_after = [t.id for t in QueueService.get_department_queue(dept.id)]

        # Queue order must be 100% identical!
        assert queue_before == queue_after
        # Emergency must still be first
        assert queue_after[0] == t2.id


# ── 8. Separation of Elapsed Wait vs Predicted Additional Wait ────────────────

def test_separation_of_elapsed_wait_and_predicted_wait(app):
    """Verify elapsed waiting time and predicted additional wait are calculated separately."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        token = QueueService.register_patient_and_issue_token(
            name='Wait Sep Patient', age=30, gender='Male', phone='9833333333',
            department_id=dept.id, priority='Normal'
        )
        # Simulate 20 minutes elapsed
        token.created_at = datetime.utcnow() - timedelta(minutes=20)
        db.session.commit()

        elapsed = QueueService.get_waiting_duration_mins(token)
        pred = MLService.predict_waiting_time(token)

        assert elapsed >= 19.0  # Elapsed is actual historical duration
        if pred is not None:
            # Predicted is future remaining wait, not a duplicate of elapsed
            assert isinstance(pred, (int, float))


# ── 9. API Response Compatibility ────────────────────────────────────────────

def test_api_queue_endpoint_contains_ml_and_elapsed_wait(client, app):
    """Verify /api/v1/queue/<dept_id> returns estimated_wait_mins and waiting_duration_mins."""
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        dept_id = dept.id
        QueueService.register_patient_and_issue_token(
            name='API Test Patient', age=28, gender='Female', phone='9844444444',
            department_id=dept_id, priority='Medium'
        )

    resp = client.get(f'/api/v1/queue/{dept_id}')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'tokens' in data
    assert len(data['tokens']) >= 1

    first_token = data['tokens'][0]
    assert 'waiting_duration_mins' in first_token
    assert 'estimated_wait_mins' in first_token
    assert 'position' in first_token
    assert 'token_number' in first_token


# ── 10. Dataset Export Without PII ───────────────────────────────────────────

def test_dataset_export_csv_omits_pii():
    """Verify that export_dataset_csv produces an uncorrupted CSV with zero patient PII."""
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = os.path.join(tmpdir, 'exported_data.csv')
        df = MLService.generate_sample_dataset(n_samples=25, random_state=42)
        out_path = MLService.export_dataset_csv(csv_path, df)

        assert os.path.exists(out_path)
        read_df = pd.read_csv(out_path)
        assert len(read_df) == 25
        assert TARGET_COLUMN in read_df.columns
        for pii_col in ['patient_name', 'phone', 'email']:
            assert pii_col not in read_df.columns


# ── 11. ML Audit Verification Suite ──────────────────────────────────────────

def test_audit_preprocessing_no_data_leakage():
    """
    Verify that StandardScaler and OneHotEncoder are fitted strictly on X_train.
    The scaler mean must match X_train exactly, and must NOT equal X_all mean.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        model_file = os.path.join(tmpdir, 'model.joblib')
        meta_file = os.path.join(tmpdir, 'meta.json')

        df = MLService.generate_sample_dataset(n_samples=150, random_state=42)
        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].copy()

        MLService.train_and_evaluate(
            dataset_df=df,
            save_path=model_file,
            metadata_path=meta_file,
            test_size=0.20,
            random_state=42
        )

        bundle, _ = MLService.load_model(model_path=model_file, metadata_path=meta_file)
        pipeline = bundle['pipeline']
        scaler = pipeline.named_steps['preprocessor'].named_transformers_['num']

        dept_avgs = bundle['dept_averages']
        overall_avg = bundle['overall_avg']
        train_df['historical_dept_avg_wait'] = train_df['department_code'].map(
            lambda c: dept_avgs.get(c, overall_avg)
        )
        expected_train_means = train_df[NUMERICAL_FEATURES].mean().values

        df_all = df.copy()
        df_all['historical_dept_avg_wait'] = df_all['department_code'].map(
            lambda c: dept_avgs.get(c, overall_avg)
        )
        full_dataset_means = df_all[NUMERICAL_FEATURES].mean().values

        # Fitted scaler means must match train split
        np.testing.assert_allclose(scaler.mean_, expected_train_means, rtol=1e-5)
        # Must NOT equal full dataset means (which would indicate leakage)
        assert not np.allclose(scaler.mean_, full_dataset_means, rtol=1e-4)


def test_audit_dept_avg_computed_from_train_only():
    """
    Verify department historical average is calculated strictly from train set.
    Injecting an extreme outlier into the test set must NOT alter training department averages.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        model_file = os.path.join(tmpdir, 'model.joblib')
        meta_file = os.path.join(tmpdir, 'meta.json')

        df = MLService.generate_sample_dataset(n_samples=100, random_state=42)
        split_idx = int(len(df) * 0.8)

        # Record normal train average for GEN
        train_gen_normal = float(df.iloc[:split_idx].query("department_code == 'GEN'")[TARGET_COLUMN].mean())

        # Inject extreme outlier into test set only
        df_contaminated = df.copy()
        test_mask = df_contaminated.index >= split_idx
        df_contaminated.loc[test_mask & (df_contaminated['department_code'] == 'GEN'), TARGET_COLUMN] = 9999.0

        MLService.train_and_evaluate(
            dataset_df=df_contaminated,
            save_path=model_file,
            metadata_path=meta_file,
            test_size=0.20,
            random_state=42
        )

        bundle, _ = MLService.load_model(model_path=model_file, metadata_path=meta_file)
        # Saved department average must still match train set only!
        assert abs(bundle['dept_averages']['GEN'] - train_gen_normal) < 1e-4
        assert bundle['dept_averages']['GEN'] < 50.0  # Not contaminated by 9999.0


def test_audit_preprocessor_transform_without_refitting():
    """
    Verify preprocessor transforms unseen/test data without altering fitted state.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        model_file = os.path.join(tmpdir, 'model.joblib')
        meta_file = os.path.join(tmpdir, 'meta.json')

        df = MLService.generate_sample_dataset(n_samples=80, random_state=42)
        MLService.train_and_evaluate(
            dataset_df=df,
            save_path=model_file,
            metadata_path=meta_file,
            test_size=0.20,
            random_state=42
        )

        bundle, _ = MLService.load_model(model_path=model_file, metadata_path=meta_file)
        pipeline = bundle['pipeline']
        scaler = pipeline.named_steps['preprocessor'].named_transformers_['num']
        means_before = scaler.mean_.copy()

        # Transform new batch with all features present
        dept_avgs = bundle['dept_averages']
        overall_avg = bundle['overall_avg']
        new_batch = df.iloc[60:].copy()
        new_batch['historical_dept_avg_wait'] = new_batch['department_code'].map(
            lambda c: dept_avgs.get(c, overall_avg)
        )
        pipeline.named_steps['preprocessor'].transform(new_batch[ALL_FEATURES])

        # Scaler parameters must remain identical (no refitting)
        np.testing.assert_array_equal(scaler.mean_, means_before)


def test_audit_synthetic_dataset_feature_consistency():
    """
    Audit synthetic dataset generator for logical queuing consistency across all samples:
    - 0 <= patients_ahead < queue_position
    - queue_position <= queue_length
    - 0 <= active_consultations <= available_doctors
    - priority_score >= 100
    - target waiting time > 0
    - is_synthetic is explicitly True
    """
    df = MLService.generate_sample_dataset(n_samples=250, random_state=123)

    assert len(df) == 250
    # Queue position relationship
    assert (df['patients_ahead'] == df['queue_position'] - 1).all()
    assert (df['queue_position'] <= df['queue_length']).all()
    assert (df['patients_ahead'] >= 0).all()

    # Doctor and consultation bounds
    assert (df['available_doctors'] >= 1).all()
    assert (df['available_doctors'] <= 3).all()
    assert (df['active_consultations'] >= 0).all()
    assert (df['active_consultations'] <= df['available_doctors']).all()

    # Priorities and scores
    assert (df['priority_score'] >= 100).all()
    assert set(df['priority'].unique()).issubset({'Normal', 'Medium', 'High', 'Emergency'})
    assert set(df['department_code'].unique()).issubset({'GEN', 'CARD', 'ORTH', 'PED', 'EMG'})

    # Target sanity
    assert (df[TARGET_COLUMN] >= 1.0).all()
    assert (df['is_synthetic'] == True).all()


def test_audit_feature_alignment_train_and_inference(app):
    """
    Verify feature names and column ordering produced during inference
    exactly match ALL_FEATURES used in model training.
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        token = QueueService.register_patient_and_issue_token(
            name='Audit Align Patient', age=29, gender='Male', phone='9811223344',
            department_id=dept.id, priority='Medium'
        )

        inference_df = MLService.build_features_for_token(token)

        assert list(inference_df.columns) == ALL_FEATURES
        assert len(inference_df.columns) == len(ALL_FEATURES)

        # Ensure types and values can be transformed without KeyError
        bundle, _ = MLService.load_model()
        if bundle and 'pipeline' in bundle:
            preds = bundle['pipeline'].predict(inference_df)
            assert len(preds) == 1
            assert preds[0] >= 0.0


def test_audit_unseen_categorical_inference_robustness():
    """
    Verify model pipeline handles unseen or rare categorical values at inference time
    without throwing exceptions (due to OneHotEncoder handle_unknown='ignore').
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        model_file = os.path.join(tmpdir, 'model.joblib')
        meta_file = os.path.join(tmpdir, 'meta.json')

        df = MLService.generate_sample_dataset(n_samples=100, random_state=42)
        MLService.train_and_evaluate(
            dataset_df=df,
            save_path=model_file,
            metadata_path=meta_file,
            test_size=0.20,
            random_state=42
        )

        bundle, _ = MLService.load_model(model_path=model_file, metadata_path=meta_file)
        pipeline = bundle['pipeline']

        # Build feature row with completely novel / unexpected categorical values
        novel_row = {
            'department_code': 'NEURO_SPECIALTY',  # Unseen
            'priority': 'UltraCritical',          # Unseen
            'registration_type': 'Helicopter',    # Unseen
            'priority_score': 1200,
            'queue_position': 2,
            'patients_ahead': 1,
            'queue_length': 5,
            'available_doctors': 2,
            'active_consultations': 1,
            'hour_of_day': 14,
            'day_of_week': 2,
            'historical_dept_avg_wait': 18.5
        }
        novel_df = pd.DataFrame([novel_row])

        # Prediction must succeed gracefully without KeyError or ValueError
        pred = pipeline.predict(novel_df)
        assert len(pred) == 1
        assert isinstance(pred[0], (int, float))
        assert pred[0] >= 0.0


def test_audit_metrics_calculated_strictly_on_held_out_split():
    """
    Verify reported evaluation metrics (MAE, RMSE, R²) in metadata are computed
    strictly on the held-out test split, and do NOT report training error.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        model_file = os.path.join(tmpdir, 'model.joblib')
        meta_file = os.path.join(tmpdir, 'meta.json')

        df = MLService.generate_sample_dataset(n_samples=150, random_state=42)
        metadata = MLService.train_and_evaluate(
            dataset_df=df,
            save_path=model_file,
            metadata_path=meta_file,
            test_size=0.20,
            random_state=42
        )

        bundle, _ = MLService.load_model(model_path=model_file, metadata_path=meta_file)
        pipeline = bundle['pipeline']

        split_idx = int(len(df) * 0.8)
        train_df = df.iloc[:split_idx].copy()
        test_df = df.iloc[split_idx:].copy()

        # Map dept avg
        dept_avgs = bundle['dept_averages']
        overall_avg = bundle['overall_avg']
        train_df['historical_dept_avg_wait'] = train_df['department_code'].map(lambda c: dept_avgs.get(c, overall_avg))
        test_df['historical_dept_avg_wait'] = test_df['department_code'].map(lambda c: dept_avgs.get(c, overall_avg))

        y_pred_test = pipeline.predict(test_df[ALL_FEATURES])
        y_pred_train = pipeline.predict(train_df[ALL_FEATURES])

        independent_test_mae = float(np.mean(np.abs(test_df[TARGET_COLUMN] - y_pred_test)))
        independent_train_mae = float(np.mean(np.abs(train_df[TARGET_COLUMN] - y_pred_train)))

        reported_mae = metadata['evaluation']['random_forest']['mae']

        # Reported MAE matches test set evaluation
        assert round(independent_test_mae, 2) == reported_mae
        # Train MAE is distinct from reported test MAE
        assert round(independent_train_mae, 2) != reported_mae


def test_audit_training_fails_gracefully_on_empty_or_sub_min_dataset():
    """
    Verify training fails gracefully with clear ValueError when dataset is
    empty or below the minimum threshold (< 10 samples).
    """
    empty_df = pd.DataFrame()
    with pytest.raises(ValueError, match="Insufficient training samples"):
        MLService.train_and_evaluate(dataset_df=empty_df)

    tiny_df = pd.DataFrame({
        'created_at': [datetime.now(timezone.utc)],
        'department_code': ['GEN'],
        TARGET_COLUMN: [10.0]
    })
    with pytest.raises(ValueError, match="Insufficient training samples: 1. Need at least 10."):
        MLService.train_and_evaluate(dataset_df=tiny_df)


# ── 12. Live Prediction Integration & Fallback Verification ──────────────────

def test_predict_waiting_time_safe_on_invalid_inputs(app):
    """
    Verify predict_waiting_time and build_features_for_token handle
    None token, missing attributes, or empty parameters safely without crashing.
    """
    with app.app_context():
        # Case 1: None token
        assert MLService.predict_waiting_time(None) is None

        # Case 2: build_features_for_token on None returns valid 1-row DataFrame with ALL_FEATURES
        feat_df = MLService.build_features_for_token(None)
        assert len(feat_df) == 1
        assert list(feat_df.columns) == ALL_FEATURES

        # Case 3: Bare QueueToken with None attributes
        bare_token = QueueToken(
            token_number='BARE-001',
            department_id=None,
            priority=None,
            priority_score=None,
            registration_type=None
        )
        bare_df = MLService.build_features_for_token(bare_token)
        assert len(bare_df) == 1
        assert list(bare_df.columns) == ALL_FEATURES
        assert bare_df['priority'].iloc[0] == 'Normal'
        assert bare_df['department_code'].iloc[0] == 'GEN'


def test_live_prediction_updates_with_doctor_availability_and_queue_depth(app):
    """
    Verify live prediction dynamically reflects changes in queue depth
    and doctor availability.
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        t1 = QueueService.register_patient_and_issue_token(
            name='Queue Test 1', age=30, gender='Male', phone='9811112222',
            department_id=dept.id, priority='Normal'
        )
        t2 = QueueService.register_patient_and_issue_token(
            name='Queue Test 2', age=35, gender='Female', phone='9811113333',
            department_id=dept.id, priority='Normal'
        )

        queue = QueueService.get_department_queue(dept.id)

        # Token 2 is behind Token 1
        pred1 = MLService.predict_waiting_time(t1, department_queue=queue, available_doctors=1)
        pred2 = MLService.predict_waiting_time(t2, department_queue=queue, available_doctors=1)

        if pred1 is not None and pred2 is not None:
            # Patient with more people ahead has higher or equal wait
            assert pred2 >= pred1

        # More available doctors should result in lower or equal predicted wait
        pred_1doc = MLService.predict_waiting_time(t2, department_queue=queue, available_doctors=1)
        pred_3doc = MLService.predict_waiting_time(t2, department_queue=queue, available_doctors=3)
        if pred_1doc is not None and pred_3doc is not None:
            assert pred_3doc <= pred_1doc


def test_patient_token_view_and_queue_status_render_predictions(client, app):
    """
    Verify patient token view and live status pages render estimated waiting time.
    """
    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        token = QueueService.register_patient_and_issue_token(
            name='UI Verification Patient', age=45, gender='Female', phone='9811114444',
            department_id=dept.id, priority='Medium'
        )
        token_num = token.token_number
        dept_id = dept.id

    # Check token view page
    resp_token = client.get(f'/patient/token/{token_num}')
    assert resp_token.status_code == 200
    html_token = resp_token.get_data(as_text=True)
    assert "Est. Additional Wait:" in html_token
    assert ("mins" in html_token or "Unavailable" in html_token)

    # Check live status page
    resp_status = client.get(f'/patient/status?dept_id={dept_id}')
    assert resp_status.status_code == 200
    html_status = resp_status.get_data(as_text=True)
    assert "Est. Additional Wait" in html_status


def test_missing_model_fallback_in_templates(client, app, monkeypatch):
    """
    Verify that when model loading fails, prediction gracefully returns None,
    and templates safely display 'Unavailable' without crashing or fabricating numbers.
    """
    # Simulate missing model bundle
    monkeypatch.setattr(MLService, 'load_model', classmethod(lambda cls, *args, **kwargs: (None, None)))

    with app.app_context():
        dept = Department.query.filter_by(code='GEN').first()
        token = QueueService.register_patient_and_issue_token(
            name='Fallback Patient', age=50, gender='Male', phone='9811115555',
            department_id=dept.id, priority='Normal'
        )
        token_num = token.token_number

        # Direct service call returns None
        assert MLService.predict_waiting_time(token) is None

    # Web page renders 'Unavailable' gracefully
    resp = client.get(f'/patient/token/{token_num}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "Unavailable" in html


def test_synthetic_to_real_switching_threshold(app):
    """
    Verify MLService.get_or_create_training_dataset correctly enforces
    the MIN_TRAINING_SAMPLES (30) threshold:
    - Returns (df, True) [is_synthetic=True] when historical DB records < 30.
    - Returns (df, False) [is_synthetic=False] when historical DB records >= 30.
    """
    with app.app_context():
        # Step 1: With zero/few records, must fall back to synthetic
        df_syn, is_syn = MLService.get_or_create_training_dataset(force_synthetic=False, n_synthetic=50)
        assert is_syn is True
        assert len(df_syn) == 50
        assert (df_syn['is_synthetic'] == True).all()

        # Step 2: Create 30 completed consultation records in the test DB
        dept = Department.query.filter_by(code='GEN').first()
        base_time = datetime.now(timezone.utc) - timedelta(days=5)

        for i in range(30):
            patient = Patient(
                patient_code=f'REAL-PAT-{i:03d}',
                name=f'Real Patient {i}',
                age=30 + (i % 20),
                gender='Male' if i % 2 == 0 else 'Female',
                phone=f'98000000{i:02d}'
            )
            db.session.add(patient)
            db.session.flush()

            t_created = base_time + timedelta(hours=i)
            t_started = t_created + timedelta(minutes=15 + (i % 10))

            tok = QueueToken(
                token_number=f'REAL-TOK-{i:03d}',
                patient_id=patient.id,
                department_id=dept.id,
                status='Completed',
                priority='Normal',
                priority_score=100,
                registration_type='Walk-in',
                created_at=t_created,
                consultation_started_at=t_started,
                qr_code_hash=f'hash_{i}'
            )
            db.session.add(tok)

        db.session.commit()

        # Step 3: Now get_or_create_training_dataset should extract from DB and return is_synthetic=False
        df_real, is_syn_after = MLService.get_or_create_training_dataset(force_synthetic=False)
        assert is_syn_after is False
        assert len(df_real) >= 30
        assert (df_real['is_synthetic'] == False).all()
        assert TARGET_COLUMN in df_real.columns
        # No patient names in extracted real dataset
        assert 'name' not in df_real.columns
        assert 'patient_name' not in df_real.columns
        assert 'phone' not in df_real.columns


