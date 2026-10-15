# Operasi ID Karyawan

Dokumen ini menjelaskan format ID karyawan aktif dan migrasi database. Production Railway telah dimigrasikan manual ke satu kolom `employee_code` yang menyimpan ID format baru. Kolom `new_employee_id` bukan bagian dari skema fisik yang diharapkan; API dan UI tetap memakai nama field `new_employee_id` untuk kompatibilitas internal.

## Format ID aktif

ID karyawan aktif disimpan di kolom database `employee_code` dengan format `JIP-CCNNNN`. `CC` menunjukkan cabang dan `NNNN` adalah nomor urut unik global lintas cabang. Karyawan baru mengambil suffix terbesar yang sudah dipakai employee/kandidat atau high-water mark global, lalu menambah satu. Nilai ID roster yang sudah diberikan HR harus digunakan persis, tidak dihitung ulang.

| Cabang | Prefix |
| --- | --- |
| Gudang A | `01` |
| Gudang C | `02` |
| Cab. Bandung | `03` |
| GLC | `04` |
| Tj. Duren | `05` |
| Setup | `06` |
| IDD PIK | `07` |
| Reef Plus | `08` |
| Kebayoran Lama | `09` |

Employee dan kandidat impor memakai `employee_code` sebagai key. Kolom `employee_code` di payroll/rekap juga menyimpan snapshot ID karyawan baru; snapshot lama yang tertimpa saat cutover tidak dapat direkonstruksi dari kolom tersebut.

## Penghapusan dan pemulihan karyawan

Tombol **Arsipkan** pada halaman Karyawan tidak menghapus record atau membebaskan ID. Karyawan dipindahkan ke **Arsip terhapus**; HR Master dapat memulihkannya dari sana dengan ID dan relasi datanya tetap terjaga. Status aktif sebelum diarsipkan dikembalikan saat dipulihkan. Untuk PHK, gunakan edit status **Nonaktif**, bukan arsipkan.

ID yang pernah digunakan tetap tertahan selama record berada di arsip sehingga tidak diberikan kepada karyawan lain. Form tambah karyawan menerima ID manual opsional untuk memasukkan kembali ID yang sudah terhapus permanen sebelum fitur arsip tersedia. Gunakan hanya setelah identitas orang, cabang, dan ID lama diverifikasi; form tidak dapat memulihkan data yang sudah terhapus secara fisik.

## Database lokal

Skema lokal mengikuti production: kolom fisik `employee_code` dipakai pada master, kandidat, payroll, dan rekap. Alembic revision `a61d9f3c4b20` menyelaraskan nama kolom pada database lokal; sebelum deployment Railway dari `a18f2c6d9e41`, chain revisi setelahnya membuat sequence, memvalidasi struktur, membangun sequence global, dan menambahkan kolom pemulihan hapus.

## Status dan urutan migrasi production

Production Railway pada `Postgres-gpOq` telah diubah manual: `new_employee_id` ditambahkan, `employee_code` lama dihapus, lalu kolom baru diganti nama menjadi `employee_code`. Hasil verifikasi menunjukkan kolom fisik `employee_code` di empat tabel, sementara `alembic_version` masih `a18f2c6d9e41`. Migrasi yang belum di-deploy diselaraskan agar dapat melanjutkan dari revisi tersebut tanpa menambahkan kolom kedua atau menghapus `employee_code`.

1. Hentikan perubahan master, impor karyawan, serta pembuatan karyawan baru. Pastikan database target dan revisi skema telah diverifikasi.
2. Verifikasi bahwa `employees.employee_code` sudah berisi seluruh ID roster yang disetujui, kandidat impor mempunyai ID, dan kode/suffix unik. Pastikan backup production terbaru tersedia.
3. Muat roster yang disetujui ke staging table berakses terbatas. Lakukan preview join berdasarkan ID database produksi; jika NIK tersedia, wajib cocok. Daftar baris hilang, ekstra, duplikat, ID bentrok, NIK berbeda, kandidat impor yang belum dipetakan, dan cabang/prefix yang tidak sesuai harus ditangani manual. Kandidat yang disetujui dipetakan ke employee terkait; kandidat pending yang tetap dipertahankan harus mendapat ID unik baru sesuai cabang. Jangan menebak pemetaan atau menghapus baris.
3. Migrasi memastikan indeks unik employee/kandidat tersedia. `e5c1a8d7f302` akan menghentikan upgrade bila suffix canonical duplikat lintas cabang, kecuali kandidat yang sudah disetujui dan merujuk ke employee dengan ID yang sama.
4. Kolom audit payroll/rekap `employee_code` diartikan sebagai snapshot ID baru, sesuai bentuk production. Jangan menjalankan migrasi yang menghapus kolom ini.
5. Push/deploy kode setelah chain migrasi ditinjau dan backup tersedia. Railway menjalankan `alembic upgrade head` otomatis; smoke-test login, pencarian, create/update/import karyawan, payroll, arsip slip, WhatsApp, dan rekap absensi.
6. Revisi `a61d9f3c4b20` merapikan database lokal. Pada Railway, revisi ini hanya memastikan indeks dan mempertahankan nama kolom `employee_code`.

Jangan arahkan script backfill lokal ke production. Karena `alembic_version` production belum mencatat perubahan manual, jangan menulis revision secara manual tanpa prosedur DBA yang menyamakan schema dan riwayat migrasi.

## Dampak dan audit

- Kolom fisik `employee_code` adalah satu-satunya kolom ID bisnis aktif pada master/kandidat dan nama kolom API/UI `new_employee_id` adalah representasi internal.
- Hubungan transaksi tetap mengacu pada primary key numerik `employee_id`; mengganti ID bisnis tidak memindahkan foreign key.
- Snapshot `employee_code` di payroll/rekap memuat ID karyawan yang tersimpan pada waktu cutover.
- Suffix empat digit tidak boleh dipakai oleh cabang lain atau kandidat impor lain; impor Master dan template karyawan menolak suffix duplikat.
- Tidak ada perubahan langsung terhadap production yang dijalankan dari lingkungan pengembangan ini.
