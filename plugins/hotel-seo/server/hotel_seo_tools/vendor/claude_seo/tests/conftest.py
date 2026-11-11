"""hotel-seo: tests that check claude-seo's own repository layout (its runtime launcher and the full
script set) don't apply to the vendored subset, so they are skipped here."""
import pytest

NOT_VENDORED = {
    "test_runtime_allows_new_scripts": "claude-seo's runtime.py launcher is not vendored (hotel-seo runs scripts via seo_check)",
    "test_issue_314_fetching_scripts_use_the_shared_decoder": "scans scripts that are not vendored (nlp_analyze, ...)",
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        reason = NOT_VENDORED.get(item.name)
        if reason:
            item.add_marker(pytest.mark.skip(reason=reason))
