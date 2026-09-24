"use client";
import { useRef, useState, useMemo, useCallback, useEffect } from "react";
import { api, triggerBlobDownload } from "@/lib/api";
import { PageHeader, Card, Button, Banner } from "@/components/ui";

/* ===================================================================
   TYPE DEFINITIONS
   =================================================================== */
interface SheetData {
  headers: string[];
  types: Record<string, string>;
  rows: Record<string, any>[];
  catatan?: string[];
}

interface SheetInfo {
  key: string;
  title: string;
  data: SheetData;
}

interface KPIs {
  total_karyawan: number;
  total_telat: number;
  total_lembur: number;
  total_bonus_lembur: number;
  total_uang_makan: number;
  total_pulang_duluan: number;
  jml_perlu_dicek: number;
  total_baris_scan: number;
}

interface ProcessResult {
  file_id: string;
  filename: string;
  kpis: KPIs;
  sheets: SheetInfo[];
  cabang_list: string[];
  profil_list: string[];
}

/* ===================================================================
   HELPERS
   =================================================================== */
function formatRupiah(val: any): string {
  if (val == null || val === "") return "-";
  const num = typeof val === "string" ? parseFloat(val) : val;
  if (isNaN(num)) return String(val);
  return "Rp " + num.toLocaleString("id-ID");
}

function formatCell(val: any, type: string): string {
  if (val == null || val === "") return "-";
  if (type === "currency") return formatRupiah(val);
  if (type === "number") {
    const num = typeof val === "string" ? parseFloat(val) : val;
    if (isNaN(num)) return String(val);
    return num.toLocaleString("id-ID");
  }
  return String(val);
}

function exportSheetCSV(sheet: SheetInfo) {
  const { headers, rows } = sheet.data;
  const csvRows = [headers.join(",")];
  for (const row of rows) {
    csvRows.push(
      headers
        .map((h) => {
          const v = row[h];
          if (v == null) return "";
          const s = String(v);
          return s.includes(",") || s.includes('"') || s.includes("\n")
            ? `"${s.replace(/"/g, '""')}"`
            : s;
        })
        .join(",")
    );
  }
  const blob = new Blob(["\uFEFF" + csvRows.join("\n")], {
    type: "text/csv;charset=utf-8;",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${sheet.title}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/* ===================================================================
   ICONS (Clean inline SVG)
   =================================================================== */
const IconDownload = () => (
  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
    <polyline points="7 10 12 15 17 10" />
    <line x1="12" x2="12" y1="15" y2="3" />
  </svg>
);

const IconCSV = () => (
  <svg className="w-4 h-4 text-emerald-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <line x1="8" y1="13" x2="16" y2="13" />
    <line x1="8" y1="17" x2="16" y2="17" />
  </svg>
);

const IconSearch = () => (
  <svg className="w-4 h-4 text-slate-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="11" cy="11" r="8" />
    <line x1="21" x2="16.65" y1="21" y2="16.65" />
  </svg>
);

const IconReset = () => (
  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
    <path d="M3 3v5h5" />
  </svg>
);

const IconClose = () => (
  <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" x2="6" y1="6" y2="18" />
    <line x1="6" x2="18" y1="6" y2="18" />
  </svg>
);

const IconExcel = () => (
  <svg className="w-4 h-4 text-emerald-600 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
    <polyline points="14 2 14 8 20 8" />
    <path d="M8 13l2 3-2 3" />
    <path d="M12 13l-2 3 2 3" />
    <line x1="15" y1="13" x2="17" y2="13" />
    <line x1="15" y1="16" x2="17" y2="16" />
    <line x1="15" y1="19" x2="17" y2="19" />
  </svg>
);

const IconInfo = () => (
  <svg className="w-4 h-4 text-indigo-600 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" />
    <line x1="12" y1="16" x2="12" y2="12" />
    <line x1="12" y1="8" x2="12.01" y2="8" />
  </svg>
);

const IconChevronDown = ({ open }: { open?: boolean }) => (
  <svg
    className={`w-4 h-4 transition-transform duration-200 ${open ? "rotate-180" : ""}`}
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <polyline points="6 9 12 15 18 9" />
  </svg>
);

const SAMPLE_PREVIEW_ROWS = [
  { cabang: "BLOK C", nama: "Budi Hartono", id_mesin: "1", timestamp: "02/03/2026 07:54:12", tipe: "C/Masuk", gerbang: "1", kosong: "-", metode: "Finger" },
  { cabang: "BLOK C", nama: "Budi Hartono", id_mesin: "1", timestamp: "02/03/2026 16:05:30", tipe: "C/Keluar", gerbang: "1", kosong: "-", metode: "Finger" },
  { cabang: "BLOK C", nama: "Andi Santanu", id_mesin: "1", timestamp: "02/03/2026 07:58:00", tipe: "C/Masuk", gerbang: "1", kosong: "-", metode: "Finger" },
  { cabang: "BLOK C", nama: "Andi Santanu", id_mesin: "1", timestamp: "02/03/2026 18:35:10", tipe: "C/Keluar", gerbang: "1", kosong: "-", metode: "Finger" },
  { cabang: "BLOK C", nama: "Dian Maulana", id_mesin: "1", timestamp: "02/03/2026 08:22:15", tipe: "C/Masuk", gerbang: "1", kosong: "-", metode: "Finger" },
  { cabang: "BLOK C", nama: "Dian Maulana", id_mesin: "1", timestamp: "02/03/2026 16:01:05", tipe: "C/Keluar", gerbang: "1", kosong: "-", metode: "Finger" },
];

/* ===================================================================
   KPI METRIC CARD
   =================================================================== */
function KpiCard({
  label,
  value,
  accent,
  isAlert,
}: {
  label: string;
  value: string | number;
  accent?: "indigo" | "rose" | "emerald" | "amber" | "slate";
  isAlert?: boolean;
}) {
  const accentBorder = {
    indigo: "border-t-indigo-500 text-indigo-600",
    rose: "border-t-rose-500 text-rose-600",
    emerald: "border-t-emerald-500 text-emerald-600",
    amber: "border-t-amber-500 text-amber-600",
    slate: "border-t-slate-300 text-slate-800",
  }[accent || "slate"];

  return (
    <div
      className={`bg-white rounded-xl border border-slate-200/80 p-3.5 shadow-xs border-t-[3px] flex flex-col justify-between transition-shadow hover:shadow-sm ${accentBorder}`}
    >
      <span className="text-xs font-medium text-slate-500">
        {label}
      </span>
      <div className="mt-1 flex items-baseline justify-between">
        <span
          className={`text-lg font-bold tracking-tight tabular ${
            isAlert ? "text-rose-600" : "text-slate-900"
          }`}
        >
          {typeof value === "number" ? value.toLocaleString("id-ID") : value}
        </span>
      </div>
    </div>
  );
}

/* ===================================================================
   EMPLOYEE DETAIL MODAL (Drilldown)
   =================================================================== */
function EmployeeModal({
  nama,
  sheets,
  onClose,
}: {
  nama: string;
  sheets: SheetInfo[];
  onClose: () => void;
}) {
  const getSheet = (key: string) => sheets.find((s) => s.key === key);

  const summarySheet = getSheet("summary");
  const summaryRow = summarySheet?.data.rows.find((r) => r["Nama"] === nama);

  const filterByNama = (key: string) => {
    const sheet = getSheet(key);
    if (!sheet) return { headers: [] as string[], rows: [] as any[] };
    return {
      headers: sheet.data.headers,
      rows: sheet.data.rows.filter((r) => r["Nama"] === nama),
      types: sheet.data.types,
    };
  };

  const sections = [
    { title: "Rekap Telat", key: "telat" },
    { title: "Rekap Lembur", key: "lembur" },
    { title: "Rekap Pulang Duluan", key: "pulang_duluan" },
    { title: "Uang Makan", key: "uang_makan" },
    { title: "Rekap Tidak Masuk", key: "tidak_masuk" },
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 backdrop-blur-xs p-4 sm:p-6"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-xl w-full max-w-5xl overflow-hidden flex flex-col border border-slate-200/90 max-h-[92vh] animate-in fade-in zoom-in-95 duration-150"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header Modal */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 bg-slate-50/70">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-indigo-600 text-white font-bold flex items-center justify-center text-sm shadow-xs">
              {nama.slice(0, 2).toUpperCase()}
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900">{nama}</h2>
              {summaryRow && (
                <p className="text-xs text-slate-500 font-medium mt-0.5">
                  Cabang: <span className="text-slate-800 font-semibold">{summaryRow["Cabang"]}</span> · Profil:{" "}
                  <span className="text-slate-800 font-semibold">{summaryRow["Profil"] || "STANDAR"}</span>
                </p>
              )}
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors cursor-pointer"
            aria-label="Tutup"
          >
            <IconClose />
          </button>
        </div>

        {/* Quick Summary KPIs */}
        {summaryRow && (
          <div className="px-6 py-3.5 border-b border-slate-100 bg-slate-50/30 flex flex-wrap gap-2.5">
            <div className="bg-white px-3.5 py-1.5 rounded-lg border border-slate-200 text-xs">
              <span className="text-slate-500 font-medium">Hari Kerja: </span>
              <span className="font-bold text-slate-900">{summaryRow["Hari Kerja Valid"] ?? 0}</span>
            </div>
            <div className="bg-white px-3.5 py-1.5 rounded-lg border border-slate-200 text-xs">
              <span className="text-slate-500 font-medium">Jml Telat: </span>
              <span className={`font-bold ${summaryRow["Jml Telat"] > 0 ? "text-rose-600" : "text-slate-900"}`}>
                {summaryRow["Jml Telat"] ?? 0}
              </span>
            </div>
            <div className="bg-white px-3.5 py-1.5 rounded-lg border border-slate-200 text-xs">
              <span className="text-slate-500 font-medium">Jam Lembur (Bulat): </span>
              <span className="font-bold text-indigo-600">
                {summaryRow["Jam Lembur (Bulat)"] != null ? `${summaryRow["Jam Lembur (Bulat)"]} jam` : 0}
              </span>
            </div>
            <div className="bg-white px-3.5 py-1.5 rounded-lg border border-slate-200 text-xs">
              <span className="text-slate-500 font-medium">Bonus Lembur: </span>
              <span className="font-bold text-indigo-600">{formatRupiah(summaryRow["Total Bonus Lembur (Rp)"])}</span>
            </div>
            <div className="bg-white px-3.5 py-1.5 rounded-lg border border-slate-200 text-xs">
              <span className="text-slate-500 font-medium">Uang Makan Akhir: </span>
              <span className="font-bold text-emerald-600">{formatRupiah(summaryRow["Total Uang Makan Akhir (Rp)"])}</span>
            </div>
          </div>
        )}

        {/* Detail Sections */}
        <div className="overflow-y-auto flex-1 px-6 py-5 space-y-6">
          {sections.map((sec) => {
            const d = filterByNama(sec.key);
            const sheet = getSheet(sec.key);
            return (
              <div key={sec.key}>
                <div className="flex items-center gap-2 mb-2">
                  <h3 className="text-xs font-semibold text-slate-800">
                    {sec.title}
                  </h3>
                  <span className="text-[11px] font-medium px-2 py-0.5 rounded-md bg-slate-100 text-slate-600">
                    {d.rows.length} catatan
                  </span>
                </div>
                {d.rows.length === 0 ? (
                  <p className="text-xs text-slate-400 italic bg-slate-50/60 p-2.5 rounded-lg border border-slate-100">
                    Tidak ada catatan kejadian pada periode ini.
                  </p>
                ) : (
                  <div className="overflow-x-auto rounded-lg border border-slate-200 shadow-xs">
                    <table className="w-full text-xs">
                      <thead>
                        <tr className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold text-slate-600">
                          {d.headers
                            .filter((h) => h !== "Nama" && !h.startsWith("_"))
                            .map((h) => (
                              <th key={h} className="px-3 py-2 text-left whitespace-nowrap">
                                {h}
                              </th>
                            ))}
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-slate-100">
                        {d.rows.map((row, ri) => (
                          <tr key={ri} className="hover:bg-slate-50/80 transition-colors">
                            {d.headers
                              .filter((h) => h !== "Nama" && !h.startsWith("_"))
                              .map((h) => (
                                <td key={h} className="px-3 py-1.5 whitespace-nowrap tabular text-slate-700">
                                  {formatCell(row[h], sheet?.data.types?.[h] || "text")}
                                </td>
                              ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

/* ===================================================================
   SHEET TABLE COMPONENT (Compact & Data-Dense)
   =================================================================== */
const PAGE_OPTIONS = [25, 50, 100, -1] as const;

function SheetTable({
  sheet,
  search,
  cabangFilter,
  profilFilter,
  onClickNama,
}: {
  sheet: SheetInfo;
  search: string;
  cabangFilter: string;
  profilFilter: string;
  onClickNama?: (nama: string) => void;
}) {
  const [page, setPage] = useState(0);
  const [pageSize, setPageSize] = useState<number>(25);
  const [sortCol, setSortCol] = useState<string | null>(null);
  const [sortAsc, setSortAsc] = useState(true);

  const { headers, rows, types } = sheet.data;

  // Filter rows
  const filteredRows = useMemo(() => {
    let out = rows;
    const s = search.toLowerCase().trim();
    if (s) {
      out = out.filter((r) =>
        headers.some((h) => {
          const v = r[h];
          return v != null && String(v).toLowerCase().includes(s);
        })
      );
    }
    if (cabangFilter && headers.includes("Cabang")) {
      out = out.filter((r) => r["Cabang"] === cabangFilter);
    }
    if (profilFilter && headers.includes("Profil")) {
      out = out.filter((r) => r["Profil"] === profilFilter);
    }
    return out;
  }, [rows, headers, search, cabangFilter, profilFilter]);

  // Sort rows
  const sortedRows = useMemo(() => {
    if (!sortCol) return filteredRows;
    const colType = types[sortCol] || "text";
    return [...filteredRows].sort((a, b) => {
      const va = a[sortCol];
      const vb = b[sortCol];
      if (va == null && vb == null) return 0;
      if (va == null) return 1;
      if (vb == null) return -1;
      let cmp = 0;
      if (colType === "number" || colType === "currency") {
        cmp = Number(va) - Number(vb);
      } else {
        cmp = String(va).localeCompare(String(vb), "id");
      }
      return sortAsc ? cmp : -cmp;
    });
  }, [filteredRows, sortCol, sortAsc, types]);

  // Pagination
  const totalRows = sortedRows.length;
  const effectivePageSize = pageSize === -1 ? totalRows || 1 : pageSize;
  const totalPages = Math.ceil(totalRows / effectivePageSize) || 1;
  const pagedRows = useMemo(() => {
    if (pageSize === -1) return sortedRows;
    const start = page * pageSize;
    return sortedRows.slice(start, start + pageSize);
  }, [sortedRows, page, pageSize]);

  function handleSort(col: string) {
    if (sortCol === col) {
      if (sortAsc) setSortAsc(false);
      else {
        setSortCol(null);
        setSortAsc(true);
      }
    } else {
      setSortCol(col);
      setSortAsc(true);
    }
    setPage(0);
  }

  const visibleHeaders = headers.filter((h) => !h.startsWith("_"));

  if (visibleHeaders.length === 0) {
    return (
      <div className="p-8 text-center text-xs text-slate-400">
        Tidak ada kolom untuk ditampilkan pada sheet ini.
      </div>
    );
  }

  return (
    <div>
      <div className="overflow-x-auto border border-slate-200/90 rounded-lg shadow-2xs max-h-[640px] overflow-y-auto">
        <table className="w-full text-xs text-left border-collapse">
          <thead className="sticky top-0 z-10 bg-slate-100/90 backdrop-blur-xs border-b border-slate-200">
            <tr>
              {visibleHeaders.map((h) => {
                const isSorted = sortCol === h;
                const isNumeric = types[h] === "number" || types[h] === "currency";
                return (
                  <th
                    key={h}
                    onClick={() => handleSort(h)}
                    className={`px-3 py-2.5 font-bold uppercase tracking-wider text-[11px] text-slate-700 whitespace-nowrap cursor-pointer select-none hover:bg-slate-200/60 transition-colors ${
                      isNumeric ? "text-right" : "text-left"
                    }`}
                  >
                    <div className={`inline-flex items-center gap-1 ${isNumeric ? "justify-end" : "justify-start"}`}>
                      <span>{h}</span>
                      <span className="text-[10px] text-slate-400">
                        {isSorted ? (sortAsc ? "▲" : "▼") : "⇅"}
                      </span>
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pagedRows.length === 0 ? (
              <tr>
                <td
                  colSpan={visibleHeaders.length}
                  className="px-4 py-8 text-center text-xs text-slate-400 italic"
                >
                  Tidak ada baris yang sesuai kriteria pencarian atau filter.
                </td>
              </tr>
            ) : (
              pagedRows.map((row, ri) => {
                const isHighlight = row["_highlight"] === true;
                return (
                  <tr
                    key={ri}
                    className={`transition-colors h-8 ${
                      isHighlight
                        ? "bg-amber-50 hover:bg-amber-100/80"
                        : ri % 2 === 1
                        ? "bg-slate-50/40 hover:bg-indigo-50/30"
                        : "bg-white hover:bg-indigo-50/30"
                    }`}
                  >
                    {visibleHeaders.map((h) => {
                      const isNama = h === "Nama" && onClickNama;
                      const isNumeric = types[h] === "number" || types[h] === "currency";
                      return (
                        <td
                          key={h}
                          className={`px-3 py-1.5 whitespace-nowrap tabular text-slate-700 ${
                            isNumeric ? "text-right" : "text-left"
                          } ${isNama ? "font-semibold text-indigo-600 hover:text-indigo-800 hover:underline cursor-pointer" : ""}`}
                          onClick={isNama ? () => onClickNama!(row["Nama"]) : undefined}
                        >
                          {formatCell(row[h], types[h] || "text")}
                        </td>
                      );
                    })}
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination Footer */}
      <div className="flex items-center justify-between mt-3 text-xs text-slate-500 font-medium px-1 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span>
            {totalRows > 0
              ? `${page * effectivePageSize + 1}–${Math.min((page + 1) * effectivePageSize, totalRows)} dari ${totalRows.toLocaleString("id-ID")} baris`
              : "0 baris"}
          </span>
          {filteredRows.length !== rows.length && (
            <span className="text-indigo-600 font-semibold">(difilter dari {rows.length.toLocaleString("id-ID")})</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span>Per halaman:</span>
          {PAGE_OPTIONS.map((ps) => (
            <button
              key={ps}
              onClick={() => {
                setPageSize(ps);
                setPage(0);
              }}
              className={`px-2 py-0.5 rounded text-xs font-semibold transition-colors cursor-pointer ${
                pageSize === ps
                  ? "bg-indigo-600 text-white shadow-xs"
                  : "bg-white border border-slate-200 text-slate-600 hover:bg-slate-50"
              }`}
            >
              {ps === -1 ? "Semua" : ps}
            </button>
          ))}
          {totalPages > 1 && (
            <div className="flex items-center gap-1 ml-2">
              <button
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
                className="px-2 py-0.5 rounded border border-slate-200 bg-white text-slate-600 disabled:opacity-30 hover:bg-slate-50 cursor-pointer disabled:cursor-not-allowed"
              >
                ‹
              </button>
              <span className="px-1 text-slate-700 font-semibold">
                {page + 1} / {totalPages}
              </span>
              <button
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                disabled={page === totalPages - 1}
                className="px-2 py-0.5 rounded border border-slate-200 bg-white text-slate-600 disabled:opacity-30 hover:bg-slate-50 cursor-pointer disabled:cursor-not-allowed"
              >
                ›
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/* ===================================================================
   README PANEL
   =================================================================== */
function ReadmePanel({ sheet }: { sheet: SheetInfo }) {
  const catatan = sheet.data.catatan || [];
  const panduanSheets = [
    { num: "1", title: "Summary Overview", desc: "Ringkasan per karyawan, semua angka dihitung real-time." },
    { num: "2", title: "Rekap Telat", desc: "Setiap kejadian telat, durasi, patokan jam per profil." },
    { num: "3", title: "Rekap Lembur", desc: "Setiap kejadian lembur, jam lembur (bulat) & bonus Rp." },
    { num: "4", title: "Rekap Pulang Duluan", desc: "Jam keluar sebelum standar, durasi kurang." },
    { num: "5", title: "Rekap Tidak Masuk", desc: "Per minggu, karyawan hadir < kuota hari kerja." },
    { num: "6", title: "Data Tidak Lengkap", desc: "Hari cuma ada satu sisi scan." },
    { num: "7", title: "Uang Makan", desc: "Perhitungan harian: base, potongan, bonus tgl merah." },
    { num: "8", title: "Perbandingan Cabang", desc: "Agregasi per cabang." },
    { num: "9", title: "Rekap per Profil", desc: "Kehadiran profil non-logic-utama." },
    { num: "10", title: "Alpa Berulang", desc: "Minggu bermasalah ≥2x berturut-turut." },
    { num: "11", title: "Perlu Dicek", desc: "Nama tidak ditemukan di master." },
    { num: "12", title: "Preprocessing", desc: "Data harian setelah agregasi & koreksi." },
    { num: "13", title: "Data Mentah", desc: "Log scan asli, untuk audit." },
  ];

  return (
    <div className="space-y-6 max-w-4xl py-2">
      <div>
        <h3 className="text-base font-bold text-slate-900 mb-2">
          Panduan Membaca Laporan Absensi HR
        </h3>
        <p className="text-xs text-slate-500 mb-4 leading-relaxed">
          Laporan ini berisi 14 sheet yang tersusun otomatis dari proses pipeline absensi karyawan.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {panduanSheets.map((ps) => (
            <div
              key={ps.num}
              className="flex gap-2.5 text-xs p-3 rounded-lg border border-slate-200/80 bg-slate-50/50"
            >
              <span className="font-semibold text-xs shrink-0 w-5 h-5 rounded-md flex items-center justify-center bg-slate-100 text-slate-700">
                {ps.num}
              </span>
              <div>
                <span className="font-semibold text-slate-800">{ps.title}</span>
                <p className="text-slate-500 mt-0.5 leading-snug">{ps.desc}</p>
              </div>
            </div>
          ))}
        </div>
      </div>

      {catatan.length > 0 && (
        <div className="p-4 rounded-xl border border-slate-200 bg-slate-50/50">
          <h4 className="text-xs font-semibold text-slate-900 mb-2">
            Catatan & Asumsi Kalkulasi
          </h4>
          <ul className="space-y-1.5">
            {catatan.map((c, i) => (
              <li key={i} className="text-xs text-slate-600 leading-relaxed flex items-start gap-2">
                <span className="text-indigo-500 font-bold shrink-0">•</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ===================================================================
   SIMPLE BAR CHART (Perbandingan Cabang)
   =================================================================== */
function SimpleBarChart({ sheet }: { sheet: SheetInfo }) {
  const { rows } = sheet.data;
  if (!rows || rows.length === 0) return null;

  const numericCols = sheet.data.headers.filter(
    (h) => h !== "Cabang" && sheet.data.types[h] === "number" && !h.includes("Durasi") && !h.includes("Karyawan")
  );
  if (numericCols.length === 0) return null;

  const maxVal = Math.max(
    1,
    ...rows.flatMap((r) => numericCols.map((c) => (typeof r[c] === "number" ? r[c] : 0)))
  );

  const barColors = ["#e11d48", "#4f46e5", "#d97706", "#059669"];

  return (
    <div className="mt-6 p-5 rounded-xl border border-slate-200 bg-slate-50/60">
      <h4 className="text-xs font-semibold text-slate-800 mb-4">
        Visualisasi Perbandingan Antar Cabang
      </h4>
      <div className="space-y-3.5">
        {rows.map((row, ri) => (
          <div key={ri} className="flex items-center gap-3">
            <span className="text-xs w-28 truncate text-right font-semibold text-slate-800">
              {row["Cabang"]}
            </span>
            <div className="flex-1 flex gap-1.5 items-center">
              {numericCols.map((col, ci) => {
                const val = typeof row[col] === "number" ? row[col] : 0;
                const pct = (val / maxVal) * 100;
                return (
                  <div
                    key={col}
                    className="h-5 rounded-sm transition-all duration-500 flex items-center justify-end pr-1.5 shadow-2xs"
                    style={{
                      width: `${Math.max(pct, 2)}%`,
                      backgroundColor: barColors[ci % barColors.length],
                      minWidth: val > 0 ? "24px" : "4px",
                    }}
                  >
                    {val > 0 && (
                      <span className="text-[10px] font-bold text-white drop-shadow-xs">{val}</span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
      <div className="flex gap-4 mt-5 pt-3 border-t border-slate-200/80 flex-wrap">
        {numericCols.map((col, ci) => (
          <div key={col} className="flex items-center gap-1.5 text-xs text-slate-600 font-medium">
            <div
              className="w-2.5 h-2.5 rounded-sm shrink-0"
              style={{ backgroundColor: barColors[ci % barColors.length] }}
            />
            {col}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ===================================================================
   AI CHAT PANEL (Floating, bottom-right)
   =================================================================== */
type ChatMessage = { role: "user" | "model"; text: string };

const SUGGESTED_PROMPTS = [
  "Siapa karyawan yang paling sering telat?",
  "Berapa total uang makan keseluruhan?",
  "Siapa yang mendapat bonus lembur terbesar?",
  "Karyawan mana yang paling sering tidak masuk?",
];

function parseInlineFormatted(text: string): React.ReactNode[] {
  // Bersihkan asteris bertumpuk jika ada
  const cleaned = text.replace(/\*{3,}/g, "**");

  const parts: React.ReactNode[] = [];
  const regex = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  let lastIdx = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(cleaned)) !== null) {
    if (match.index > lastIdx) {
      parts.push(cleaned.substring(lastIdx, match.index));
    }
    const token = match[0];
    if (token.startsWith("**") && token.endsWith("**")) {
      parts.push(
        <strong key={match.index} className="font-semibold text-slate-900">
          {token.slice(2, -2)}
        </strong>
      );
    } else if (token.startsWith("*") && token.endsWith("*")) {
      parts.push(
        <em key={match.index} className="italic text-slate-700">
          {token.slice(1, -1)}
        </em>
      );
    } else if (token.startsWith("`") && token.endsWith("`")) {
      parts.push(
        <code key={match.index} className="px-1.5 py-0.5 rounded bg-indigo-50 font-mono text-[11px] text-indigo-700 font-medium border border-indigo-100">
          {token.slice(1, -1)}
        </code>
      );
    }
    lastIdx = regex.lastIndex;
  }
  if (lastIdx < cleaned.length) {
    parts.push(cleaned.substring(lastIdx));
  }
  return parts.length > 0 ? parts : [cleaned];
}

function FormattedMessage({ text }: { text: string }) {
  const lines = text.split("\n");
  const elements: React.ReactNode[] = [];

  lines.forEach((rawLine, idx) => {
    const line = rawLine.trim();

    if (!line) {
      elements.push(<div key={`sp-${idx}`} className="h-2" />);
      return;
    }

    if (line === "---" || line === "***" || line === "___") {
      elements.push(<hr key={`hr-${idx}`} className="my-2.5 border-slate-200" />);
      return;
    }

    // Headings: ### or ## or #
    if (line.startsWith("#")) {
      const headingText = line.replace(/^#+\s*/, "");
      elements.push(
        <div key={`h-${idx}`} className="font-bold text-[13px] text-indigo-950 mt-3 mb-1 pt-1 border-b border-indigo-100/70 pb-1 flex items-center gap-1.5">
          <span className="w-1.5 h-3.5 bg-indigo-600 rounded-full shrink-0" />
          <span>{parseInlineFormatted(headingText)}</span>
        </div>
      );
      return;
    }

    // Bullet points: * , - , •
    const bulletMatch = line.match(/^([*\-•])\s+(.*)/);
    if (bulletMatch) {
      elements.push(
        <div key={`b-${idx}`} className="flex items-start gap-2 py-0.5 pl-1 text-slate-700">
          <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 mt-1.5 shrink-0" />
          <div className="flex-1 leading-relaxed">{parseInlineFormatted(bulletMatch[2])}</div>
        </div>
      );
      return;
    }

    // Numbered list: 1. , 2. , or alphabetical a. , b.
    const numMatch = line.match(/^(\d+|[a-zA-Z])[\.\)]\s+(.*)/);
    if (numMatch) {
      elements.push(
        <div key={`n-${idx}`} className="flex items-start gap-2 py-0.5 pl-1 text-slate-700">
          <span className="min-w-[18px] h-[18px] rounded-md bg-indigo-50 text-indigo-700 text-[10px] font-bold flex items-center justify-center shrink-0 mt-0.5 border border-indigo-200/70">
            {numMatch[1]}
          </span>
          <div className="flex-1 leading-relaxed">{parseInlineFormatted(numMatch[2])}</div>
        </div>
      );
      return;
    }

    // Regular paragraph
    elements.push(
      <p key={`p-${idx}`} className="leading-relaxed text-slate-700 py-0.5">
        {parseInlineFormatted(line)}
      </p>
    );
  });

  return <div className="space-y-0.5 text-xs text-slate-800">{elements}</div>;
}

function AIChatPanel({ fileId }: { fileId: string }) {
  const [open, setOpen] = useState(false);
  const [isExpanded, setIsExpanded] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [chatError, setChatError] = useState<string | null>(null);
  const [copiedIdx, setCopiedIdx] = useState<number | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (open) {
      setTimeout(() => inputRef.current?.focus(), 120);
    }
  }, [open]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  async function sendMessage(text: string) {
    if (!text.trim() || loading) return;
    const userMsg: ChatMessage = { role: "user", text: text.trim() };
    const newHistory = [...messages, userMsg];
    setMessages(newHistory);
    setInput("");
    setLoading(true);
    setChatError(null);
    try {
      const reply = await api.chatWithAI(fileId, text.trim(), messages);
      setMessages([...newHistory, { role: "model", text: reply }]);
    } catch (err: any) {
      setChatError(err.message || "Gagal menghubungi AI. Coba lagi.");
    } finally {
      setLoading(false);
    }
  }

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(input);
    }
  }

  async function handleCopy(text: string, index: number) {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIdx(index);
      setTimeout(() => setCopiedIdx(null), 2000);
    } catch {
      // fallback
    }
  }

  const hasMessages = messages.length > 0;

  return (
    <>
      {/* Floating Button */}
      {!open && (
        <button
          id="ai-chat-fab"
          onClick={() => setOpen(true)}
          className="fixed bottom-6 right-6 z-50 flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-indigo-600 text-white text-xs font-semibold shadow-md hover:bg-indigo-700 transition-colors cursor-pointer"
          title="Tanya asisten tentang data absensi ini"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          </svg>
          <span>Tanya Asisten</span>
        </button>
      )}

      {/* Chat Panel */}
      {open && (
        <div
          id="ai-chat-panel"
          className={`fixed bottom-6 right-6 z-50 flex flex-col transition-all duration-150 rounded-xl shadow-xl border border-slate-200 bg-white overflow-hidden ${
            isExpanded
              ? "w-[92vw] sm:w-[620px] max-h-[720px] h-[85vh]"
              : "w-[92vw] sm:w-[440px] max-h-[600px] h-[580px]"
          }`}
        >
          {/* Header */}
          <div className="flex items-center gap-3 px-4 py-3 bg-slate-900 text-white shrink-0 border-b border-slate-800">
            <div className="w-7 h-7 rounded-lg bg-indigo-600 text-white flex items-center justify-center shrink-0">
              <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-xs font-bold leading-tight">Analisis Absensi AI</p>
              <p className="text-[11px] text-slate-400 leading-tight">Gemma 4 · Google AI</p>
            </div>
            <div className="flex items-center gap-1">
              {hasMessages && (
                <button
                  onClick={() => { setMessages([]); setChatError(null); }}
                  className="text-slate-400 hover:text-white text-[11px] font-medium px-2 py-1 rounded hover:bg-slate-800 transition-colors cursor-pointer mr-1"
                  title="Hapus riwayat chat"
                >
                  Hapus
                </button>
              )}
              {/* Expand / Minimize Toggle */}
              <button
                onClick={() => setIsExpanded(!isExpanded)}
                className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors cursor-pointer shrink-0"
                title={isExpanded ? "Perkecil panel" : "Perbesar panel"}
                aria-label={isExpanded ? "Perkecil panel" : "Perbesar panel"}
              >
                {isExpanded ? (
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="4 14 10 14 10 20" />
                    <polyline points="20 10 14 10 14 4" />
                    <line x1="14" y1="10" x2="21" y2="3" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                ) : (
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <polyline points="15 3 21 3 21 9" />
                    <polyline points="9 21 3 21 3 15" />
                    <line x1="21" y1="3" x2="14" y2="10" />
                    <line x1="3" y1="21" x2="10" y2="14" />
                  </svg>
                )}
              </button>
              {/* Close Button */}
              <button
                onClick={() => setOpen(false)}
                className="p-1.5 rounded hover:bg-slate-800 text-slate-400 hover:text-white transition-colors cursor-pointer shrink-0"
                aria-label="Tutup chat"
              >
                <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="18" x2="6" y1="6" y2="18" />
                  <line x1="6" x2="18" y1="6" y2="18" />
                </svg>
              </button>
            </div>
          </div>

          {/* Messages Area */}
          <div className="flex-1 overflow-y-auto px-4 py-3.5 space-y-3 min-h-0 bg-slate-50/70">
            {!hasMessages && (
              <div className="space-y-3 pt-1">
                <div className="p-3 rounded-lg bg-white border border-slate-200 text-center">
                  <p className="text-xs font-semibold text-slate-800 mb-0.5">Asisten Analisis Absensi</p>
                  <p className="text-[11px] text-slate-500">
                    Ketik pertanyaan tentang rincian keterlambatan, lembur, uang makan, atau jam kerja cabang.
                  </p>
                </div>
                <div className="space-y-1.5">
                  {SUGGESTED_PROMPTS.map((p, i) => (
                    <button
                      key={i}
                      onClick={() => sendMessage(p)}
                      disabled={loading}
                      className="w-full text-left text-xs px-3 py-2 rounded-lg border border-slate-200 bg-white text-slate-700 font-medium hover:border-slate-300 hover:bg-slate-50 transition-colors cursor-pointer disabled:opacity-50 flex items-center justify-between"
                    >
                      <span>{p}</span>
                      <span className="text-slate-400">→</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                <div
                  className={`rounded-xl text-xs ${
                    msg.role === "user"
                      ? "max-w-[85%] bg-indigo-600 text-white px-3.5 py-2.5 shadow-xs"
                      : "w-full max-w-[94%] bg-white text-slate-800 border border-slate-200 shadow-xs p-3.5"
                  }`}
                >
                  {msg.role === "user" ? (
                    <div className="whitespace-pre-wrap leading-relaxed">{msg.text}</div>
                  ) : (
                    <div>
                      {/* Sub-header inside AI card with Copy button */}
                      <div className="flex items-center justify-between pb-2 mb-2 border-b border-slate-100 text-[11px] text-slate-400">
                        <span className="font-medium text-slate-600">
                          Analisis
                        </span>
                        <button
                          onClick={() => handleCopy(msg.text, i)}
                          className="flex items-center gap-1 text-[11px] text-slate-500 hover:text-slate-800 px-2 py-0.5 rounded hover:bg-slate-100 transition-colors cursor-pointer"
                          title="Salin jawaban ini"
                        >
                          {copiedIdx === i ? (
                            <span className="text-emerald-600 font-medium">
                              Tersalin ✓
                            </span>
                          ) : (
                            <>
                              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                                <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                              </svg>
                              <span>Salin</span>
                            </>
                          )}
                        </button>
                      </div>
                      <FormattedMessage text={msg.text} />
                    </div>
                  )}
                </div>
              </div>
            ))}

            {/* Loading indicator */}
            {loading && (
              <div className="flex justify-start">
                <div className="bg-white border border-slate-200 rounded-xl px-3.5 py-2.5 shadow-xs flex items-center gap-2">
                  <span className="inline-block w-3.5 h-3.5 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
                  <span className="text-[11px] text-slate-500 font-medium">Menganalisis data...</span>
                </div>
              </div>
            )}

            {chatError && (
              <div className="text-xs text-rose-700 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
                {chatError}
              </div>
            )}

            <div ref={bottomRef} />
          </div>

          {/* Input Area */}
          <div className="px-3.5 py-3 border-t border-slate-200 bg-white shrink-0">
            <div className="flex items-center gap-2">
              <input
                ref={inputRef}
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={handleKey}
                disabled={loading}
                placeholder="Ketik pertanyaan atau nama karyawan..."
                className="flex-1 text-xs px-3.5 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-indigo-500 focus:bg-white disabled:opacity-60 transition-colors"
              />
              <button
                onClick={() => sendMessage(input)}
                disabled={!input.trim() || loading}
                className="w-8 h-8 rounded-lg bg-indigo-600 text-white flex items-center justify-center hover:bg-indigo-700 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer shrink-0"
                aria-label="Kirim pesan"
              >
                <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <line x1="22" y1="2" x2="11" y2="13" />
                  <polygon points="22 2 15 22 11 13 2 9 22 2" />
                </svg>
              </button>
            </div>
          </div>
        </div>
      )}

    </>
  );
}



export default function ProsesPage() {
  const [files, setFiles] = useState<File[]>([]);
  const [processing, setProcessing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ProcessResult | null>(null);
  const [activeTab, setActiveTab] = useState(0);
  const [search, setSearch] = useState("");
  const [cabangFilter, setCabangFilter] = useState("");
  const [profilFilter, setProfilFilter] = useState("");
  const [downloading, setDownloading] = useState(false);
  const [detailNama, setDetailNama] = useState<string | null>(null);
  const [downloadingTemplate, setDownloadingTemplate] = useState<"xlsx" | "csv" | null>(null);
  const [showTemplateGuide, setShowTemplateGuide] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function handleFiles(list: FileList | null) {
    if (!list) return;
    setFiles(Array.from(list));
    setError(null);
  }

  async function handleProcess() {
    if (files.length === 0) return;
    setProcessing(true);
    setError(null);
    setResult(null);
    try {
      const data = await api.prosesAbsensi(files);
      setResult(data);
      setActiveTab(0);
    } catch (err: any) {
      setError(err.message || "Gagal memproses data absensi.");
    } finally {
      setProcessing(false);
    }
  }

  async function handleDownloadExcel() {
    if (!result) return;
    setDownloading(true);
    try {
      await api.downloadProcessedExcel(result.file_id, result.filename);
    } catch (err: any) {
      setError(err.message || "Gagal mengunduh file.");
    } finally {
      setDownloading(false);
    }
  }

  function handleReset() {
    setResult(null);
    setFiles([]);
    setSearch("");
    setCabangFilter("");
    setProfilFilter("");
    setActiveTab(0);
  }

  const handleClickNama = useCallback((nama: string) => {
    setDetailNama(nama);
  }, []);

  async function handleDownloadTemplate(format: "xlsx" | "csv") {
    setDownloadingTemplate(format);
    setError(null);
    try {
      const blob = await api.downloadAttendanceTemplate(format);
      triggerBlobDownload(
        blob,
        format === "xlsx" ? "template_absensi_mentah.xlsx" : "template_absensi_mentah.csv"
      );
    } catch (err: any) {
      setError("Gagal mengunduh template: " + (err.message || String(err)));
    } finally {
      setDownloadingTemplate(null);
    }
  }

  // ============== UPLOAD MODE ==============
  if (!result) {
    return (
      <div className="max-w-4xl mx-auto space-y-6">
        <PageHeader
          title="Proses Data Absensi"
          description="Unggah satu atau lebih file log mesin absensi mentah. Sistem akan memproses dan menyajikan 14 sheet hasil secara interaktif."
          action={
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                onClick={() => handleDownloadTemplate("xlsx")}
                disabled={downloadingTemplate !== null}
              >
                <span className="flex items-center gap-1.5">
                  <IconExcel />
                  {downloadingTemplate === "xlsx" ? "Mengunduh..." : "Unduh Template (.xlsx)"}
                </span>
              </Button>
            </div>
          }
        />

        {error && <Banner kind="error">{error}</Banner>}

        <Card className="max-w-3xl mx-auto">
          <div
            onClick={() => inputRef.current?.click()}
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              handleFiles(e.dataTransfer.files);
            }}
            className="border-2 border-dashed border-slate-300 hover:border-indigo-500 rounded-xl p-10 text-center cursor-pointer transition-all duration-200 hover:bg-indigo-50/20 group"
          >
            <input
              ref={inputRef}
              type="file"
              multiple
              accept=".xlsx,.xls,.csv"
              className="hidden"
              onChange={(e) => handleFiles(e.target.files)}
            />
            <div className="inline-flex items-center justify-center w-14 h-14 rounded-2xl bg-indigo-50 group-hover:bg-indigo-100 text-indigo-600 mb-3.5 transition-colors">
              <svg className="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" x2="12" y1="3" y2="15" />
              </svg>
            </div>
            <p className="text-sm font-semibold text-slate-800">
              Pilih file absensi atau seret ke area ini
            </p>
            <p className="text-xs mt-1 text-slate-500">
              Mendukung format <span className="font-semibold text-slate-700">.xlsx, .xls, .csv</span> · Dapat memilih beberapa file sekaligus
            </p>
          </div>

          {files.length > 0 && (
            <div className="mt-5 space-y-2">
              <div className="text-xs font-semibold text-slate-700">
                File Siap Diproses ({files.length}):
              </div>
              <ul className="space-y-1.5 max-h-48 overflow-y-auto">
                {files.map((f, i) => (
                  <li
                    key={i}
                    className="flex justify-between items-center px-3.5 py-2 rounded-lg text-xs bg-slate-50 border border-slate-200/80"
                  >
                    <div className="flex items-center gap-2 truncate">
                      <svg className="w-4 h-4 text-indigo-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <polyline points="14 2 14 8 20 8" />
                      </svg>
                      <span className="font-medium text-slate-800 truncate">{f.name}</span>
                    </div>
                    <span className="text-[11px] font-semibold text-slate-400 tabular shrink-0 ml-3">
                      {(f.size / 1024).toFixed(0)} KB
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex items-center justify-between mt-6 pt-4 border-t border-slate-100">
            {files.length > 0 ? (
              <button
                type="button"
                onClick={() => setFiles([])}
                className="text-xs font-semibold text-rose-600 hover:text-rose-700 cursor-pointer"
              >
                Hapus Semua File
              </button>
            ) : <div />}
            <Button onClick={handleProcess} disabled={files.length === 0 || processing}>
              {processing ? (
                <span className="flex items-center gap-2">
                  <span className="inline-block w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Memproses Pipeline...
                </span>
              ) : (
                "Proses Absensi Sekarang"
              )}
            </Button>
          </div>
        </Card>

        {/* Template & Contoh Format File Card */}
        <Card className="max-w-3xl mx-auto border border-slate-200/90 shadow-2xs">
          <div className="flex items-start justify-between gap-4 flex-wrap pb-3.5 border-b border-slate-100">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 rounded-lg bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shrink-0 mt-0.5">
                <IconExcel />
              </div>
              <div>
                <h3 className="text-sm font-bold text-slate-900">
                  Contoh & Template File Log Absensi
                </h3>
                <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">
                  Gunakan template acuan 8 kolom ini untuk memastikan data log scan mesin absensi Anda terproses tanpa kendala.
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => handleDownloadTemplate("xlsx")}
                disabled={downloadingTemplate !== null}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold shadow-2xs transition-colors cursor-pointer disabled:opacity-60"
                title="Unduh template Excel dengan 2 sheet (Log Absensi & Panduan Kolom)"
              >
                <IconExcel />
                <span>{downloadingTemplate === "xlsx" ? "Mengunduh..." : "Template Excel (.xlsx)"}</span>
              </button>
              <button
                type="button"
                onClick={() => handleDownloadTemplate("csv")}
                disabled={downloadingTemplate !== null}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 text-xs font-semibold shadow-2xs transition-colors cursor-pointer disabled:opacity-60"
                title="Unduh contoh data format CSV"
              >
                <IconCSV />
                <span>{downloadingTemplate === "csv" ? "Mengunduh..." : "Contoh CSV (.csv)"}</span>
              </button>
            </div>
          </div>

          {/* Toggle Button for Preview */}
          <div className="pt-3.5">
            <button
              type="button"
              onClick={() => setShowTemplateGuide(!showTemplateGuide)}
              className="flex items-center justify-between w-full py-1 text-xs font-semibold text-slate-700 hover:text-indigo-600 cursor-pointer select-none transition-colors"
            >
              <span className="flex items-center gap-2">
                <IconInfo />
                <span>{showTemplateGuide ? "Sembunyikan Contoh & Spesifikasi 8 Kolom" : "Lihat Contoh Data & Spesifikasi 8 Kolom Absensi"}</span>
              </span>
              <IconChevronDown open={showTemplateGuide} />
            </button>

            {showTemplateGuide && (
              <div className="mt-3.5 space-y-4 animate-in fade-in duration-150">
                {/* Tabel Contoh Data */}
                <div className="overflow-x-auto border border-slate-200 rounded-lg">
                  <table className="w-full text-xs text-left border-collapse">
                    <thead>
                      <tr className="bg-slate-100/90 border-b border-slate-200 text-[11px] font-bold text-slate-700 uppercase tracking-wider">
                        <th className="px-3 py-2 whitespace-nowrap">Cabang</th>
                        <th className="px-3 py-2 whitespace-nowrap">Nama</th>
                        <th className="px-3 py-2 whitespace-nowrap text-center">ID_Mesin</th>
                        <th className="px-3 py-2 whitespace-nowrap text-center">Timestamp_Raw</th>
                        <th className="px-3 py-2 whitespace-nowrap text-center">Tipe_Asli_Raw</th>
                        <th className="px-3 py-2 whitespace-nowrap text-center">Kode_Gerbang</th>
                        <th className="px-3 py-2 whitespace-nowrap text-center">Kolom_Kosong</th>
                        <th className="px-3 py-2 whitespace-nowrap">Metode</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 font-mono text-[11px]">
                      {SAMPLE_PREVIEW_ROWS.map((r, i) => (
                        <tr key={i} className={i % 2 === 1 ? "bg-slate-50/50" : "bg-white"}>
                          <td className="px-3 py-1.5 whitespace-nowrap font-sans font-semibold text-slate-800">{r.cabang}</td>
                          <td className="px-3 py-1.5 whitespace-nowrap font-sans text-slate-900">{r.nama}</td>
                          <td className="px-3 py-1.5 whitespace-nowrap text-center text-slate-600">{r.id_mesin}</td>
                          <td className="px-3 py-1.5 whitespace-nowrap text-center text-indigo-600 font-semibold">{r.timestamp}</td>
                          <td className="px-3 py-1.5 whitespace-nowrap text-center font-sans font-semibold">
                            <span className={`px-2 py-0.5 rounded text-[10px] ${r.tipe === "C/Masuk" ? "bg-emerald-50 text-emerald-700 border border-emerald-200" : "bg-blue-50 text-blue-700 border border-blue-200"}`}>
                              {r.tipe}
                            </span>
                          </td>
                          <td className="px-3 py-1.5 whitespace-nowrap text-center text-slate-500">{r.gerbang}</td>
                          <td className="px-3 py-1.5 whitespace-nowrap text-center text-slate-400">{r.kosong}</td>
                          <td className="px-3 py-1.5 whitespace-nowrap font-sans text-slate-600">{r.metode}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* 4 Panduan Penting */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2.5 pt-1 text-xs">
                  <div className="p-3 rounded-lg border border-slate-200/90 bg-slate-50/50">
                    <span className="font-bold text-slate-800 flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-indigo-500" />
                      1. Struktur 8 Kolom Mesin
                    </span>
                    <p className="text-slate-500 mt-1 leading-relaxed">
                      Format standar ekspor mesin: Cabang, Nama, ID_Mesin, Timestamp_Raw, Tipe_Asli_Raw, Kode_Gerbang, Kolom_Kosong, Metode.
                    </p>
                  </div>

                  <div className="p-3 rounded-lg border border-slate-200/90 bg-slate-50/50">
                    <span className="font-bold text-slate-800 flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                      2. Format Tanggal & Waktu
                    </span>
                    <p className="text-slate-500 mt-1 leading-relaxed">
                      Format <code className="text-slate-700 font-semibold bg-slate-200/60 px-1 rounded">DD/MM/YYYY HH:MM:SS</code> (mis. 02/03/2026 07:54:12) maupun ISO <code className="text-slate-700 font-semibold bg-slate-200/60 px-1 rounded">YYYY-MM-DD HH:MM:SS</code> otomatis didukung.
                    </p>
                  </div>

                  <div className="p-3 rounded-lg border border-slate-200/90 bg-slate-50/50">
                    <span className="font-bold text-slate-800 flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                      3. Kesesuaian Nama Karyawan
                    </span>
                    <p className="text-slate-500 mt-1 leading-relaxed">
                      Pastikan ejaan nama di kolom ke-2 sesuai dengan menu <span className="font-semibold text-slate-700">Master Karyawan</span> agar profil jadwal dan uang makan otomatis terhubung.
                    </p>
                  </div>

                  <div className="p-3 rounded-lg border border-slate-200/90 bg-slate-50/50">
                    <span className="font-bold text-slate-800 flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full bg-purple-500" />
                      4. Fleksibel: Header & Multi-File
                    </span>
                    <p className="text-slate-500 mt-1 leading-relaxed">
                      Boleh memakai baris header ataupun langsung data di baris pertama. Anda dapat mengunggah beberapa file cabang sekaligus.
                    </p>
                  </div>
                </div>
              </div>
            )}
          </div>
        </Card>

        <p className="text-xs text-center text-slate-400 mt-2 max-w-xl mx-auto leading-relaxed">
          Master karyawan dan tanggal merah otomatis diambil dari database pengaturan HR Master.
        </p>
      </div>
    );
  }

  // ============== RESULTS DASHBOARD ==============
  const { kpis, sheets } = result;
  const activeSheet = sheets[activeTab];

  return (
    <div>
      {/* Employee Detail Modal */}
      {detailNama && (
        <EmployeeModal
          nama={detailNama}
          sheets={sheets}
          onClose={() => setDetailNama(null)}
        />
      )}

      {/* Top Bar Header */}
      <div className="flex items-start justify-between mb-6 pb-4 border-b border-slate-200/80 flex-wrap gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <h1 className="text-2xl font-bold tracking-tight text-slate-900">
              Dashboard Hasil Absensi
            </h1>
            <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200">
              Selesai Diproses
            </span>
          </div>
          <p className="text-xs mt-1 text-slate-500 font-medium">
            Berkas: <span className="text-slate-800 font-semibold">{result.filename}</span>
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          <Button variant="secondary" onClick={handleReset}>
            <span className="flex items-center gap-1.5">
              <IconReset />
              Proses File Lain
            </span>
          </Button>
          <Button onClick={handleDownloadExcel} disabled={downloading}>
            <span className="flex items-center gap-2">
              <IconDownload />
              {downloading ? "Mengunduh..." : "Unduh Excel (.xlsx)"}
            </span>
          </Button>
        </div>
      </div>

      {error && <Banner kind="error">{error}</Banner>}

      {/* KPI Cards Row */}
      <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-2.5 mb-6">
        <KpiCard label="Karyawan" value={kpis.total_karyawan} accent="slate" />
        <KpiCard label="Total Scan" value={kpis.total_baris_scan} accent="slate" />
        <KpiCard
          label="Total Telat"
          value={kpis.total_telat}
          accent="rose"
          isAlert={kpis.total_telat > 0}
        />
        <KpiCard label="Jam Lembur" value={`${kpis.total_lembur} jam`} accent="indigo" />
        <KpiCard label="Pulang Cepat" value={kpis.total_pulang_duluan} accent="amber" />
        <KpiCard label="Bonus Lembur" value={formatRupiah(kpis.total_bonus_lembur)} accent="indigo" />
        <KpiCard label="Uang Makan" value={formatRupiah(kpis.total_uang_makan)} accent="emerald" />
        <KpiCard
          label="Perlu Dicek"
          value={kpis.jml_perlu_dicek}
          accent="rose"
          isAlert={kpis.jml_perlu_dicek > 0}
        />
      </div>

      {/* Sheet Tabs Bar */}
      <div className="mb-4 overflow-x-auto pb-1" style={{ scrollbarWidth: "thin" }}>
        <div className="flex gap-1.5 min-w-max p-1 bg-slate-200/60 rounded-xl border border-slate-200">
          {sheets.map((sheet, i) => {
            const isActive = i === activeTab;
            const rowCount = sheet.data.rows?.length ?? 0;
            const isPerluDicek = sheet.key === "perlu_dicek" && rowCount > 0;
            return (
              <button
                key={sheet.key}
                onClick={() => {
                  setActiveTab(i);
                  setSearch("");
                  setCabangFilter("");
                  setProfilFilter("");
                }}
                className={`px-3 py-1.5 rounded-lg text-xs font-semibold whitespace-nowrap transition-all duration-150 flex items-center gap-1.5 cursor-pointer select-none ${
                  isActive
                    ? "bg-white text-indigo-600 shadow-xs font-bold"
                    : isPerluDicek
                    ? "text-rose-600 hover:bg-white/60"
                    : "text-slate-600 hover:text-slate-900 hover:bg-white/60"
                }`}
              >
                <span>{sheet.title}</span>
                {sheet.key !== "readme" && (
                  <span
                    className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${
                      isActive
                        ? "bg-indigo-50 text-indigo-700"
                        : isPerluDicek
                        ? "bg-rose-100 text-rose-700"
                        : "bg-slate-200/80 text-slate-600"
                    }`}
                  >
                    {rowCount.toLocaleString("id-ID")}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>

      {/* Sheet Content Card */}
      <Card className="p-0 overflow-hidden border border-slate-200/90 shadow-xs">
        {/* Filter & Action Toolbar */}
        {activeSheet.key !== "readme" && (
          <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-200/80 bg-slate-50/50 flex-wrap">
            {/* Search Input */}
            <div className="relative flex-1 min-w-[220px] max-w-sm">
              <span className="absolute left-3 top-1/2 -translate-y-1/2">
                <IconSearch />
              </span>
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={`Cari di ${activeSheet.title}...`}
                className="w-full pl-9 pr-3 py-1.5 text-xs rounded-lg border border-slate-200 bg-white text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/15 shadow-2xs"
              />
            </div>

            {/* Cabang Filter */}
            {activeSheet.data.headers.includes("Cabang") && result.cabang_list.length > 0 && (
              <select
                value={cabangFilter}
                onChange={(e) => setCabangFilter(e.target.value)}
                className="text-xs rounded-lg border border-slate-200 px-3 py-1.5 bg-white text-slate-700 font-medium focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/15 shadow-2xs cursor-pointer"
              >
                <option value="">Semua Cabang</option>
                {result.cabang_list.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </select>
            )}

            {/* Profil Filter */}
            {activeSheet.data.headers.includes("Profil") && result.profil_list.length > 0 && (
              <select
                value={profilFilter}
                onChange={(e) => setProfilFilter(e.target.value)}
                className="text-xs rounded-lg border border-slate-200 px-3 py-1.5 bg-white text-slate-700 font-medium focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/15 shadow-2xs cursor-pointer"
              >
                <option value="">Semua Profil</option>
                {result.profil_list.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </select>
            )}

            {/* Export CSV Button */}
            <button
              onClick={() => exportSheetCSV(activeSheet)}
              className="flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-lg border border-slate-200 bg-white hover:bg-slate-50 text-slate-700 shadow-2xs transition-colors ml-auto cursor-pointer"
            >
              <IconCSV />
              Ekspor Sheet CSV
            </button>
          </div>
        )}

        {/* Table / Readme Panel */}
        <div className="p-4 sm:p-5">
          {activeSheet.key === "readme" ? (
            <ReadmePanel sheet={activeSheet} />
          ) : (
            <>
              <SheetTable
                sheet={activeSheet}
                search={search}
                cabangFilter={cabangFilter}
                profilFilter={profilFilter}
                onClickNama={
                  activeSheet.data.headers.includes("Nama") ? handleClickNama : undefined
                }
              />
              {activeSheet.key === "perbandingan" && <SimpleBarChart sheet={activeSheet} />}
            </>
          )}
        </div>
      </Card>

      {/* AI Chat Panel — muncul floating di pojok kanan bawah */}
      <AIChatPanel fileId={result.file_id} />
    </div>
  );
}
