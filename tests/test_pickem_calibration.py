from pathlib import Path

import pandas as pd

from src.pickem.calibration import MovementCalibrator, handwritten_adjustment, movement_adjustment


def test_handwritten_buckets_and_gaps() -> None:
    assert handwritten_adjustment(2.51) == 0.03
    assert handwritten_adjustment(2.5) == 0.015
    assert handwritten_adjustment(1.0) == 0.015
    assert handwritten_adjustment(0.75) == 0.0
    assert handwritten_adjustment(0.5) == 0.0
    assert handwritten_adjustment(0.0) == 0.0
    assert handwritten_adjustment(-0.5) == 0.0
    assert handwritten_adjustment(-0.75) == 0.0
    assert handwritten_adjustment(-1.0) == -0.015
    assert handwritten_adjustment(-2.5) == -0.015
    assert handwritten_adjustment(-2.51) == -0.03
    assert abs(handwritten_adjustment(10.0)) <= 0.03


def test_none_source_is_always_zero() -> None:
    cal = MovementCalibrator("none")
    assert cal.movement_adjustment(0.7, 3.0) == 0.0
    assert movement_adjustment(0.2, -4.0, calibrator=cal) == 0.0


def test_matrix_csv_production_adjustment(tmp_path: Path) -> None:
    csv_path = tmp_path / "matrix.csv"
    pd.DataFrame(
        [
            {
                "probability_min": 0.50,
                "probability_max": 0.90,
                "movement_min": 1.0,
                "movement_max": 3.0,
                "production_adjustment": 0.02,
            },
            {
                "probability_min": 0.90,
                "probability_max": 1.00,
                "movement_min": 1.0,
                "movement_max": 3.0,
                "production_adjustment": 0.01,
            },
            {
                "probability_min": 0.50,
                "probability_max": 0.90,
                "movement_min": -3.0,
                "movement_max": 1.0,
                "production_adjustment": -0.02,
            },
            {
                "probability_min": 0.90,
                "probability_max": 1.00,
                "movement_min": -3.0,
                "movement_max": 1.0,
                "production_adjustment": 0.0,
            },
        ]
    ).to_csv(csv_path, index=False)
    cal = MovementCalibrator("matrix_csv", matrix_path=csv_path)
    assert cal.movement_adjustment(0.60, 1.5) == 0.02
    assert cal.movement_adjustment(0.90, 1.5) == 0.01
    assert cal.movement_adjustment(0.40, 2.0) == 0.0  # underdog band absent
    assert cal.movement_adjustment(0.60, 0.0) == -0.02


def test_matrix_csv_missing_file_is_zero(tmp_path: Path) -> None:
    cal = MovementCalibrator("matrix_csv", matrix_path=tmp_path / "missing.csv")
    assert cal.movement_adjustment(0.70, 3.0) == 0.0


def test_clamp() -> None:
    cal = MovementCalibrator("none", clamp_min=0.01, clamp_max=0.99)
    assert cal.clamp(0.0) == 0.01
    assert cal.clamp(1.0) == 0.99
    assert cal.clamp(0.5) == 0.5
