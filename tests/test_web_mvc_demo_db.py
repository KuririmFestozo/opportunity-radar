"""The MVC demo DB must include coordinates and opportunity intents."""
import importlib.util
from pathlib import Path
import sqlite3
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "web-mvc" / "tools" / "create_demo_db.py"
spec = importlib.util.spec_from_file_location("mvc_demo", SCRIPT)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_demo_fixture_supports_location_and_intents(tmp_path):
    output = tmp_path / "example.db"
    demo.create_demo(output)
    with sqlite3.connect(output) as conn:
        assert conn.execute("SELECT count(*) FROM opportunities").fetchone()[0] == 6
        assert conn.execute(
            "SELECT count(*) FROM opportunities WHERE latitude IS NOT NULL AND longitude IS NOT NULL"
        ).fetchone()[0] == 6
        assert conn.execute("SELECT count(*) FROM opportunity_intents").fetchone()[0] == 6
    with pytest.raises(FileExistsError):
        demo.create_demo(output)
