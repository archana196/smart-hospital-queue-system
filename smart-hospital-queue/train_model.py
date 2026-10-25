"""
train_model.py – Reproducible training script for outpatient waiting-time prediction.

Usage:
    python train_model.py
"""

import os
import sys
from app import create_app
from app.services.ml_service import MLService, DEFAULT_MODEL_PATH, DEFAULT_METADATA_PATH

def main():
    print("=" * 70)
    print(" Smart Hospital Queue - ML Waiting-Time Prediction Training")
    print("=" * 70)

    app = create_app('development')
    with app.app_context():
        print("[1/4] Preparing dataset (checking DB historical records / synthetic generator)...")
        dataset_df, is_synthetic = MLService.get_or_create_training_dataset(n_synthetic=600)
        
        sample_type = "[SAMPLE DATA] Synthetic Development Set" if is_synthetic else "Real Historical DB Records"
        print(f"      Total records: {len(dataset_df)} ({sample_type})")
        print(f"      Date range: {dataset_df['created_at'].min()} to {dataset_df['created_at'].max()}")

        print("[2/4] Exporting dataset snapshot for auditability...")
        csv_path = os.path.join(os.path.dirname(DEFAULT_MODEL_PATH), 'training_dataset_export.csv')
        MLService.export_dataset_csv(csv_path, dataset_df)
        print(f"      Saved: {csv_path} (No PII)")

        print("[3/4] Training Random Forest Regressor & evaluating against Baseline...")
        metadata = MLService.train_and_evaluate(
            dataset_df=dataset_df,
            save_path=DEFAULT_MODEL_PATH,
            metadata_path=DEFAULT_METADATA_PATH,
            test_size=0.20,
            random_state=42
        )

        eval_data = metadata['evaluation']
        print("\n" + "=" * 70)
        print(" EVALUATION RESULTS (Temporal Test Split: 20%)")
        print("=" * 70)
        print(f" Training Samples: {metadata['train_samples']} | Testing Samples: {metadata['test_samples']}")
        print(f" Features Used:    {len(metadata['features'])} features")
        print("-" * 70)
        print(" 1. Baseline Model (Training Median):")
        print(f"    - MAE:  {eval_data['baseline_median']['mae']:.2f} minutes")
        print(f"    - RMSE: {eval_data['baseline_median']['rmse']:.2f} minutes")
        print("-" * 70)
        print(" 2. Random Forest Regressor (n_estimators=100, max_depth=8):")
        print(f"    - MAE:  {eval_data['random_forest']['mae']:.2f} minutes")
        print(f"    - RMSE: {eval_data['random_forest']['rmse']:.2f} minutes")
        print(f"    - R²:   {eval_data['random_forest']['r2']:.4f}")
        print("=" * 70)
        print(f" Artifact saved: {DEFAULT_MODEL_PATH}")
        print(f" Metadata saved: {DEFAULT_METADATA_PATH}")

        if is_synthetic:
            print("\n[!] DATASET LIMITATION NOTICE:")
            print("    The model was trained on synthetic development data [SAMPLE DATA]")
            print("    because real historical consultation records were insufficient (< 30).")
            print("    Do NOT claim validated real-world clinical accuracy until production data is accumulated.")
        print("=" * 70)

if __name__ == '__main__':
    main()
