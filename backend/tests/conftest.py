import os
import sys
from pathlib import Path

# ensure backend importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_civicfix.db")
os.environ.setdefault("SECRET_KEY", "test-secret")
