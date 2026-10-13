# Rencana Refactor Backend dan Frontend

## Tujuan

Meningkatkan keterbacaan, kemudahan pemeliharaan, efisiensi proses backend, penggunaan memori, serta ukuran dan runtime bundle frontend tanpa merusak fitur. Refactor dilakukan bertahap, didahului baseline yang terukur, dan setiap bagian harus mempertahankan perilaku aplikasi.

## Keputusan dan batasan

- Cakupan: backend dan frontend aplikasi.
- Prioritas: readability/maintenance, kecepatan backend/memori, serta ukuran bundle/runtime frontend.
- Tidak mengubah perilaku bisnis, kontrak API, skema atau isi database.
- Tidak menambah dependency.
- Pelaksanaan bertahap dengan tes dan tinjauan tiap tahap, bukan satu rewrite besar.
- Tetap lokal; tidak menyentuh Railway/production atau melakukan deployment.
- File rahasia, database, uploads, hasil build, generated code, dan artefak pengguna dikecualikan dari refactor.

## Kondisi awal

Ukuran ini merupakan indikator untuk membantu menentukan modul yang perlu ditinjau, bukan target untuk memecah setiap file:

- Backend: sekitar 10.441 baris Python pada `backend/app`. Modul terbesar yang terukur:
  - `routers/whatsapp.py`: sekitar 1.703 baris
  - `routers/employees.py`: sekitar 1.641 baris
  - `pipeline/service.py`: sekitar 837 baris
  - `pipeline/excel_writer.py`: sekitar 714 baris
  - `pipeline/data_process.py`: sekitar 651 baris
  - `routers/process.py`: sekitar 588 baris
  - `routers/leaves.py`: sekitar 571 baris
  - `leave_logic.py`: sekitar 553 baris
- Frontend: sekitar 7.468 baris pada `frontend/app`. Halaman terbesar yang terukur:
  - `karyawan/page.tsx`: sekitar 2.238 baris
  - `proses/page.tsx`: sekitar 1.949 baris
  - `cuti-izin/page.tsx`: sekitar 1.533 baris
- Tes backend: sekitar 2.541 baris pada sembilan file test; `test_contracts.py` sekitar 1.204 baris.
- Tes browser Playwright tersedia pada `frontend/tests/e2e/hr.spec.ts`; TypeScript strict mode aktif.
- QA backend menggunakan SQLite in-memory dan browser menggunakan API mock, sesuai dokumentasi QA.
- Baseline latency, penggunaan memori, ukuran bundle, dan cakupan perilaku belum dikumpulkan; ukur sebelum menentukan optimasi.

## Tahapan kerja

### 1. Membuat baseline dan peta perilaku

- Inventarisasi halaman, endpoint, alur chatbot, pipeline absensi, modul bisnis, kontrak API, dan tes yang melindunginya.
- Jalankan tes backend/frontend yang tersedia, build, lint, dan typecheck untuk merekam kondisi awal. Catat kegagalan yang sudah ada agar tidak dianggap sebagai regresi refactor.
- Kumpulkan ukuran build/chunk frontend dan profil waktu/memori menggunakan workload sintetis yang dapat diulang. Jangan menggunakan data HR lokal yang berisi data nyata.
- Tandai perilaku kritis yang belum memiliki coverage; tambahkan characterization/regression tests sebelum merombak modul terkait.

### 2. Merampingkan frontend secara modular

- Tinjau halaman terbesar (`karyawan`, `proses`, `cuti-izin`) dan pecah berdasarkan tanggung jawab yang jelas: komponen tampilan, form/dialog, tabel, hooks/state, serta fungsi transformasi murni.
- Pertahankan batas client/server Next.js dan pola autentikasi. Jangan memindahkan state atau side effect dengan cara yang mengubah timing, validasi, navigasi, atau interaksi pengguna.
- Pertahankan seluruh bentuk request/response API dan fitur yang ada.
- Ukur kembali bundle/runtime setelah perubahan. Hapus kode yang terbukti tidak digunakan hanya jika tidak mengubah perilaku.

### 3. Merampingkan backend dan pipeline

- Pisahkan tanggung jawab router besar ke service/helper domain teruji, mulai dari area karyawan dan WhatsApp.
- Tinjau pemisahan pipeline menjadi tahapan pemuatan, normalisasi, perhitungan, dan ekspor jika batas tanggung jawabnya jelas.
- Pertahankan URL/method/status response, skema, otorisasi, transaksi, aturan bisnis, urutan efek samping, penyimpanan/audit, dan penanganan error.
- Hindari perubahan paralel pada aturan bisnis atau migrasi database. Ekstraksi modul harus didukung tes yang membandingkan hasil sebelum dan sesudah.

### 4. Optimasi berdasarkan bottleneck terukur

- Gunakan baseline untuk mencari query berulang, pekerjaan berulang pada data, serialisasi/ekspor mahal, render berulang, atau kode yang masuk bundle tanpa kebutuhan.
- Buat perubahan kecil; bandingkan output secara eksplisit pada fixture identik, lalu ukur latency/memori/bundle dengan metode dan workload yang sama.
- Abaikan perubahan yang manfaatnya tidak terukur atau menambah kompleksitas. Jangan membuat abstraksi/helper generik tanpa kebutuhan lintas pemakai.

### 5. Verifikasi dan dokumentasi

- Jalankan tes domain/API terkait setelah tiap ekstraksi; jalankan Playwright untuk journey terkait dan regression suite penuh pada checkpoint.
- Sebelum refactor selesai, jalankan backend pytest, frontend lint, TypeScript check, production build, Playwright smoke/regression suite, dan `git diff --check`.
- Dokumentasikan struktur modul hasil refactor, perbandingan baseline yang relevan, tes yang dijalankan, dan keterbatasan yang masih ada.

## Area prioritas untuk ditinjau

- **Backend:** `backend/app/routers/whatsapp.py`, `employees.py`, `process.py`, `leaves.py`, `backend/app/pipeline/service.py`, `data_process.py`, `excel_writer.py`, dan `leave_logic.py`.
- **Frontend:** `frontend/app/(app)/karyawan/page.tsx`, `proses/page.tsx`, `cuti-izin/page.tsx`, `frontend/lib/api.ts`, serta komponen UI bersama.
- **QA:** `backend/tests/`, `frontend/tests/e2e/hr.spec.ts`, konfigurasi Playwright, `frontend/package.json`, dan `docs/QA-TESTING.md`.

## Kriteria selesai

- Semua alur yang tercakup sebelum refactor tetap terverifikasi; tidak ada perubahan kontrak API, aturan bisnis, skema/data, atau UX yang tidak disengaja.
- Backend tests, frontend lint/typecheck/build, browser smoke/regression tests, dan `git diff --check` lulus. Kegagalan baseline yang sudah ada didokumentasikan terpisah.
- Hasil optimasi memiliki perbandingan yang terukur dan dapat diulang. Pemecahan modul memperjelas tanggung jawab tanpa menambah kompleksitas yang tidak perlu.
- Tidak ada dependency baru, deployment, atau perubahan data/layanan produksi.
