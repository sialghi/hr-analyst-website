# -*- coding: utf-8 -*-
"""
excel_writer.py
================
Tulis semua hasil ke satu file .xlsx sesuai struktur di Bagian 4 rencana.

REVISI v2: Ditambah sheet Uang Makan, Rekap per Profil, Perlu Dicek.
Sheet Lembur ditambah kolom Bonus_Lembur_Rp. Semua sheet punya kolom Tanggal.

CATATAN DESAIN (beda dari dummy, disengaja):
Dummy punya baris "Filter Bulan / Filter Cabang" yang sifatnya CONTOH VISUAL
saja (bukan filter yang benar-benar berfungsi). Sebagai gantinya saya pasang
**AutoFilter** bawaan Excel di sheet Preprocessing & Summary Overview - user
tinggal klik ikon panah di header kolom Cabang/Tanggal utk filter per
cabang/bulan. Ini fitur native Excel, selalu jalan, dan tidak butuh formula
tambahan yang rawan rusak.
"""
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side, numbers
from openpyxl.utils import get_column_letter
from openpyxl.chart import BarChart, Reference
import pandas as pd
import numpy as np

FONT_NORMAL = Font(name="Arial", size=10)
FONT_HEADER = Font(name="Arial", size=10, bold=True)
FONT_TITLE = Font(name="Arial", size=13, bold=True)
FONT_SUBTITLE = Font(name="Arial", size=9, italic=True, color="555555")
FILL_HEADER = PatternFill("solid", fgColor="305496")
FILL_ALT = PatternFill("solid", fgColor="F2F2F2")
FILL_KUNING_LEMBUR = PatternFill("solid", fgColor="FFFF00")  # Kuning penanda lembur khusus Minggu
THIN = Side(style="thin", color="D9D9D9")
BORDER_ALL = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
FMT_RUPIAH = '#,##0'


def _tulis_judul(ws, judul, subjudul=None, n_kolom=8):
    ws["A1"] = judul
    ws["A1"].font = FONT_TITLE
    if subjudul:
        ws["A2"] = subjudul
        ws["A2"].font = FONT_SUBTITLE
    if n_kolom > 1:
        ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=n_kolom)
        if subjudul:
            ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=n_kolom)


def _tulis_header_tabel(ws, row, headers):
    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=row, column=i, value=h)
        c.font = FONT_HEADER
        # Background bawaan/putih untuk header agar lebih kompatibel
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = BORDER_ALL


def _nilai_aman(v):
    """Konversi NaN/NaT/None jadi None supaya openpyxl menulis cell KOSONG (bukan string 'NaT')."""
    if v is None:
        return None
    if isinstance(v, float) and np.isnan(v):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _tulis_dataframe(ws, df, start_row, start_col=1, dengan_border=True, kolom_rupiah=None, highlight_row_fn=None):
    """Tulis DataFrame apa adanya (bukan formula) - untuk sheet data mentah/detail.
    kolom_rupiah: set of 0-indexed column positions yang harus diformat sebagai Rupiah.
    highlight_row_fn: callable(row_namedtuple) -> PatternFill or None untuk highlight baris.
    """
    if kolom_rupiah is None:
        kolom_rupiah = set()
    for r_idx, row in enumerate(df.itertuples(index=False), start=start_row):
        row_fill = highlight_row_fn(row) if highlight_row_fn else None
        for c_idx, val in enumerate(row, start=start_col):
            cell = ws.cell(row=r_idx, column=c_idx, value=_nilai_aman(val))
            cell.font = FONT_NORMAL
            if dengan_border:
                cell.border = BORDER_ALL
            if row_fill is not None:
                cell.fill = row_fill
            elif (r_idx - start_row) % 2 == 1:
                cell.fill = FILL_ALT
            # Format Rupiah
            if (c_idx - start_col) in kolom_rupiah:
                cell.number_format = FMT_RUPIAH
    return start_row + len(df)


def _autosize(ws, n_kolom, lebar_default=16, max_lebar=40):
    for i in range(1, n_kolom + 1):
        col_letter = get_column_letter(i)
        max_len = lebar_default
        for cell in ws[col_letter]:
            try:
                v = cell.value
                if v is not None:
                    max_len = max(max_len, min(len(str(v)) + 2, max_lebar))
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = max_len


def _sheet_readme(wb, ringkasan_info):
    ws = wb.create_sheet("README")
    _tulis_judul(ws, "README — Panduan Membaca Laporan Absensi HR (v2)", n_kolom=6)
    baris = [
        "",
        "Sheet dalam file ini:",
        "2. Summary Overview    -> ringkasan per karyawan, semua angka pakai formula.",
        "3. Data Mentah         -> log scan asli, tidak diubah, untuk audit.",
        "4. Preprocessing       -> data harian per karyawan setelah agregasi & koreksi jam. Kolom 'Status Data' & 'Profil'.",
        "5. Rekap Telat         -> setiap kejadian telat, dengan durasi. Patokan jam per profil.",
        "6. Rekap Lembur        -> setiap kejadian lembur, dengan durasi & bonus Rp. Patokan jam per profil.",
        "7. Rekap Pulang Duluan -> setiap kejadian pulang sebelum jam standar, dengan durasi kurang.",
        "8. Rekap Tidak Masuk   -> per minggu per karyawan yang hadir < kuota hari kerja (sesuai profil).",
        "9. Data Tidak Lengkap  -> hari yang cuma ada satu sisi scan - dikeluarkan dari perhitungan.",
        "10. Perbandingan Cabang -> agregasi sheet 2 per cabang.",
        "11. Rekap Alpa Berulang -> karyawan yang 'minggu bermasalah'-nya terjadi >=2 minggu BERTURUT-TURUT.",
        "12. Uang Makan         -> perhitungan uang makan per hari per karyawan (potongan telat, potongan pulang duluan, & bonus tanggal merah).",
        "13. Rekap per Profil   -> kehadiran & jam kerja untuk profil non-logic-utama (Live Stream, Setup, OB).",
        "14. Perlu Dicek        -> nama di data absensi yang tidak ditemukan di file master karyawan.",
        "",
        "7 Profil Jadwal Kerja:",
        "- OFFICE           : Sen-Jum 08-16, Sab 08-13",
        "- GUDANG           : Sen-Sab 08-16",
        "- JAVAPETCO        : Sen-Min 09-19 (1 hari libur fleksibel)",
        "- ANAK_KONTEN_LIVE : Fleksibel, target 5-8 jam/hari",
        "- ANAK_KONTEN_MARKETING : Sen-Jum 09-17, Sab 09-16",
        "- SETUP_BLOK_C     : Sen-Sab 08-16",
        "- OFFICE_BOY       : 07-15",
        "",
        "Uang Makan: Rp100.000/hari (bisa di-override per orang).",
        "Potongan telat: ≤12:00 = Rp10.000, 12:00-15:00 = 50% uang makan.",
        "Bonus tanggal merah: +1× uang makan kalau masuk di tanggal merah nasional (profil tertentu).",
        "Bonus lembur: Rp10.000/jam (pembulatan: ≥31 menit sisa = 1 jam).",
        "",
        "Cara filter per cabang / per bulan:",
        "Klik ikon panah di header kolom 'Cabang' atau 'Tanggal' pada sheet Preprocessing / Summary Overview (AutoFilter bawaan Excel).",
        "",
    ]

    for i, teks in enumerate(baris, start=4):
        ws.cell(row=i, column=1, value=teks).font = FONT_NORMAL
    _autosize(ws, 6, lebar_default=20, max_lebar=110)


def _sheet_data_mentah(wb, df_mentah):
    ws = wb.create_sheet("3. Data Mentah")
    _tulis_judul(ws, "3. Data Mentah", "Log scan mesin absen, apa adanya dari file input (untuk audit).", n_kolom=len(df_mentah.columns))
    _tulis_header_tabel(ws, 4, list(df_mentah.columns))
    _tulis_dataframe(ws, df_mentah, start_row=5)
    ws.freeze_panes = "A5"
    _autosize(ws, len(df_mentah.columns))


def _sheet_preprocessing(wb, df_prep):
    ws = wb.create_sheet("4. Preprocessing")
    kolom_tampil = ["Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Masuk", "Jam_Keluar",
                     "Status_Data", "Kategori_Hari", "Is_Tanggal_Merah", "Catatan"]
    # Filter kolom yang ada
    kolom_ada = [c for c in kolom_tampil if c in df_prep.columns]
    df_show = df_prep[kolom_ada].rename(columns={
        "Jam_Masuk": "Jam Masuk", "Jam_Keluar": "Jam Keluar",
        "Status_Data": "Status Data", "Kategori_Hari": "Kategori Hari",
        "Is_Tanggal_Merah": "Tanggal Merah",
    })
    _tulis_judul(
        ws, "4. Preprocessing — Agregasi Harian & Koreksi",
        "Jam Masuk = scan tercepat, Jam Keluar = scan terakhir. Label salah sudah dikoreksi per profil. "
        "Kolom Profil dari file master karyawan.",
        n_kolom=len(df_show.columns),
    )
    _tulis_header_tabel(ws, 4, list(df_show.columns))
    baris_akhir = _tulis_dataframe(ws, df_show, start_row=5)
    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(df_show.columns))}{baris_akhir-1}"
    _autosize(ws, len(df_show.columns))
    return baris_akhir - 1  # baris data terakhir


def _sheet_rekap_kejadian(wb, nama_sheet, judul, subjudul, df, kolom_map, kolom_rupiah_nama=None, highlight_row_fn=None):
    """kolom_rupiah_nama: list nama kolom OUTPUT yang mau diformat Rupiah."""
    ws = wb.create_sheet(nama_sheet)
    df_copy = df.copy()
    for col in kolom_map.keys():
        if col not in df_copy.columns:
            df_copy[col] = None
    df_show = df_copy.rename(columns=kolom_map)[list(kolom_map.values())]
    n_kolom = max(1, len(df_show.columns))
    _tulis_judul(ws, judul, subjudul, n_kolom=n_kolom)
    _tulis_header_tabel(ws, 4, list(df_show.columns))

    # Cari index kolom Rupiah
    rp_set = set()
    if kolom_rupiah_nama:
        header_list = list(df_show.columns)
        for nama in kolom_rupiah_nama:
            if nama in header_list:
                rp_set.add(header_list.index(nama))

    baris_akhir = _tulis_dataframe(ws, df_show, start_row=5, kolom_rupiah=rp_set, highlight_row_fn=highlight_row_fn)
    ws.freeze_panes = "A5"
    _autosize(ws, len(df_show.columns))
    if len(df_show) == 0:
        ws.cell(row=5, column=1, value="(tidak ada kejadian pada periode data ini)").font = FONT_SUBTITLE
    return baris_akhir - 1


def _sheet_tidak_masuk(wb, df):
    kolom_map = {
        "Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil", "Minggu": "Minggu",
        "Jml_Hari_Valid": "Jml Hari Valid", "Jml_Hari_Tidak_Masuk": "Jml Hari Tidak Masuk",
        "Hari_Tidak_Masuk": "Hari yang Tidak Masuk",
        "Keterangan": "Keterangan",
    }
    return _sheet_rekap_kejadian(
        wb, "8. Rekap Tidak Masuk", "8. Rekap Tidak Masuk",
        "Ditampilkan jika hari kerja valid dalam 1 minggu < kuota minimal (sesuai profil).",
        df, kolom_map,
    )


def _sheet_data_tidak_lengkap(wb, df_prep):
    kolom_list = ["Cabang", "Nama", "Profil", "Tanggal", "Hari", "Jam_Masuk", "Jam_Keluar", "Catatan"]
    kolom_ada = [c for c in kolom_list if c in df_prep.columns]
    df = df_prep[df_prep["Status_Data"] == "Tidak Lengkap"][kolom_ada].rename(
        columns={"Jam_Masuk": "Jam Masuk", "Jam_Keluar": "Jam Keluar"}
    )
    ws = wb.create_sheet("9. Data Tidak Lengkap")
    _tulis_judul(
        ws, "9. Data Tidak Lengkap",
        "Hari yang dikeluarkan dari Data Process (Aturan #11) - cuma ada 1 sisi scan. Untuk verifikasi manual HR.",
        n_kolom=len(df.columns),
    )
    _tulis_header_tabel(ws, 4, list(df.columns))
    _tulis_dataframe(ws, df, start_row=5)
    ws.freeze_panes = "A5"
    _autosize(ws, len(df.columns))


def _sheet_summary_overview(wb, daftar_karyawan):
    """
    daftar_karyawan: DataFrame kolom [Cabang, Nama, Profil] - satu baris per karyawan unik.

    Semua metrik ditulis sebagai FORMULA yang merujuk ke sheet 2-6.
    REVISI v2: tambah kolom Total Uang Makan dan Total Bonus Lembur Rp.
    """
    ws = wb.create_sheet("2. Summary Overview")
    headers = [
        "Cabang", "Nama", "Profil", "Absensi In", "Absensi Out", "Hari Kerja Valid", "Masuk Tanggal Merah",
        "Jml Telat", "Total Durasi Telat", "Jml Lembur", "Jam Lembur (Bulat)",
        "Total Bonus Lembur (Rp)", "Jml Pulang Duluan", "Total Durasi Pulang Duluan",
        "Minggu Bermasalah", "Jumlah Hari Tidak Masuk",
        "Uang Makan Harian (Rp)", "Potongan Telat (Rp)", "Potongan Pulang Duluan (Rp)",
        "Bonus Tanggal Merah (Rp)", "Total Uang Makan Akhir (Rp)",
    ]
    _tulis_judul(
        ws, "2. Summary Overview per Karyawan",
        "Ringkasan per karyawan. Semua angka pakai formula. "
        "Total Uang Makan ada di sheet 12 (Uang Makan).",
        n_kolom=len(headers),
    )
    _tulis_header_tabel(ws, 4, headers)

    baris_mulai = 5
    n = len(daftar_karyawan)
    for i, (_, row) in enumerate(daftar_karyawan.iterrows()):
        r = baris_mulai + i
        ws.cell(row=r, column=1, value=row["Cabang"]).font = FONT_NORMAL
        ws.cell(row=r, column=2, value=row["Nama"]).font = FONT_NORMAL
        profil_val = row.get("Profil", "")
        ws.cell(row=r, column=3, value=profil_val).font = FONT_NORMAL
        nama_ref = f"$B{r}"

        # Col D: Absensi In
        ws.cell(row=r, column=4,
                value=f"=COUNTIFS('4. Preprocessing'!$B:$B,{nama_ref},'4. Preprocessing'!$F:$F,\"<>\")")
        # Col E: Absensi Out
        ws.cell(row=r, column=5,
                value=f"=COUNTIFS('4. Preprocessing'!$B:$B,{nama_ref},'4. Preprocessing'!$G:$G,\"<>\")")
        # Col F: Hari Kerja Valid
        ws.cell(row=r, column=6,
                value=(f"=COUNTIFS('4. Preprocessing'!$B:$B,{nama_ref},"
                       f"'4. Preprocessing'!$H:$H,\"Lengkap\","
                       f"'4. Preprocessing'!$I:$I,\"Kerja\")"))
        # Col G: Masuk Tanggal Merah
        ws.cell(row=r,column=7,value=f"=COUNTIFS('4. Preprocessing'!$B:$B,{nama_ref},'4. Preprocessing'!$I:$I,\"Tanggal Merah\")")
        # Col H: Jml Telat
        ws.cell(row=r, column=8, value=f"=COUNTIF('5. Rekap Telat'!$B:$B,{nama_ref})")
        # Col I: Total Durasi Telat
        sumif_telat = f"SUMIF('5. Rekap Telat'!$B:$B,{nama_ref},'5. Rekap Telat'!$G:$G)"
        ws.cell(row=r, column=9, value=f'=IF({sumif_telat}>0, INT({sumif_telat}) & " jam " & ROUND(({sumif_telat}-INT({sumif_telat}))*60, 0) & " menit", "0 menit")')
        # Col J: Jml Lembur
        ws.cell(row=r, column=10, value=f"=COUNTIF('6. Rekap Lembur'!$B:$B,{nama_ref})")
        # Col K: Jam Lembur (Bulat)
        sumif_lembur = f"SUMIF('6. Rekap Lembur'!$B:$B,{nama_ref},'6. Rekap Lembur'!$I:$I)"
        ws.cell(row=r, column=11, value=f"={sumif_lembur}")
        # Col L: Total Bonus Lembur Rp
        ws.cell(row=r, column=12, value=f"=SUMIF('6. Rekap Lembur'!$B:$B,{nama_ref},'6. Rekap Lembur'!$J:$J)")
        ws.cell(row=r, column=12).number_format = FMT_RUPIAH
        # Col M: Jml Pulang Duluan
        ws.cell(row=r, column=13, value=f"=COUNTIF('7. Rekap Pulang Duluan'!$B:$B,{nama_ref})")
        # Col N: Total Durasi Pulang Duluan
        sumif_pulang = f"SUMIF('7. Rekap Pulang Duluan'!$B:$B,{nama_ref},'7. Rekap Pulang Duluan'!$G:$G)"
        ws.cell(row=r, column=14, value=f'=IF({sumif_pulang}>0, INT({sumif_pulang}) & " jam " & ROUND(({sumif_pulang}-INT({sumif_pulang}))*60, 0) & " menit", "0 menit")')
        
        # Col N: Minggu Bermasalah
        ws.cell(row=r, column=15, value=f"=COUNTIF('8. Rekap Tidak Masuk'!$B:$B,{nama_ref})")
        # Col O: Jumlah Hari Tidak Masuk
        ws.cell(row=r, column=16, value=f"=SUMIF('8. Rekap Tidak Masuk'!$B:$B,{nama_ref},'8. Rekap Tidak Masuk'!$F:$F)")
        # Col P: Uang Makan Harian
        ws.cell(row=r, column=17, value=f"=SUMIF('12. Uang Makan'!$B:$B,{nama_ref},'12. Uang Makan'!$F:$F)")
        ws.cell(row=r, column=17).number_format = FMT_RUPIAH
        # Col Q: Potongan Telat
        ws.cell(row=r, column=18, value=f"=SUMIF('12. Uang Makan'!$B:$B,{nama_ref},'12. Uang Makan'!$G:$G)")
        ws.cell(row=r, column=18).number_format = FMT_RUPIAH
        # Col R: Potongan Pulang Duluan
        ws.cell(row=r, column=19, value=f"=SUMIF('12. Uang Makan'!$B:$B,{nama_ref},'12. Uang Makan'!$H:$H)")
        ws.cell(row=r, column=19).number_format = FMT_RUPIAH
        # Col S: Bonus Tanggal Merah
        ws.cell(row=r, column=20, value=f"=SUMIF('12. Uang Makan'!$B:$B,{nama_ref},'12. Uang Makan'!$I:$I)")
        ws.cell(row=r, column=20).number_format = FMT_RUPIAH
        # Col T: Total Uang Makan Akhir
        ws.cell(row=r, column=21, value=f"=SUMIF('12. Uang Makan'!$B:$B,{nama_ref},'12. Uang Makan'!$J:$J)")
        ws.cell(row=r, column=21).number_format = FMT_RUPIAH

        for c in range(1, len(headers) + 1):
            ws.cell(row=r, column=c).border = BORDER_ALL
            if i % 2 == 1:
                ws.cell(row=r, column=c).fill = FILL_ALT

    baris_akhir = baris_mulai + n - 1
    if n > 0:
        ws.auto_filter.ref = f"A4:{get_column_letter(len(headers))}{baris_akhir}"
    ws.freeze_panes = "A5"
    _autosize(ws, len(headers))

    if n > 0:
        chart = BarChart()
        chart.title = "Jml Telat vs Lembur vs Pulang Duluan per Karyawan"
        chart.y_axis.title = "Jumlah Kejadian"
        chart.x_axis.title = "Nama"
        data = Reference(ws, min_col=7, max_col=7, min_row=4, max_row=baris_akhir)
        data2 = Reference(ws, min_col=9, max_col=9, min_row=4, max_row=baris_akhir)
        data3 = Reference(ws, min_col=12, max_col=12, min_row=4, max_row=baris_akhir)
        cats = Reference(ws, min_col=2, min_row=baris_mulai, max_row=baris_akhir)
        chart.add_data(data, titles_from_data=True)
        chart.add_data(data2, titles_from_data=True)
        chart.add_data(data3, titles_from_data=True)
        chart.set_categories(cats)
        chart.height, chart.width = 9, 22
        ws.add_chart(chart, f"A{baris_akhir+3}")

    return baris_mulai, baris_akhir


def _sheet_perbandingan_cabang(wb, daftar_cabang, ref_summary):
    baris_mulai_sum, baris_akhir_sum = ref_summary
    ws = wb.create_sheet("10. Perbandingan Cabang")
    headers = [
        "Cabang", "Jml Karyawan", "Total Kejadian Telat", "Total Durasi Telat",
        "Total Kejadian Lembur", "Jam Lembur (Bulat)", "Total Kejadian Pulang Duluan",
        "Minggu Bermasalah",
    ]
    _tulis_judul(ws, "10. Perbandingan Antar Cabang",
                 "Agregasi dari sheet 2 (Summary Overview) - untuk evaluasi manajerial lintas cabang.",
                 n_kolom=len(headers))
    _tulis_header_tabel(ws, 4, headers)

    baris_mulai = 5
    rng_cabang = f"'2. Summary Overview'!$A${baris_mulai_sum}:$A${baris_akhir_sum}"
    for i, cabang in enumerate(daftar_cabang):
        r = baris_mulai + i
        ws.cell(row=r, column=1, value=cabang).font = FONT_NORMAL
        ref = f"$A{r}"
        ws.cell(row=r, column=2, value=f"=COUNTIF({rng_cabang},{ref})")
        # Kejadian Telat
        ws.cell(row=r, column=3, value=f"=COUNTIF('5. Rekap Telat'!$A:$A,{ref})")
        # Durasi Telat
        sumif_telat_cabang = f"SUMIF('5. Rekap Telat'!$A:$A,{ref},'5. Rekap Telat'!$G:$G)"
        ws.cell(row=r, column=4, value=f'=IF({sumif_telat_cabang}>0, INT({sumif_telat_cabang}) & " jam " & ROUND(({sumif_telat_cabang}-INT({sumif_telat_cabang}))*60, 0) & " menit", "0 menit")')
        
        # Kejadian Lembur
        ws.cell(row=r, column=5, value=f"=COUNTIF('6. Rekap Lembur'!$A:$A,{ref})")
        # Jam Lembur (Bulat)
        sumif_lembur_cabang = f"SUMIF('6. Rekap Lembur'!$A:$A,{ref},'6. Rekap Lembur'!$I:$I)"
        ws.cell(row=r, column=6, value=f"={sumif_lembur_cabang}")
        
        # Kejadian Pulang Duluan
        ws.cell(row=r, column=7, value=f"=COUNTIF('7. Rekap Pulang Duluan'!$A:$A,{ref})")
        
        # Minggu Bermasalah
        ws.cell(row=r, column=8, value=f"=COUNTIF('8. Rekap Tidak Masuk'!$A:$A,{ref})")
        
        for c in range(1, len(headers) + 1):
            ws.cell(row=r, column=c).border = BORDER_ALL
            if i % 2 == 1:
                ws.cell(row=r, column=c).fill = FILL_ALT

    baris_akhir = baris_mulai + len(daftar_cabang) - 1
    _autosize(ws, len(headers))

    if len(daftar_cabang) > 0:
        chart = BarChart()
        chart.title = "Perbandingan Kejadian per Cabang"
        chart.y_axis.title = "Jumlah Kejadian"
        data = Reference(ws, min_col=3, max_col=3, min_row=4, max_row=baris_akhir)
        data2 = Reference(ws, min_col=5, max_col=5, min_row=4, max_row=baris_akhir)
        data3 = Reference(ws, min_col=7, max_col=7, min_row=4, max_row=baris_akhir)
        cats = Reference(ws, min_col=1, min_row=baris_mulai, max_row=baris_akhir)
        chart.add_data(data, titles_from_data=True)
        chart.add_data(data2, titles_from_data=True)
        chart.add_data(data3, titles_from_data=True)
        chart.set_categories(cats)
        chart.height, chart.width = 9, 22
        ws.add_chart(chart, f"A{baris_akhir+3}")


def _sheet_alpa_berulang(wb, df):
    kolom_map = {
        "Nama": "Nama", "Jml_Minggu_Beruntun": "Jml Minggu Beruntun",
        "Periode_Minggu": "Periode Minggu", "Keterangan": "Keterangan",
    }
    _sheet_rekap_kejadian(
        wb, "11. Rekap Alpa Berulang", "11. Rekap Alpa Berulang",
        "Karyawan dengan 'minggu bermasalah' (<4 hari kerja) terjadi >=2 minggu BERTURUT-TURUT.",
        df, kolom_map,
    )


def _sheet_uang_makan(wb, df_uang_makan):
    """BARU v2: Sheet uang makan per orang per hari."""
    kolom_map = {
        "Cabang": "Cabang",
        "Nama": "Nama",
        "Profil": "Profil",
        "Tanggal": "Tanggal",
        "Hari": "Hari",
        "Uang_Makan_Base": "Uang Makan (Rp)",
        "Potongan_Telat": "Potongan Telat (Rp)",
        "Potongan_Pulang_Duluan": "Potongan Pulang Duluan (Rp)",
        "Bonus_Tanggal_Merah": "Bonus Tanggal Merah (Rp)",
        "Total_Uang_Makan": "Total Uang Makan (Rp)",
    }
    kolom_rp = ["Uang Makan (Rp)", "Potongan Telat (Rp)", "Potongan Pulang Duluan (Rp)", "Bonus Tanggal Merah (Rp)", "Total Uang Makan (Rp)"]
    _sheet_rekap_kejadian(
        wb, "12. Uang Makan", "12. Uang Makan",
        "Perhitungan uang makan harian: base, potongan telat, potongan pulang duluan, bonus tanggal merah.",
        df_uang_makan, kolom_map,
        kolom_rupiah_nama=kolom_rp,
    )


def _sheet_rekap_profil(wb, df_profil_exclude):
    """BARU v2: Sheet rekap kehadiran untuk profil exclude."""
    kolom_map = {
        "Cabang": "Cabang",
        "Nama": "Nama",
        "Profil": "Profil",
        "Tanggal": "Tanggal",
        "Hari": "Hari",
        "Jam_Masuk": "Jam Masuk",
        "Jam_Keluar": "Jam Keluar",
        "Total_Jam_Kerja": "Total Jam Kerja",
    }
    _sheet_rekap_kejadian(
        wb, "13. Rekap per Profil", "13. Rekap per Profil (Non-Logic Utama)",
        "Kehadiran & total jam kerja untuk profil: Anak Konten Live Stream, Setup Blok C, Office Boy. "
        "Tanpa kolom telat/lembur (tidak relevan untuk profil ini).",
        df_profil_exclude, kolom_map,
    )


def _sheet_perlu_dicek(wb, df_perlu_dicek):
    """BARU v2: Sheet nama yang tidak ditemukan di master."""
    ws = wb.create_sheet("14. Perlu Dicek")
    headers = ["Nama", "Cabang", "Jumlah Scan"]
    _tulis_judul(
        ws, "14. Perlu Dicek — Nama Tidak Ditemukan di Master",
        "Nama-nama di data absensi yang tidak cocok dengan file master karyawan. "
        "Periksa: typo, belum didaftarkan, atau beda penulisan.",
        n_kolom=len(headers),
    )
    _tulis_header_tabel(ws, 4, headers)

    if df_perlu_dicek is not None and not df_perlu_dicek.empty:
        kolom_map = {"Nama": "Nama", "Cabang": "Cabang", "Jumlah_Scan": "Jumlah Scan"}
        df_show = df_perlu_dicek.rename(columns=kolom_map)[list(kolom_map.values())]
        _tulis_dataframe(ws, df_show, start_row=5)
    else:
        ws.cell(row=5, column=1, value="(semua nama di data absensi ditemukan di file master ✓)").font = FONT_SUBTITLE

    ws.freeze_panes = "A5"
    _autosize(ws, len(headers))


def tulis_laporan_excel(path_output, df_mentah, df_prep, df_telat, df_lembur,
                         df_pulang_duluan, df_tidak_masuk, df_alpa_berulang,
                         catatan_asumsi, df_uang_makan=None,
                         df_profil_exclude=None, df_perlu_dicek=None):
    """
    REVISI v2: Terima 3 DataFrame baru opsional:
    - df_uang_makan: hasil hitung_uang_makan()
    - df_profil_exclude: hasil hitung_rekap_profil_exclude()
    - df_perlu_dicek: hasil cari_nama_tidak_dikenal()
    """
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # buang sheet default kosong

    _sheet_readme(wb, {"catatan": catatan_asumsi})

    # Daftar karyawan unik untuk Summary Overview
    kolom_group = ["Nama"]
    if "Profil" in df_prep.columns:
        daftar_karyawan = (
            df_prep.groupby("Nama").agg(
                Cabang=("Cabang", lambda s: s.value_counts().idxmax()),
                Profil=("Profil", "first"),
            ).reset_index()
            [["Cabang", "Nama", "Profil"]]
            .sort_values(["Cabang", "Nama"])
        )
    else:
        daftar_karyawan = (
            df_prep.groupby("Nama")["Cabang"]
            .agg(lambda s: s.value_counts().idxmax())
            .reset_index()
            .rename(columns={"Cabang": "Cabang"})
            [["Cabang", "Nama"]]
            .sort_values(["Cabang", "Nama"])
        )

    ref_summary = _sheet_summary_overview(wb, daftar_karyawan)
    daftar_cabang = sorted(daftar_karyawan["Cabang"].unique().tolist())

    _sheet_data_mentah(wb, df_mentah)
    _sheet_preprocessing(wb, df_prep)

    # --- Sheet 3: Rekap Telat ---
    kolom_telat = {
        "Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil",
        "Tanggal": "Tanggal", "Hari": "Hari",
        "Jam_Masuk": "Jam Masuk", "Jam_Masuk_Standar": "Jam Standar",
        "Durasi_Telat_Format": "Durasi Telat",
        "Kejadian_Ke": "Telat Ke-", "Status_Toleransi": "Status Toleransi",
        "Potongan_Telat_Rp": "Potongan (Rp)",
    }
    kolom_telat = {k: v for k, v in kolom_telat.items() if k in df_telat.columns}
    _sheet_rekap_kejadian(
        wb, "5. Rekap Telat", "5. Rekap Telat",
        "Detail per kejadian: tanggal, jam masuk, durasi telat, status toleransi (1x max 10 m per periode).",
        df_telat, kolom_telat,
        kolom_rupiah_nama=["Potongan (Rp)"],
    )

    # Highlight baris kuning untuk Harry / Driver lembur hari Minggu
    def _highlight_lembur_minggu_driver(row):
        hari = getattr(row, "Hari", None)
        profil = str(getattr(row, "Profil", "")).upper()
        nama = str(getattr(row, "Nama", "")).lower()
        if hari == "Minggu" and ("DRIVER" in profil or "harry" in nama):
            return FILL_KUNING_LEMBUR
        return None

    # --- Sheet 4: Rekap Lembur (+ Bonus Rp) ---
    kolom_lembur = {"Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil",
                    "Tanggal": "Tanggal", "Hari": "Hari",
                    "Jam_Keluar": "Jam Keluar", "Jam_Keluar_Standar": "Jam Standar",
                    "Durasi_Lembur_Format": "Durasi Lembur",
                    "Jam_Lembur_Bulat": "Jam Lembur (bulat)",
                    "Bonus_Lembur_Rp": "Bonus Lembur (Rp)"}
    kolom_lembur = {k: v for k, v in kolom_lembur.items() if k in df_lembur.columns}
    _sheet_rekap_kejadian(
        wb, "6. Rekap Lembur", "6. Rekap Lembur",
        "Detail per kejadian: tanggal, jam keluar, durasi lembur, bonus Rp. Pembulatan: ≥31 menit sisa = 1 jam.",
        df_lembur, kolom_lembur,
        kolom_rupiah_nama=["Bonus Lembur (Rp)"],
        highlight_row_fn=_highlight_lembur_minggu_driver,
    )

    # --- Sheet 5: Rekap Pulang Duluan ---
    kolom_pd = {"Cabang": "Cabang", "Nama": "Nama", "Profil": "Profil",
                "Tanggal": "Tanggal", "Hari": "Hari",
                "Jam_Keluar": "Jam Keluar",
                "Durasi_Kurang_Format": "Durasi Kurang"}
    kolom_pd = {k: v for k, v in kolom_pd.items() if k in df_pulang_duluan.columns}
    _sheet_rekap_kejadian(
        wb, "7. Rekap Pulang Duluan", "7. Rekap Pulang Duluan",
        "Detail per kejadian: tanggal, jam keluar, durasi kurang dari patokan profil.",
        df_pulang_duluan, kolom_pd,
    )

    _sheet_tidak_masuk(wb, df_tidak_masuk)
    _sheet_data_tidak_lengkap(wb, df_prep)

    _sheet_perbandingan_cabang(wb, daftar_cabang, ref_summary)
    _sheet_alpa_berulang(wb, df_alpa_berulang)

    # --- Sheet baru v2 ---
    if df_uang_makan is not None:
        _sheet_uang_makan(wb, df_uang_makan)

    if df_profil_exclude is not None:
        _sheet_rekap_profil(wb, df_profil_exclude)

    if df_perlu_dicek is not None:
        _sheet_perlu_dicek(wb, df_perlu_dicek)
    else:
        # Tetap buat sheet kosong supaya user tahu fiturnya ada
        _sheet_perlu_dicek(wb, pd.DataFrame())

    wb.save(path_output)
    return path_output
