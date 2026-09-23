# HR Analyst & Absensi Automation System
### PT. Javareef Indonesia Perkasa

[![FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688?style=flat-square&logo=fastapi)](https://fastapi.tiangolo.com)
[![Next.js](https://img.shields.io/badge/Frontend-Next.js%2016-black?style=flat-square&logo=next.js)](https://nextjs.org)
[![TypeScript](https://img.shields.io/badge/Language-TypeScript-blue?style=flat-square&logo=typescript)](https://www.typescriptlang.org/)
[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python)](https://python.org)
[![TailwindCSS](https://img.shields.io/badge/Styling-TailwindCSS-38B2AC?style=flat-square&logo=tailwind-css)](https://tailwindcss.com/)
[![License](https://img.shields.io/badge/License-Proprietary-slate?style=flat-square)]()

Sistem otomasi analisis absensi cerdas dan manajemen aturan bisnis SDM (Sumber Daya Manusia) berbasis web. Aplikasi ini mengolah log mentah mesin absensi (fingerprint/face scan) dari berbagai cabang menjadi laporan analitik komprehensif 14 sheet Excel, dashboard interaktif, serta kalkulasi otomatis uang makan, lembur, keterlambatan, dan rekap alpa secara real-time.

---

## 📑 Daftar Isi

- [Fitur Utama](#-fitur-utama)
- [Arsitektur Sistem](#-arsitektur-sistem)
- [Struktur Direktori](#-struktur-direktori)
- [Spesifikasi Format File Absensi (8 Kolom)](#-spesifikasi-format-file-absensi-8-kolom)
- [14 Sheet Laporan Otomatis](#-14-sheet-laporan-otomatis)
- [Panduan Instalasi Lokal](#-panduan-instalasi-lokal)
  - [Prasyarat](#prasyarat)
  - [1. Konfigurasi Backend](#1-konfigurasi-backend)
  - [2. Konfigurasi Frontend](#2-konfigurasi-frontend)
- [Deployment ke Production](#-deployment-ke-production)
  - [1. Database (PostgreSQL Railway / Supabase)](#1-database-postgresql-railway--supabase)
  - [2. Backend (Railway)](#2-backend-railway)
  - [3. Frontend (Vercel)](#3-frontend-vercel)
- [Integrasi Otomasi Workflow (n8n / Webhook)](#-integrasi-otomasi-workflow-n8n--webhook)
- [Peran Pengguna & Keamanan (RBAC)](#-peran-pengguna--keamanan-rbac)

---

## 🚀 Fitur Utama

- ⚙️ **Panel Aturan Bisnis Dinamis (No Hardcoded Config)**:
  Aturan jam kerja masuk/pulang, toleransi keterlambatan, patokan lembur, kuota hari kerja, dan aturan bonus per profil/divisi (Office, Gudang, Javapetco/Toko, Konten, Driver, dll) dapat diubah langsung lewat UI tanpa deploy ulang aplikasi.
- 📊 **Pemrosesan Data Absensi Multi-File & Real-Time**:
  Dukungan unggah beberapa file log mesin absensi sekaligus (`.xlsx`, `.xls`, `.csv`). Hasil langsung tampil di web dashboard interaktif dengan modal drilldown per karyawan dan tombol ekspor Excel.
- 📥 **Template & Contoh Absensi Siap Pakai**:
  Fitur unduh template absensi Excel (`.xlsx` 2 sheet berisi data contoh nyata + panduan kolom) serta contoh `.csv`, dilengkapi tabel preview 8 kolom baku.
- 👥 **Master Karyawan & Sinkronisasi Profil**:
  Katalog karyawan lengkap dengan ID Mesin, cabang kerja, profil kerja, dan override uang makan per individu. Mendukung import massal Excel/CSV.
- 🗓️ **Kalender Tanggal Merah Nasional & Khusus**:
  Pengelolaan tanggal libur nasional dan hari libur perusahaan dengan fitur import Excel untuk perhitungan otomatis lembur dan hak uang makan.
- 🛡️ **Role-Based Access Control (RBAC)**:
  Pemisahan hak akses antara **HR Master** (akses penuh kelola aturan & pengguna) dan **HR Staff** (akses proses absensi dan monitoring laporan).
- 🔗 **Kompatibilitas Otomasi n8n**:
  Menyediakan endpoint REST API terproteksi API Key untuk integrasi otomatisasi penjadwalan via n8n atau webhook internal.

---

## 🏛️ Arsitektur Sistem

```
+-----------------------------------------------------------------------------------+
|                                 CLIENT / PENGGUNA                                 |
+-----------------------------------------------------------------------------------+
           |                                                       |
    (Web Browser UI)                                        (n8n Workflow API)
           v                                                       v
+-----------------------+                               +-----------------------+
|  FRONTEND (Next.js)   |                               |  FastAPI / n8n Route  |
|  - Modern Dashboard   | ---(REST API + JWT Bearer)--->|  Header X-API-Key     |
|  - Interactive Sheets |                               +-----------------------+
+-----------------------+                                           |
                                                                    v
                                                     +------------------------------+
                                                     |    BACKEND (FastAPI App)     |
                                                     |  - Auth & RBAC Guard         |
                                                     |  - Runtime Config Loader     |
                                                     |  - Core Data Pipeline        |
                                                     +------------------------------+
                                                                    |
                                        +---------------------------+---------------------------+
                                        v                                                       v
                         +------------------------------+                        +------------------------------+
                         |      DATABASE STORAGE        |                        |      PIPELINE PROCESSING     |
                         |  - SQLite (Lokal Dev)        |                        |  - Normalisasi Datetime      |
                         |  - PostgreSQL (Production)   |                        |  - Deduplikasi Scan Ganda    |
                         |    (Users, Profiles, Rules,  |                        |  - Koreksi Label Masuk/Keluar|
                         |     Employees, Holidays)     |                        |  - 14 Analytical Sheets      |
                         +------------------------------+                        +------------------------------+
```

---

## 📁 Struktur Direktori

```text
├── backend/                         # Backend Application (FastAPI)
│   ├── app/
│   │   ├── main.py                  # Inisialisasi FastAPI & middleware CORS
│   │   ├── database.py              # Konfigurasi SQLAlchemy & koneksi DB
│   │   ├── models.py                # Skema ORM tabel DB
│   │   ├── schemas.py               # Pydantic schemas untuk validasi I/O
│   │   ├── auth.py                  # Logika otentikasi JWT & hashing password
│   │   ├── routers/
│   │   │   ├── auth.py              # Endpoint autentikasi & kelola user
│   │   │   ├── profiles.py          # CRUD profil divisi/jadwal kerja
│   │   │   ├── rules.py             # Aturan bisnis global (uang makan/potongan)
│   │   │   ├── employees.py         # CRUD & import master karyawan + template
│   │   │   ├── holidays.py          # CRUD & import tanggal merah
│   │   │   └── process.py           # Endpoint proses absensi & download template
│   │   └── pipeline/                # Mesin pemrosesan analitik absensi
│   │       ├── config_runtime.py    # Bridge config database ke modul analitik
│   │       ├── loader.py            # Pembaca format .xlsx, .xls, .csv mesin
│   │       ├── preprocessing.py     # Pembersihan scan ganda & normalisasi jam
│   │       ├── data_process.py      # Kalkulasi telat, lembur, uang makan, alpa
│   │       ├── excel_writer.py      # Generator file Excel 14 sheet terformat
│   │       └── service.py           # Orkestrasi pipeline end-to-end
│   ├── seed.py                      # Seeder otomatis akun Master & 7 profil default
│   ├── requirements.txt             # Dependensi Python
│   ├── Procfile                     # Konfigurasi start runner deployment
│   └── railway.toml                 # Konfigurasi Railway deployment
│
├── frontend/                        # Frontend Application (Next.js 16)
│   ├── app/
│   │   ├── layout.tsx               # Root layout & font loader
│   │   ├── page.tsx                 # Redirect route
│   │   ├── login/                   # Halaman masuk sistem
│   │   └── (app)/                   # Route terotentikasi dengan Sidebar Nav
│   │       ├── dashboard/           # Ringkasan KPI absensi & statistik
│   │       ├── aturan-bisnis/       # Konfigurasi aturan jam kerja per divisi
│   │       ├── aturan-global/       # Konfigurasi nominal uang makan & potongan
│   │       ├── karyawan/            # Katalog master karyawan & import Excel
│   │       ├── tanggal-merah/       # Kalender libur nasional
│   │       ├── proses/              # Upload file log absensi, preview & download
│   │       └── pengguna/            # Manajemen staf & role akun
│   ├── components/
│   │   ├── Sidebar.tsx              # Navigasi utama dengan branding perusahaan
│   │   └── ui.tsx                   # Design system reusable components
│   └── lib/
│       └── api.ts                   # API client service & token storage
```

---

## 🧾 Spesifikasi Format File Absensi (8 Kolom)

Sistem dirancang untuk membaca file ekspor mesin absensi mentah dalam format `.xlsx`, `.xls`, maupun `.csv`. File dapat memiliki baris header ataupun langsung baris data pada baris pertama.

| No | Nama Kolom | Wajib | Contoh Nilai | Keterangan |
|:--:|:---|:---:|:---|:---|
| 1 | `Cabang` | Ya | `BANDUNG`, `BLOK C`, `BLOK A` | Cabang atau unit lokasi absensi |
| 2 | `Nama` | Ya | `Budi Hartono` | Wajib sesuai dengan nama di Master Karyawan |
| 3 | `ID_Mesin` | Opsional | `1` | Nomor unit mesin fingerprint/face scan |
| 4 | `Timestamp_Raw`| Ya | `02/03/2026 07:54:12` | Mendukung `DD/MM/YYYY HH:MM:SS` & format ISO |
| 5 | `Tipe_Asli_Raw`| Ya | `C/Masuk`, `C/Keluar` | Arah scan mesin (sistem otomatis mengoreksi jika label terbalik) |
| 6 | `Kode_Gerbang` | Opsional | `1` | Nomor terminal/gerbang pintu |
| 7 | `Kolom_Kosong` | Opsional | `-` | Kolom bawaan ekspor mesin |
| 8 | `Metode` | Opsional | `Finger`, `Face`, `Password`| Metode verifikasi presensi |

> [!TIP]
> Anda dapat mengunduh template acuan lengkap (`template_absensi_mentah.xlsx`) langsung melalui menu **Proses Data Absensi** di aplikasi web.

---

## 📊 14 Sheet Laporan Otomatis

Setiap kali data absensi diproses, sistem menghasilkan buku kerja Excel (`.xlsx`) profesional dengan 14 sheet analitik lengkap:

1. **Summary Overview**: Ringkasan akumulasi seluruh karyawan (hari kerja valid, frekuensi telat, jam lembur bulat, total bonus lembur, uang makan akhir, dan status catatan).
2. **Rekap Telat**: Detil setiap kejadian datang terlambat, menit selisih, dan patokan jam masuk profil.
3. **Rekap Lembur**: Perhitungan jam lembur (dibulatkan per jam utuh) dan nominal bonus lembur (Rp).
4. **Rekap Pulang Duluan**: Daftar scan keluar sebelum jam kepulangan resmi profil jadwal.
5. **Rekap Tidak Masuk**: Evaluasi mingguan kehadiran vs kuota minimal hari kerja.
6. **Data Tidak Lengkap**: Deteksi hari kerja yang hanya memiliki satu sisi scan (hanya Masuk atau hanya Keluar).
7. **Uang Makan**: Rincian harian uang makan kotor, potongan telat bertahap, bonus tanggal merah, dan total bersih.
8. **Perbandingan Cabang**: Agregasi metrik kedisiplinan dan biaya antar cabang operasional.
9. **Rekap per Profil**: Rekapitulasi kehadiran divisi non-logika-utama (Marketing, Live Streaming, Toko, dll).
10. **Alpa Berulang**: Identifikasi karyawan yang tidak memenuhi kuota kerja $\ge 2$ minggu beruntun.
11. **Perlu Dicek**: Daftar nama pada log mesin yang belum terdaftar di database Master Karyawan.
12. **Preprocessing**: Data absensi harian bersih setelah deduplikasi scan ganda dan koreksi label.
13. **Data Mentah**: Jejak audit seluruh log scan asli dari berkas masukan.
14. **Readme & Catatan Logika**: Dokumentasi aturan kalkulasi, formula, dan parameter yang digunakan.

---

## 🛠️ Panduan Instalasi Lokal

### Prasyarat
- **Python**: $\ge 3.10$
- **Node.js**: $\ge 18.0$ dan **npm**
- **Git**

### 1. Konfigurasi Backend

```bash
# Masuk ke folder backend
cd backend

# Buat virtual environment
python -m venv venv

# Aktifkan virtual environment
# Windows (PowerShell):
.\venv\Scripts\Activate.ps1
# Windows (CMD):
.\venv\Scripts\activate.bat
# Linux/macOS:
source venv/bin/activate

# Install dependensi
pip install -r requirements.txt

# Buat berkas environment
cp .env.example .env
```

Sesuaikan isi file `.env`:
```ini
# Kosongkan DATABASE_URL untuk menggunakan SQLite lokal otomatis
DATABASE_URL=
JWT_SECRET_KEY=kunci-rahasia-jwt-super-aman-ganti-di-production
API_KEY=kunci-api-untuk-n8n
FRONTEND_ORIGIN=http://localhost:3000
SEED_HR_MASTER_EMAIL=admin@perusahaan.com
SEED_HR_MASTER_PASSWORD=ubah-password-ini
```

Inisialisasi database dan akun awal:
```bash
# Buat akun HR Master pertama dan 7 profil kerja bawaan
python seed.py

# Jalankan server backend
uvicorn app.main:app --reload --port 8000
```
Backend berjalan di: `http://localhost:8000` (Dokumentasi API Swagger di `http://localhost:8000/docs`).

### 2. Konfigurasi Frontend

Buka terminal baru:
```bash
# Masuk ke folder frontend
cd frontend

# Install dependensi
npm install

# Buat berkas environment local
cp .env.example .env.local
```

Pastikan isi `.env.local`:
```ini
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Jalankan server development:
```bash
npm run dev
```
Frontend berjalan di: `http://localhost:3000`.

### Kredensial Login Bawaan:
- **Email**: `admin@perusahaan.com`
- **Password**: `ubah-password-ini`  
*(Disarankan segera mengganti kata sandi setelah masuk pertama kali melalui menu Pengguna).*

---

## ☁️ Deployment ke Production

### 1. Database (PostgreSQL Railway / Supabase)
1. Buka [railway.app](https://railway.app), klik **New Project** $\rightarrow$ **Provision PostgreSQL**.
2. Salin URL koneksi database yang diberikan (format `postgresql://...`).
3. Ganti prefiks protokol menjadi `postgresql+psycopg2://` agar sesuai dengan driver SQLAlchemy backend.

### 2. Backend (Railway)
1. Hubungkan repositori GitHub ke Railway.
2. Pilih sub-folder direktori root: `backend`.
3. Tambahkan **Environment Variables** di dashboard Railway:
   - `DATABASE_URL`: URI PostgreSQL di atas.
   - `JWT_SECRET_KEY`: String acak panjang aman.
   - `API_KEY`: Kunci token untuk webhook automasi.
   - `FRONTEND_ORIGIN`: URL domain Vercel frontend Anda (mis. `https://hr-analyst.vercel.app`).
   - `SEED_HR_MASTER_EMAIL`: Email admin utama.
   - `SEED_HR_MASTER_PASSWORD`: Kata sandi admin utama.
4. Railway akan menjalankan aplikasi secara otomatis sesuai `Procfile` / `railway.toml`.
5. Buka tab **Shell** di Railway dan jalankan seeder sekali:
   ```bash
   python seed.py
   ```

### 3. Frontend (Vercel)
1. Buka [vercel.com](https://vercel.com) $\rightarrow$ **Add New Project** $\rightarrow$ pilih repositori ini.
2. Pada **Root Directory**, klik **Edit** dan pilih folder `frontend`.
3. Tambahkan **Environment Variable**:
   - `NEXT_PUBLIC_API_URL`: URL publik backend Railway Anda (mis. `https://backend-production.up.railway.app` tanpa garis miring penutup).
4. Klik **Deploy**.

---

## 🤖 Integrasi Otomasi Workflow (n8n / Webhook)

Aplikasi tetap mempertahankan endpoint integrasi n8n yang dapat dipanggil tanpa login web (menggunakan header API Key):

### 1. Proses Absensi Otomatis
- **Method**: `POST`
- **Endpoint**: `https://{BACKEND_URL}/proses-absensi`
- **Headers**:
  - `X-API-Key`: `<API_KEY>`
- **Body (form-data)**:
  - `files`: Berkas absensi mentah (`.xlsx` / `.csv`)
  - `master_karyawan` *(opsional)*: Jika tidak dikirim, otomatis memakai data tabel Master Karyawan.
  - `file_tanggal_merah_override` *(opsional)*: Jika tidak dikirim, otomatis memakai data tabel Tanggal Merah.
- **Response**: File biner laporan Excel (`application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`).

### 2. Sinkronisasi Tanggal Merah
- **Method**: `POST`
- **Endpoint**: `https://{BACKEND_URL}/upload-tanggal-merah`
- **Headers**:
  - `X-API-Key`: `<API_KEY>`
- **Body (form-data)**:
  - `file_tanggal_merah`: Berkas Excel daftar tanggal libur.

---

## 🔐 Peran Pengguna & Keamanan (RBAC)

Keamanan hak akses diberlakukan secara ketat di sisi backend (API route guards) serta antarmuka visual frontend:

| Hak Akses / Modul | HR Master | HR Staff |
|:---|:---:|:---:|
| Upload & Memproses Data Absensi | ✅ | ✅ |
| Unduh Laporan Excel & CSV Hasil | ✅ | ✅ |
| Unduh Template & Contoh File Absensi | ✅ | ✅ |
| Mengubah Aturan Jam Kerja Divisi (Profiles) | ✅ | ❌ *(Read-only)* |
| Mengubah Nominal Uang Makan & Potongan Global | ✅ | ❌ *(Read-only)* |
| Tambah, Ubah, & Hapus Master Karyawan | ✅ | ❌ *(Read-only)* |
| Tambah & Hapus Tanggal Merah | ✅ | ❌ *(Read-only)* |
| Kelola Akun Staf & Hak Akses Pengguna | ✅ | ❌ |

---

## 📄 Lisensi

Hak Cipta © 2026 **PT. Javareef Indonesia Perkasa**. Seluruh hak cipta dilindungi undang-undang. Sistem ini dikembangkan khusus untuk kepentingan operasional internal perusahaan.
