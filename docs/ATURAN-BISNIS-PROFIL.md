# Aturan Bisnis Profil dan Karyawan

## Tujuan profil

Profil adalah konfigurasi jadwal/operasional yang dipakai pipeline absensi. Profil memiliki `code` unik sebagai kunci, nama tampilan, daftar cabang, hari kerja, jadwal masuk/pulang, patokan lembur, serta sejumlah flag dan parameter perhitungan.

| Bagian | Field utama | Makna pada aplikasi |
| --- | --- | --- |
| Identitas | `code`, `nama` | Kode stabil yang dirujuk karyawan dan label UI. |
| Penempatan | `cabang` | Daftar cabang pada profil dalam bentuk JSON. |
| Jadwal | `hari_kerja`, `jam_masuk`, `jam_keluar` | Hari kerja dan jam default/per hari. |
| Lembur | `patokan_lembur`, `ikut_lembur`, `lembur_khusus` | Patokan dan opsi pemrosesan lembur profil. |
| Keterlambatan | `ikut_telat` | Menentukan apakah aturan telat profil disertakan pada pipeline. |
| Kuota hari kerja | `ikut_kuota_hari_kerja`, `hari_kandidat_kuota`, `min_hari_kerja` | Opsi dan ambang terkait kalkulasi kuota hari kerja. |
| Hari merah | `ikut_bonus_tanggal_merah` | Opsi bonus terkait tanggal merah. |

Jam profil dapat disimpan sebagai nilai default atau peta hari, misalnya `{"default":"08:00","Sabtu":"13:00"}`. Bentuk `lembur_khusus` memiliki parameter seperti hari yang berlaku, threshold jam, tarif per jam, dan bonus flat.

## Aturan global dan pemuatan konfigurasi

Tabel `business_rule` merupakan konfigurasi global yang dirancang sebagai satu baris. Field-nya mencakup profil default, jam standar, deduplikasi scan, ambang hari kerja, parameter uang makan/potongan, bonus lembur, pembulatan lembur, dan toleransi telat.

Saat pipeline dijalankan, `pipeline.config_runtime.reload_from_db()` memuat profil dan aturan global dari database. Jika belum ada baris aturan global, nilai fallback di kode digunakan. Konfigurasi DB yang dipakai pipeline dengan demikian dapat berubah dari waktu ke waktu; laporan proses sebaiknya mengidentifikasi lingkungan dan konfigurasi yang berlaku.

Default uang makan global adalah Rp0 per hari untuk seluruh cabang. Nilai `employees.uang_makan_override` yang kosong mengikuti aturan global; nominal yang diisi secara eksplisit menjadi override karyawan. Kelayakan dan perhitungan tanggal merah berbasis profil/cabang yang telah ada tetap berlaku, tetapi tidak mengubah nominal default global.

## Karyawan dan relasinya dengan profil

- `employees.profile_code` adalah foreign key ke `profiles.code`; profil yang sedang dipakai karyawan tidak dapat dihapus sebelum karyawan dipindahkan ke profil lain.
- `employees.cabang` adalah teks tersendiri, bukan foreign key ke katalog cabang. UI edit menyajikan gabungan cabang dari profil dan cabang yang sudah tersimpan pada karyawan agar nilai lama tetap dapat dipilih.
- Kode profil, bukan nama tampilan profil, menjadi referensi master yang stabil. Nama profil dapat berubah tanpa mengganti kode karyawan.
- `employment_status` (`PKWTT`, `PKWT`, atau `PHL`), tanggal masuk, status aktif, dan data kontrak adalah atribut master terpisah dari konfigurasi jadwal profil.

## Override pada tingkat karyawan

Model dan form karyawan menyediakan `has_custom_rules` dan beberapa field override, antara lain jam masuk/pulang, toleransi telat, dan bonus lembur per jam. Kolom-kolom ini tersimpan pada master karyawan. Namun pemuatan konfigurasi pipeline yang ditinjau di dokumen ini secara eksplisit memuat profil dan `business_rule`; penggunaan semua override karyawan oleh setiap jalur kalkulasi belum dapat dipastikan. Karena itu:

1. Jangan menganggap toggle atau nilai override sebagai hasil perhitungan yang sudah terjamin tanpa menguji jalur pipeline terkait.
2. Perubahan pada perilaku override memerlukan regression test terpisah pada data karyawan sintetis dan perhitungan absensi.
3. Dokumen ini tidak mengubah algoritma maupun menjanjikan perilaku override baru.

## Hak perubahan dan penghapusan

- Semua pengguna HR yang berhak dapat melihat profil/aturan sesuai otorisasi API.
- Hanya HR Master yang dapat membuat, memperbarui, atau menghapus profil serta mengubah aturan global.
- Profil yang masih direferensikan oleh satu atau lebih karyawan ditolak penghapusannya oleh backend.
- Daftar cabang profil dapat digunakan sebagai pilihan input; data cabang karyawan tetap merupakan nilai tersendiri di database.

## Parameter kode yang bukan konfigurasi profil

Kuota tahunan default (12 hari), batas pengingat kontrak (H-10), daftar role, status kepegawaian yang diterima, dan sejumlah aturan validasi berada pada kode/config backend. Mengubah profil tidak otomatis mengubah parameter-parameter tersebut. Periksa implementasi/config yang dirilis sebelum mengutip angka atau perilaku sebagai kebijakan berjalan.
