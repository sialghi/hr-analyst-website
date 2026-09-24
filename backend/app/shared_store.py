# -*- coding: utf-8 -*-
"""
shared_store.py
===============
In-memory store bersama yang bisa diimport oleh beberapa router tanpa
menyebabkan circular import.

Structure _file_store:
    {
        "<file_id>": {
            "path":        "/tmp/hr_pipeline_xxx/Report_Hasil_abc12345.xlsx",
            "filename":    "Report Hasil_Absensi.xlsx",
            "result_data": { ... }  # JSON lengkap dari jalankan_pipeline_db_json
        }
    }
"""

from typing import Any

# Keyed by file_id (hex string)
_file_store: dict[str, dict[str, Any]] = {}
