"""Mark only historical v1 experimental-pairing expectations as retired.
The original tests are retained for traceability; v2 replacements run separately.
"""
import pytest
RETIRED={
 'test_device_pairing_license_and_revocation','test_device_revoked_license_loses_access',
 'test_pairing_rejects_wrong_claim_and_user_without_license','test_device_limit_and_owner_revoke',
 'test_expired_pairing_code_rejected','test_pending_pairing_cannot_claim_after_device_or_license_revoked',
 'test_plan_snapshot_duration_platform_device_limit_and_disable',
 'test_pg_parallel_pairings_respect_device_limit','test_pg_device_license_revoke_stops_access',
}
def pytest_collection_modifyitems(items):
    for item in items:
        if item.originalname in RETIRED:
            item.add_marker(pytest.mark.xfail(strict=True,reason='v0.8 intentionally retires unsafe experimental v1 pairing; see v2 tests'))
