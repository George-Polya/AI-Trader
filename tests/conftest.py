import os
import pytest

def pytest_collection_modifyitems(config, items):
    if os.getenv("RUN_KIS_SMOKE") == "true":
        return
    skip_kis_smoke = pytest.mark.skip(reason="need RUN_KIS_SMOKE=true env var to run")
    for item in items:
        if "kis_smoke" in item.keywords:
            item.add_marker(skip_kis_smoke)
