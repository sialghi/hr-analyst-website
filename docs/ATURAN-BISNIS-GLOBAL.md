# Aturan Bisnis Global HR Analyst

Dokumen ini merangkum perilaku sistem yang terlihat pada implementasi backend dan UI saat ini. Ketentuan operasional yang baru disepakati ditandai sebagai kebijakan aplikasi; dokumen ini bukan pengganti kebijakan HR atau nasihat hukum.

## Pengguna dan kewenangan

- Pengguna yang terautentikasi memiliki salah satu role `hr_master` atau `hr_staff`.
- Kedua role dapat mengakses operasi HR yang memang dibuka untuk HR. Perubahan profil/aturan global, pengelolaan pengguna, dan operasi tertentu dibatasi untuk `hr_master` oleh dependency otorisasi endpoint.
- Token login berlaku 12 jam. Hak akses tetap diperiksa di backend; menyembunyikan tombol di UI bukan pengganti otorisasi server.

## Master karyawan dan kontrak

- Status kepegawaian yang dikenali: `PKWTT`, `PKWT`, dan `PHL`. Status aktif/nonaktif adalah atribut terpisah.
- `employee_code` adalah kode bisnis yang digunakan untuk pencocokan pada proses impor master terbaru. NIK harus 16 digit jika disediakan dan tidak boleh dipakai oleh lebih dari satu karyawan.
- Template impor master tidak memuat gaji atau tanggal akhir kontrak. Data kontrak PKWT dicatat melalui form/fitur kontrak, bukan dibuat dari tanggal yang tidak tersedia di workbook.
- Karyawan PKWT yang belum memiliki kontrak berstatus `ACTIVE` disimpan nonaktif pada alur impor yang menerapkan validasi kontrak. HR harus melengkapi kontrak melalui aplikasi sebelum mengaktifkannya.
- Kontrak menyimpan nomor urut, tanggal mulai/akhir, status, dan keterangan. Histori kontrak yang sudah ada dipertahankan; perpanjangan/pengangkatan PKWTT tidak menghapus kontrak terdahulu.
- Untuk perpindahan PHL → PKWT yang dicatat melalui form edit, aplikasi menyimpan periode PHL dalam rekaman transisi tersendiri dan membuat kontrak PKWT aktif. Tanggal mulai PHL diprefill dari `join_date`, dapat dikoreksi tanpa mengubah `join_date`, dan berakhir sehari sebelum awal kontrak PKWT. Tanggal kontrak wajib lengkap dan tervalidasi.
- Rekaman periode PHL → PKWT hanya dibuat untuk transisi yang disimpan setelah fitur tersedia. Histori lama tidak ditebak atau di-backfill.
- HR Master dapat memperbaiki tanggal mulai/akhir, status, dan keterangan kontrak tanpa mengubah nomor kontrak. Jika kontrak memiliki periode transisi PHL, awal periode PHL harus tetap sebelum kontrak; tanggal transisi mengikuti awal kontrak dan akhir periode PHL otomatis sehari sebelumnya.
- Menghapus kontrak menghapus catatan transisi PHL yang terkait. Jika kontrak aktif tersebut memiliki catatan transisi, status karyawan dikembalikan menjadi PHL. Menghapus catatan transisi PHL saja tidak menghapus kontrak atau mengubah status karyawan.
- Pengingat kontrak mendekati masa akhir menggunakan konstanta aplikasi H-10; angka ini bukan nilai yang diedit melalui aturan profil.
- Default uang makan pada aturan global adalah Rp0 per hari dan berlaku sama untuk semua cabang. Nilai kosong pada master karyawan mengikuti default global; nominal override yang secara eksplisit diisi pada karyawan tetap digunakan.
- Aturan profil yang sudah ada untuk perhitungan uang makan, termasuk kelayakan bonus tanggal merah dan perlakuan IDD tanggal merah, tetap berlaku atas nominal dasar tersebut. Default nol tidak menghapus konfigurasi/override eksplisit.

## Cuti, izin, dan saldo

- Permohonan cuti/izin memiliki status seperti `PENDING`, `APPROVED`, atau `REJECTED`; perubahan status dan pencatatan saldo dilakukan melalui endpoint aplikasi.
- Kategori yang memotong kuota tahunan pada ledger saat ini adalah `CUTI_TAHUNAN` (1 hari) dan `CUTI_SETENGAH_HARI` (0,5 hari). Jenis lain tidak memotong kuota tahunan melalui pemetaan tersebut.
- Saldo adalah jumlah entri ledger untuk karyawan dan tahun terkait, bukan angka saldo yang berdiri sendiri. Ledger mencatat pemberian, pemakaian, pembalikan, dan penghangusan saldo.
- Konstanta saat ini menetapkan kuota penuh 12 hari dan reset tahunan 1 Januari. Untuk tahun anniversary pertama, implementasi memberikan kuota proporsional berdasarkan bulan anniversary (`13 - bulan anniversary`, dibatasi 1 sampai kuota penuh). Nilai dan algoritma ini tetap mengikuti konfigurasi/kode aplikasi.
- Tab rekap saldo pada UI menampilkan tahun berjalan tanpa pilihan tahun. API tetap menerima parameter `year` untuk kebutuhan integrasi dan detail lain.
- Perubahan aturan PHL berlaku untuk pengajuan baru saja; catatan pengajuan historis tidak direklasifikasi atau dihapus.

## Kebijakan PHL yang diterapkan

- PHL tidak dapat mengajukan cuti atau izin melalui endpoint web/chatbot.
- Pengecualian yang tetap tersedia adalah `WORK_FROM_LOCATION` (Absensi Jarak Jauh), dengan validasi dan persetujuan normal yang relevan.
- Ketidakhadiran PHL diproses melalui antrean review absensi; satu-satunya keputusan review yang diperbolehkan adalah `UNPAID_LEAVE`.
- Pembatasan diperiksa di backend dan ditampilkan di UI. Request langsung ke endpoint tetap harus tunduk pada validasi server.

## Absensi, profil, dan batas perhitungan

- Aturan global dan aturan profil dibaca dari database untuk pemrosesan absensi; perilaku kalkulasi terperinci dijelaskan di [Aturan Bisnis Profil](ATURAN-BISNIS-PROFIL.md).
- Data upload disimpan sebagai batch dan hasil absensi harian/review. File mentah tidak disimpan sebagai kolom database pada model batch.
- Perhitungan kompensasi PHK belum menghasilkan nominal; implementasi mengembalikan `estimated_compensation` kosong sampai aturan HR yang diperlukan ditetapkan.
- Nama pada beberapa tabel lama (misalnya pengajuan cuti, penyesuaian, dan absen manual) belum memiliki foreign key langsung ke `employees`. Proses rekonsiliasi harus memperlakukan hal itu sebagai keterbatasan integritas data, bukan menganggap seluruh hubungan berdasarkan nama terjamin.

## Kepemilikan perubahan

Aturan role, validasi kontrak, kategori cuti, pembatasan PHL, dan algoritma saldo adalah perilaku aplikasi. Nilai konfigurasi yang disimpan dalam tabel `profiles` dan `business_rule` dikelola melalui UI oleh HR Master; nilai tersebut dapat berubah dan tidak boleh dianggap sebagai konstanta bisnis tanpa memeriksa database yang sedang digunakan.
