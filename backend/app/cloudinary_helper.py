# -*- coding: utf-8 -*-
"""
cloudinary_helper.py
Helper untuk upload/hapus foto ke Cloudinary (cloud storage gratis).

Konfigurasi ENV yang diperlukan di Railway:
  CLOUDINARY_CLOUD_NAME = <cloud_name_anda>
  CLOUDINARY_API_KEY    = <api_key_anda>
  CLOUDINARY_API_SECRET = <api_secret_anda>

Jika ENV tidak terkonfigurasi, fungsi akan fallback ke penyimpanan lokal
supaya development di localhost tetap berjalan normal.
"""
import os
import io
from typing import Optional
from pathlib import Path

import cloudinary
import cloudinary.uploader


# ─── Konfigurasi ─────────────────────────────────────────────────────────────

def _is_cloudinary_configured() -> bool:
    """Periksa apakah semua ENV Cloudinary sudah terset."""
    return all([
        os.environ.get("CLOUDINARY_CLOUD_NAME"),
        os.environ.get("CLOUDINARY_API_KEY"),
        os.environ.get("CLOUDINARY_API_SECRET"),
    ])


def _configure_cloudinary():
    """Konfigurasi Cloudinary SDK dari ENV."""
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME"),
        api_key=os.environ.get("CLOUDINARY_API_KEY"),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET"),
        secure=True,
    )


# ─── Upload ───────────────────────────────────────────────────────────────────

def upload_to_cloudinary(
    file_bytes: bytes,
    filename: str,
    folder: str = "hr_foto_absensi",
    resource_type: str = "auto",
) -> Optional[str]:
    """
    Upload bytes ke Cloudinary.

    Returns:
        URL publik Cloudinary jika berhasil (https://res.cloudinary.com/...).
        None jika gagal atau ENV belum dikonfigurasi.
    """
    if not _is_cloudinary_configured():
        print("[Cloudinary] ENV belum dikonfigurasi, skip Cloudinary upload.")
        return None

    _configure_cloudinary()

    # Ambil nama file tanpa ekstensi sebagai public_id
    stem = Path(filename).stem
    try:
        result = cloudinary.uploader.upload(
            io.BytesIO(file_bytes),
            public_id=f"{folder}/{stem}",
            resource_type=resource_type,
            overwrite=True,
        )
        url: str = result.get("secure_url", "")
        print(f"[Cloudinary] Upload berhasil: {url}")
        return url if url else None
    except Exception as e:
        print(f"[Cloudinary] Gagal upload: {e}")
        return None


def delete_from_cloudinary(public_id: str) -> bool:
    """
    Hapus aset dari Cloudinary berdasarkan public_id.

    Returns:
        True jika berhasil dihapus, False jika gagal.
    """
    if not _is_cloudinary_configured():
        return False

    _configure_cloudinary()

    try:
        result = cloudinary.uploader.destroy(public_id)
        return result.get("result") == "ok"
    except Exception as e:
        print(f"[Cloudinary] Gagal hapus {public_id}: {e}")
        return False
