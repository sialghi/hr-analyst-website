# ERD Database HR Analyst

Diagram berikut mengikuti tabel SQLAlchemy pada `backend/app/models.py` dan hanya menggambar relasi yang memiliki foreign key database. Kolom teks yang kebetulan menyimpan nama atau kode bisnis tidak dianggap relasi FK.

```mermaid
erDiagram
    PROFILES {
        int id PK
        string code UK
        string nama
        json cabang
        json hari_kerja
        json jam_masuk
        json jam_keluar
        json patokan_lembur
        json lembur_khusus
    }
    BUSINESS_RULE {
        int id PK
        string profil_default
        string jam_masuk_standar
        string jam_keluar_standar
        int dedup_threshold_menit
        int uang_makan_default
        int bonus_lembur_per_jam
    }
    USERS {
        int id PK
        string nama
        string email UK
        string hashed_password
        string role
    }
    EMPLOYEES {
        int id PK
        string employee_code UK
        string nik UK
        string nama
        string profile_code FK
        string cabang
        string employment_status
        date join_date
        boolean active
    }
    EMPLOYEE_IMPORT_CANDIDATES {
        int id PK
        string employee_code UK
        string nama
        int approved_employee_id FK
        string status
    }
    EMPLOYMENT_CONTRACTS {
        int id PK
        int employee_id FK
        int contract_number
        date start_date
        date end_date
        string status
    }
    EMPLOYEE_EMPLOYMENT_TRANSITIONS {
        int id PK
        int employee_id FK
        int employment_contract_id FK
        date phl_start_date
        date phl_end_date
        date transition_date
        datetime created_at
    }
    WHATSAPP_IDENTITIES {
        int id PK
        string phone_number UK
        int employee_id FK
        string status
        int failed_attempts
    }
    WHATSAPP_AUDIT_LOGS {
        int id PK
        string phone_number
        int employee_id FK
        string event_type
        datetime created_at
    }
    WHATSAPP_PROCESSED_MESSAGES {
        int id PK
        string message_id UK
        datetime processed_at
    }
    HOLIDAYS {
        int id PK
        date tanggal UK
        string keterangan
    }
    LEAVE_REQUESTS {
        int id PK
        string import_key UK
        string nama
        string kategori
        date tanggal_mulai
        date tanggal_selesai
        string status
    }
    EMPLOYEE_ADJUSTMENTS {
        int id PK
        string nama UK
        float bonus_lain
        float potongan_lain
    }
    ABSEN_MANUAL {
        int id PK
        string nama
        int tahun
        int bulan
        int jumlah
    }
    ATTENDANCE_UPLOAD_BATCHES {
        int id PK
        string filename
        date period_start
        date period_end
        string file_hash
        string status
    }
    ATTENDANCE_DAILY {
        int id PK
        int employee_id FK
        date attendance_date
        int upload_batch_id FK
        string status
    }
    ATTENDANCE_REVIEWS {
        int id PK
        int employee_id FK
        date attendance_date
        int leave_request_id FK
        int upload_batch_id FK
        string status
        string decision
    }
    ATTENDANCE_RECAP_RECORDS {
        int id PK
        string source_key UK
        string source_file_hash
        int employee_id FK
        string employee_code
        string source_nik
        date attendance_date
        string reconciliation_status
    }
    LEAVE_BALANCE_LEDGER {
        int id PK
        int employee_id FK
        int leave_request_id FK
        int year
        string entry_type
        float amount
    }
    DATABASE_MIGRATION_ARCHIVE {
        int id PK
        string archive_key UK
        string source_table
        string source_primary_key
        json legacy_columns
    }

    PROFILES ||--o{ EMPLOYEES : "profile_code"
    EMPLOYEES ||--o{ EMPLOYMENT_CONTRACTS : "employee_id"
    EMPLOYEES ||--o{ EMPLOYEE_EMPLOYMENT_TRANSITIONS : "employee_id"
    EMPLOYMENT_CONTRACTS ||--o| EMPLOYEE_EMPLOYMENT_TRANSITIONS : "employment_contract_id unique"
    EMPLOYEES ||--o{ WHATSAPP_IDENTITIES : "employee_id"
    EMPLOYEES o|--o{ WHATSAPP_AUDIT_LOGS : "employee_id nullable"
    EMPLOYEES o|--o{ EMPLOYEE_IMPORT_CANDIDATES : "approved_employee_id nullable"
    EMPLOYEES ||--o{ ATTENDANCE_DAILY : "employee_id"
    ATTENDANCE_UPLOAD_BATCHES o|--o{ ATTENDANCE_DAILY : "upload_batch_id nullable"
    EMPLOYEES ||--o{ ATTENDANCE_REVIEWS : "employee_id"
    LEAVE_REQUESTS o|--o{ ATTENDANCE_REVIEWS : "leave_request_id nullable"
    ATTENDANCE_UPLOAD_BATCHES o|--o{ ATTENDANCE_REVIEWS : "upload_batch_id nullable"
    EMPLOYEES o|--o{ ATTENDANCE_RECAP_RECORDS : "employee_id nullable"
    EMPLOYEES ||--o{ LEAVE_BALANCE_LEDGER : "employee_id"
    LEAVE_REQUESTS o|--o{ LEAVE_BALANCE_LEDGER : "leave_request_id nullable"
```

## Batasan interpretasi

- `LEAVE_REQUESTS.nama`, `EMPLOYEE_ADJUSTMENTS.nama`, dan `ABSEN_MANUAL.nama` bukan foreign key ke `EMPLOYEES`; pencocokan berbasis nama pada sebagian jalur tidak menjamin integritas referensial.
- `EMPLOYEE_IMPORT_CANDIDATES.approved_employee_id`, relasi leave pada review/ledger, relasi upload batch, dan relasi karyawan pada rekap/WhatsApp audit dapat bernilai `NULL` sesuai model.
- `EMPLOYEE_EMPLOYMENT_TRANSITIONS` merekam periode PHL hanya pada proses transisi PHL → PKWT yang baru disimpan; tidak ada data transisi lama yang di-backfill otomatis.
- `EMPLOYEE_CODE` pada rekap kehadiran merupakan nilai sumber untuk rekonsiliasi, bukan FK ke `EMPLOYEES.employee_code`.
- Tabel konfigurasi global, akun, pesan webhook yang sudah diproses, hari libur, penyesuaian, absen manual, dan arsip migrasi tidak memiliki FK langsung lain pada model.
- Field ringkas yang ditampilkan bukan daftar lengkap kolom fisik. Gunakan model SQLAlchemy dan skema database pada environment sasaran sebagai referensi lengkap.
