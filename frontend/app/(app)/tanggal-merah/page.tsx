"use client";
import { useEffect, useState, useRef } from "react";
import { api, isHrMaster, triggerBlobDownload } from "@/lib/api";
import { PageHeader, Card, Field, Button, Banner, inputCls, inputStyle } from "@/components/ui";

interface Holiday { id: number; tanggal: string; keterangan: string | null; }

interface ImportResult {
  status: string;
  total: number;
  inserted: number;
  updated: number;
  skipped: number;
  errors: string[];
  pesan: string;
}

export default function TanggalMerahPage() {
  const master = isHrMaster();
  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [tanggal, setTanggal] = useState("");
  const [keterangan, setKeterangan] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // State untuk Modal Import File
  const [showImport, setShowImport] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  function load() {
    api.getHolidays().then(setHolidays).catch((e) => setError(e.message));
  }
  useEffect(load, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.addHoliday({ tanggal, keterangan: keterangan || null });
      setTanggal("");
      setKeterangan("");
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number) {
    if (!confirm("Hapus tanggal merah ini?")) return;
    try {
      await api.deleteHoliday(id);
      load();
    } catch (err: any) {
      alert(err.message);
    }
  }

  // Unduh template Excel tanggal merah
  async function handleDownloadTemplate() {
    setDownloadingTemplate(true);
    setImportError(null);
    try {
      const blob = await api.downloadHolidaysTemplate();
      triggerBlobDownload(blob, "template_tanggal_merah.xlsx");
    } catch (err: any) {
      setImportError("Gagal mengunduh template: " + err.message);
    } finally {
      setDownloadingTemplate(false);
    }
  }

  // Proses upload import tanggal merah
  async function handleImportSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!importFile) {
      setImportError("Silakan pilih file Excel (.xlsx/.xls) atau CSV terlebih dahulu.");
      return;
    }
    setImporting(true);
    setImportError(null);
    setImportResult(null);

    try {
      const res = await api.importHolidays(importFile);
      setImportResult(res);
      load();
    } catch (err: any) {
      setImportError(err.message);
    } finally {
      setImporting(false);
    }
  }

  function handleFileSelect(files: FileList | null) {
    if (!files || files.length === 0) return;
    const file = files[0];
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!["xlsx", "xls", "csv"].includes(ext || "")) {
      setImportError("File harus berformat Excel (.xlsx, .xls) atau CSV (.csv)");
      return;
    }
    setImportFile(file);
    setImportError(null);
    setImportResult(null);
  }

  return (
    <div>
      <PageHeader
        title="Tanggal Merah"
        description="Dipakai untuk perhitungan bonus lembur di hari libur nasional."
        action={
          master && (
            <Button
              variant="secondary"
              onClick={() => {
                setImportFile(null);
                setImportError(null);
                setImportResult(null);
                setShowImport(true);
              }}
            >
              Import Excel/CSV
            </Button>
          )
        }
      />

      {error && <Banner kind="error">{error}</Banner>}

      {master && (
        <Card className="mb-6">
          <form onSubmit={handleAdd} className="flex items-end gap-4">
            <Field label="Tanggal">
              <input type="date" required className={inputCls} style={inputStyle} value={tanggal} onChange={(e) => setTanggal(e.target.value)} />
            </Field>
            <Field label="Keterangan (opsional)">
              <input className={inputCls} style={{ ...inputStyle, width: 260 }} placeholder="mis. Hari Kemerdekaan" value={keterangan} onChange={(e) => setKeterangan(e.target.value)} />
            </Field>
            <Button type="submit" disabled={saving}>{saving ? "Menambah..." : "+ Tambah"}</Button>
          </form>
        </Card>
      )}

      <Card className="p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left" style={{ borderColor: "var(--line)", color: "var(--text-muted)" }}>
              <th className="px-4 py-3 font-medium">Tanggal</th>
              <th className="px-4 py-3 font-medium">Keterangan</th>
              {master && <th className="px-4 py-3 font-medium text-right">Aksi</th>}
            </tr>
          </thead>
          <tbody>
            {holidays.map((h) => (
              <tr key={h.id} className="border-b last:border-0" style={{ borderColor: "var(--line)" }}>
                <td className="px-4 py-3 tabular" style={{ color: "var(--ink)" }}>
                  {new Date(h.tanggal + "T00:00:00").toLocaleDateString("id-ID", { day: "2-digit", month: "long", year: "numeric" })}
                </td>
                <td className="px-4 py-3">{h.keterangan || "—"}</td>
                {master && (
                  <td className="px-4 py-3 text-right">
                    <button onClick={() => handleDelete(h.id)} className="text-xs underline" style={{ color: "var(--clay)" }}>Hapus</button>
                  </td>
                )}
              </tr>
            ))}
            {holidays.length === 0 && (
              <tr><td colSpan={3} className="px-4 py-8 text-center" style={{ color: "var(--text-muted)" }}>Belum ada tanggal merah tersimpan.</td></tr>
            )}
          </tbody>
        </table>
      </Card>

      {/* Modal Import Excel / CSV Tanggal Merah */}
      {showImport && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ background: "rgba(21,34,48,0.5)" }}>
          <div className="bg-white rounded-lg p-6 w-full max-w-lg space-y-4 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-semibold" style={{ color: "var(--ink)" }}>
                  Import Tanggal Merah
                </h3>
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  Unggah file Excel (.xlsx/.xls) atau CSV untuk menambahkan tanggal merah sekaligus.
                </p>
              </div>
              <button
                onClick={() => setShowImport(false)}
                className="text-gray-400 hover:text-gray-600 text-lg font-bold"
              >
                ✕
              </button>
            </div>

            {importError && <Banner kind="error">{importError}</Banner>}

            {/* Hasil Ringkasan Import */}
            {importResult && (
              <div className="p-4 rounded-md border text-sm space-y-2" style={{ borderColor: "var(--moss-border)", background: "var(--moss-bg)" }}>
                <div className="font-semibold text-base" style={{ color: "var(--moss)" }}>
                  ✓ {importResult.pesan}
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs" style={{ color: "var(--ink)" }}>
                  <div>Total baris: <strong>{importResult.total}</strong></div>
                  <div>Tanggal baru: <strong style={{ color: "var(--moss)" }}>+{importResult.inserted}</strong></div>
                  <div>Keterangan diperbarui: <strong style={{ color: "var(--ink)" }}>{importResult.updated}</strong></div>
                  <div>Baris dilewati: <strong>{importResult.skipped}</strong></div>
                </div>
                {importResult.errors && importResult.errors.length > 0 && (
                  <div className="mt-2 pt-2 border-t text-xs" style={{ borderColor: "var(--line)", color: "var(--clay)" }}>
                    <strong>Catatan:</strong>
                    <ul className="list-disc pl-4 mt-1 space-y-0.5 max-h-24 overflow-y-auto">
                      {importResult.errors.map((err, i) => (
                        <li key={i}>{err}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}

            {/* Panduan Kolom & Tombol Download Template */}
            <div className="p-3.5 rounded-md border text-xs space-y-2.5" style={{ background: "var(--paper)", borderColor: "var(--line)" }}>
              <div className="flex items-center justify-between">
                <span className="font-semibold" style={{ color: "var(--ink)" }}>Format Kolom Spreadsheet</span>
                <button
                  type="button"
                  onClick={handleDownloadTemplate}
                  disabled={downloadingTemplate}
                  className="underline font-medium text-xs transition disabled:opacity-50"
                  style={{ color: "var(--accent)" }}
                >
                  {downloadingTemplate ? "Mengunduh..." : "Unduh Template Excel"}
                </button>
              </div>
              <div className="space-y-1" style={{ color: "var(--text-muted)" }}>
                <div>• <strong>Tanggal</strong> (Wajib): Format <code>YYYY-MM-DD</code> (contoh: 2026-08-17) atau <code>DD/MM/YYYY</code></div>
                <div>• <strong>Keterangan</strong> (Opsional): Nama hari libur / perayaan nasional</div>
              </div>
            </div>

            {/* Area Drag and Drop File */}
            <form onSubmit={handleImportSubmit} className="space-y-4">
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls,.csv"
                className="hidden"
                onChange={(e) => handleFileSelect(e.target.files)}
              />

              <div
                onDragOver={(e) => { e.preventDefault(); setIsDragging(true); }}
                onDragLeave={() => setIsDragging(false)}
                onDrop={(e) => {
                  e.preventDefault();
                  setIsDragging(false);
                  handleFileSelect(e.dataTransfer.files);
                }}
                onClick={() => fileInputRef.current?.click()}
                className="border-2 border-dashed rounded-lg p-6 text-center cursor-pointer transition"
                style={{
                  borderColor: isDragging ? "var(--accent-light)" : "var(--line)",
                  background: isDragging ? "var(--accent-wash)" : "transparent",
                }}
              >
                <div className="mb-2" style={{ color: "var(--text-muted)" }}>
                  <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
                    <polyline points="14 2 14 8 20 8"/>
                    <line x1="12" y1="18" x2="12" y2="12"/>
                    <line x1="9" y1="15" x2="15" y2="15"/>
                  </svg>
                </div>
                {importFile ? (
                  <div>
                    <p className="font-medium text-sm" style={{ color: "var(--ink)" }}>{importFile.name}</p>
                    <p className="text-xs text-gray-500 mt-1">{(importFile.size / 1024).toFixed(1)} KB — Klik atau drag untuk ganti file</p>
                  </div>
                ) : (
                  <div>
                    <p className="text-sm font-medium" style={{ color: "var(--ink)" }}>
                      Klik untuk pilih file atau seret file ke sini
                    </p>
                    <p className="text-xs text-gray-500 mt-1">
                      Mendukung format .xlsx, .xls, atau .csv
                    </p>
                  </div>
                )}
              </div>

              <div className="flex justify-end gap-3 pt-2">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setShowImport(false);
                    setImportFile(null);
                    setImportResult(null);
                  }}
                >
                  {importResult ? "Tutup" : "Batal"}
                </Button>
                <Button
                  type="submit"
                  disabled={!importFile || importing}
                >
                  {importing ? "Mengimpor Data..." : "Mulai Import"}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
