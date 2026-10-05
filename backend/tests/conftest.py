# conftest.py — di-load otomatis oleh pytest sebelum test
# Tujuan: mock dotenv agar test bisa berjalan tanpa .env file
import sys
from unittest.mock import MagicMock

# Mock dotenv sebelum app diimpor
sys.modules["dotenv"] = MagicMock()

# Override DATABASE_URL ke in-memory SQLite
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"
