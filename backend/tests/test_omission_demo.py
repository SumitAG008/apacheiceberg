"""Tests for 60-Second Telemetry Omission & Dispute Demonstration Module."""

from etp.omission_demo import generate_synthetic_daily_telemetry, run_60s_omission_demo


def test_synthetic_telemetry_generation():
    submitted, total = generate_synthetic_daily_telemetry(
        mpan="MPAN-TEST-001",
        day_iso="2026-09-22",
        start_nonce=500,
        drop_indices=[10, 11, 12]
    )

    assert len(total) == 48
    assert len(submitted) == 45
    assert submitted[0]["etp_nonce"] == 500
    assert submitted[-1]["etp_nonce"] == 547


def test_60s_omission_demo_execution():
    report = run_60s_omission_demo(tsa_url=None, mpan="MPAN-DEMO-TEST", day="2026-09-22")

    assert report["meter_id"] == "MPAN-DEMO-TEST"
    assert report["expected_readings"] == 48
    assert report["received_readings"] == 42
    assert report["omitted_readings_count"] == 6
    assert report["checkpoint_status"] == "ANCHORED_WITH_GAPS"
    assert report["dispute_verdict"] == "OMISSION_DETECTED_AND_PROVEN"
    assert len(report["merkle_root"]) == 64
    assert len(report["authenticated_anchor_digest"]) == 64
    assert report["tsa_anchor_ref"].startswith("urn:meldra:")
