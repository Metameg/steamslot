from scripts.refresh_catalog_fixture import CURATED_APP_IDS


def test_curated_app_ids_are_unique():
    assert len(CURATED_APP_IDS) == len(set(CURATED_APP_IDS))


def test_curated_app_ids_span_expected_count():
    assert len(CURATED_APP_IDS) >= 20
