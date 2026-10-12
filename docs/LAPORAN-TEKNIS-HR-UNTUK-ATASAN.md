# Laporan Teknis HR Analyst

**Status:** pembaruan lokal siap untuk ditinjau. Perubahan tidak dideploy dan tidak mengakses/mengubah Railway atau database production.

## Ringkasan eksekutif

Pembaruan menyelaraskan alur master karyawan dengan penggunaan Kode Karyawan, memperjelas input cabang, menerapkan pembatasan pengajuan dan review absensi PHL pada server, serta menyederhanakan rekap saldo menjadi tahun berjalan. Template impor diperbarui agar tidak mengandung gaji maupun tanggal akhir kontrak; proses kontrak PKWT tetap melalui aplikasi. Histori yang sudah tercatat tidak direklasifikasi.

## Perubahan fungsional

- **Master karyawan:** template baru memisahkan kode profil dari status kepegawaian; impor pembaruan mencocokkan berdasarkan Kode Karyawan. Template lama yang memakai tata letak berbeda ditolak agar tidak salah memetakan kolom.
- **Kontrak:** impor PKWT tanpa kontrak aktif mempertahankan validasi dan menahan status aktif; HR melengkapi kontrak melalui form karyawan.
- **Cabang:** input edit berupa dropdown yang menggabungkan cabang profil dan nilai cabang karyawan tersimpan, termasuk nilai lama di luar katalog profil.
- **PHL:** cuti/izin baru diblokir dari endpoint dan chatbot; `WORK_FROM_LOCATION` tetap tersedia. Review absensi PHL hanya menerima `UNPAID_LEAVE`, termasuk bila request dikirim langsung ke API.
- **Rekap saldo:** UI memakai tahun berjalan otomatis dan tetap menampilkan tahun yang dipakai; endpoint masih mendukung parameter tahun.
- **Dokumentasi:** tersedia aturan global, aturan profil, Mermaid ERD berdasarkan FK model, dan laporan teknis ini.
- **QA:** backend menggunakan pytest dan SQLite in-memory; browser menggunakan Playwright dengan API sintetis. Workflow CI menjalankan pemeriksaan tanpa kredensial production.

## Komponen utama

Backend: `backend/app/employee_imports.py`, `backend/app/routers/employees.py`, `leaves.py`, `whatsapp.py`, dan `process.py`.

Frontend: halaman Karyawan, Cuti & Izin, dan Proses Absensi. Regression browser berada di `frontend/tests/e2e/hr.spec.ts`; konfigurasi test server terpisah memakai port dan direktori output Next.js sendiri.

Dokumentasi database dan proses terdapat pada `docs/ERD-DATABASE.md`, `docs/ATURAN-BISNIS-GLOBAL.md`, `docs/ATURAN-BISNIS-PROFIL.md`, dan `docs/QA-TESTING.md`.

## Verifikasi lokal

| Pemeriksaan | Hasil |
| --- | --- |
| Backend `pytest -q` | 75 tes lulus |
| Frontend `npx tsc --noEmit` | Lulus |
| Frontend `npm run build` | Lulus |
| Playwright `npm run test:e2e` | 7 tes lulus |
| `npm run lint:qa` | Lulus |
| Repo-wide `npm run lint` | Belum bersih; masih mengembalikan temuan ESLint pada halaman aplikasi, termasuk `no-explicit-any` dan aturan React Hooks. Perlu pekerjaan cleanup terpisah dan bukan bukti bahwa seluruh repo lolos lint. |

Tes hanya memakai data sintetis dan tidak mengirim pesan WhatsApp sungguhan. Peringatan deprecation pada backend test berasal dari versi FastAPI/Starlette/Pydantic yang terpasang; tidak menyebabkan kegagalan tes.

## Risiko dan tindak lanjut

1. **PKWT:** pastikan setiap kontrak memiliki tanggal dan status aktif yang benar sebelum karyawan diaktifkan.
2. **Override karyawan:** model memiliki kolom override, tetapi pemuatan runtime yang ditinjau secara eksplisit memuat profil dan aturan global; efektifnya semua override pada perhitungan absensi perlu dikonfirmasi lewat test terpisah.
3. **Relasi berbasis nama:** beberapa tabel historis belum memiliki FK ke master karyawan. Rekonsiliasi atau perubahan nama dapat memerlukan pemeriksaan khusus; ERD menandai batas ini.
4. **Lint:** jadwalkan perbaikan lint/type hygiene secara terpisah, karena lint repository penuh masih gagal pada sejumlah pola lama.
5. **Rilis:** lakukan review bisnis HR, validasi dengan workbook sintetis yang bentuknya sama dengan sumber resmi, lalu rencanakan deployment terpisah. Tidak ada migrasi DB atau cutover dalam pekerjaan ini.

## Keputusan yang tidak diubah

- Tidak mengubah algoritma profil/pipeline absensi atau skema database.
- Tidak menghapus data, histori cuti/PHL, maupun riwayat kontrak.
- Tidak mengubah kuota tahunan maupun aturan legal payroll/kompensasi.
- Tidak men-deploy, mengakses Railway, atau menggunakan data personal pada tes.

## Tambahan: tab informasi karyawan dan histori transisi PHL → PKWT

Halaman Karyawan kini memisahkan data master dan Linking WhatsApp menjadi tab halaman terpisah. Untuk transisi PHL → PKWT yang baru, Edit Karyawan > Kepegawaian mencatat periode PHL di tabel `employee_employment_transitions`, lalu membuat kontrak PKWT aktif dengan nomor berikutnya. Periode PHL tidak dicampur dengan baris kontrak. Tanggal masuk utama dipertahankan; tanggal mulai periode PHL diprefill darinya dan dapat dikoreksi hanya pada histori. Akhir PHL ditetapkan satu hari sebelum tanggal mulai kontrak. Histori transisi lama tidak diisi otomatis.

Penambahan tabel ini bekerja pada skema SQLite lokal melalui mekanisme `create_all()` yang ada. Tidak ada migrasi PostgreSQL atau deployment pada perubahan ini; perubahan skema untuk PostgreSQL harus direncanakan dan diuji terpisah sebelum rilis.
