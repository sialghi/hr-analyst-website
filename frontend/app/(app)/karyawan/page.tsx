"use client";
import { useEffect, useState, useRef } from "react";
import { api, isHrMaster, triggerBlobDownload } from "@/lib/api";
import { PageHeader, Card, Field, Button, Banner, inputCls, inputStyle } from "@/components/ui";

interface Employee {
  id: number;
  nama: string;
  id_mesin: string | null;
  profile_code: string;
  cabang: string | null;
  uang_makan_override: number | null;
  active: boolean;
}
interface Profile { code: string; nama: string; }

interface ImportResult {
  status: string;
  total: number;
  inserted: number;
  updated: number;
  skipped: number;
  errors: string[];
  pesan: string;
}

const BLANK = { nama: "", id_mesin: "", profile_code: "", cabang: "", uang_makan_override: "", active: true };

export default function KaryawanPage() {
  const master = isHrMaster();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [filter, setFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<any>(BLANK);
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
    api.getEmployees().then(setEmployees).catch((e) => setError(e.message));
    api.getProfiles().then(setProfiles).catch(() => {});
  }
  useEffect(load, []);

  function startCreate() {
    setEditingId(null);
    setForm({ ...BLANK, profile_code: profiles[0]?.code || "" });
    setShowForm(true);
    setError(null);
  }

  function startEdit(emp: Employee) {
    setEditingId(emp.id);
    setForm({
      nama: emp.nama, id_mesin: emp.id_mesin || "", profile_code: emp.profile_code,
      cabang: emp.cabang || "", uang_makan_override: emp.uang_makan_override?.toString() || "", active: emp.active,
    });
    setShowForm(true);
    setError(null);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = {
        nama: form.nama,
        id_mesin: form.id_mesin || null,
        profile_code: form.profile_code,
        cabang: form.cabang || null,
        uang_makan_override: form.uang_makan_override ? parseInt(form.uang_makan_override) : null,
        active: form.active,
      };
      if (editingId) await api.updateEmployee(editingId, payload);
      else await api.createEmployee(payload);
      setShowForm(false);
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number, nama: string) {
    if (!confirm(`Hapus karyawan "${nama}" dari master?`)) return;
    try {
      await api.deleteEmployee(id);
      load();
    } catch (err: any) {
      alert(err.message);
    }
  }

  // Unduh template Excel
  async function handleDownloadTemplate() {
    setDownloadingTemplate(true);
    setImportError(null);
    try {
      const blob = await api.downloadEmployeesTemplate();
      triggerBlobDownload(blob, "template_karyawan.xlsx");
    } catch (err: any) {
      setImportError("Gagal mengunduh template: " + err.message);
    } finally {
      setDownloadingTemplate(false);
    }
  }

  // Proses upload import file
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
      const res = await api.importEmployees(importFile);
      setImportResult(res);
      load(); // refresh data tabel
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

  const filtered = employees.filter((e) => e.nama.toLowerCase().includes(filter.toLowerCase()));
  const profileName = (code: string) => profiles.find((p) => p.code === code)?.nama || code;

  return (
    <div>
      <PageHeader
        title="Karyawan"
        description="Daftar karyawan dan profil/divisi masing-masing. Dipakai otomatis saat memproses absensi."
        action={
          master && (
            <div className="flex items-center gap-2.5">
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
              <Button onClick={startCreate}>+ Tambah Karyawan</Button>
            </div>
          )
        }
      />

      {error && <Banner kind="error">{error}</Banner>}

      <input
        placeholder="Cari nama karyawan..."
        className={inputCls} style={{ ...inputStyle, maxWidth: 320 }}
        value={filter} onChange={(e) => setFilter(e.target.value)}
      />

      <Card className="mt-4 p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left" style={{ borderColor: "var(--line)", color: "var(--text-muted)" }}>
              <th className="px-4 py-3 font-medium">Nama</th>
              <th className="px-4 py-3 font-medium">Profil</th>
              <th className="px-4 py-3 font-medium">Cabang</th>
              <th className="px-4 py-3 font-medium">Status</th>
              {master && <th className="px-4 py-3 font-medium text-right">Aksi</th>}
            </tr>
          </thead>
          <tbody>
            {filtered.map((emp) => (
              <tr key={emp.id} className="border-b last:border-0" style={{ borderColor: "var(--line)" }}>
                <td className="px-4 py-3 font-medium" style={{ color: "var(--ink)" }}>{emp.nama}</td>
                <td className="px-4 py-3">{profileName(emp.profile_code)}</td>
                <td className="px-4 py-3">{emp.cabang || "—"}</td>
                <td className="px-4 py-3">
                  <span className="px-2.5 py-0.5 rounded text-xs font-medium border" style={{
                    background: emp.active ? "var(--moss-bg)" : "var(--clay-bg)",
                    borderColor: emp.active ? "var(--moss-border)" : "var(--clay-border)",
                    color: emp.active ? "var(--moss)" : "var(--clay)",
                  }}>
                    {emp.active ? "Aktif" : "Nonaktif"}
                  </span>
                </td>
                {master && (
                  <td className="px-4 py-3 text-right space-x-3">
                    <button onClick={() => startEdit(emp)} className="text-xs underline" style={{ color: "var(--ink)" }}>Edit</button>
                    <button onClick={() => handleDelete(emp.id, emp.nama)} className="text-xs underline" style={{ color: "var(--clay)" }}>Hapus</button>
                  </td>
                )}
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={5} className="px-4 py-8 text-center" style={{ color: "var(--text-muted)" }}>Tidak ada data.</td></tr>
            )}
          </tbody>
        </table>
      </Card>

      {/* Modal Tambah / Edit Karyawan Manual */}
      {showForm && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ background: "rgba(21,34,48,0.5)" }}>
          <form onSubmit={handleSave} className="bg-white rounded-lg p-6 w-full max-w-md space-y-4 shadow-xl">
            <h3 className="text-base font-semibold" style={{ color: "var(--ink)" }}>
              {editingId ? "Edit Karyawan" : "Tambah Karyawan Baru"}
            </h3>
            {error && <Banner kind="error">{error}</Banner>}
            <Field label="Nama Lengkap">
              <input required className={inputCls} style={inputStyle} value={form.nama} onChange={(e) => setForm({ ...form, nama: e.target.value })} />
            </Field>
            <Field label="Profil / Divisi">
              <select required className={inputCls} style={inputStyle} value={form.profile_code} onChange={(e) => setForm({ ...form, profile_code: e.target.value })}>
                <option value="" disabled>Pilih profil...</option>
                {profiles.map((p) => <option key={p.code} value={p.code}>{p.nama}</option>)}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="ID Mesin Absen (opsional)">
                <input className={inputCls} style={inputStyle} value={form.id_mesin} onChange={(e) => setForm({ ...form, id_mesin: e.target.value })} />
              </Field>
              <Field label="Cabang (opsional)">
                <input className={inputCls} style={inputStyle} value={form.cabang} onChange={(e) => setForm({ ...form, cabang: e.target.value })} />
              </Field>
            </div>
            <Field label="Uang Makan Khusus (Rp/hari, opsional)" hint="Kosongkan untuk pakai nilai default global">
              <input type="number" className={inputCls} style={inputStyle} value={form.uang_makan_override} onChange={(e) => setForm({ ...form, uang_makan_override: e.target.value })} />
            </Field>
            <label className="flex items-center gap-2 text-sm">
              <input type="checkbox" checked={form.active} onChange={(e) => setForm({ ...form, active: e.target.checked })} />
              Aktif (ikut dihitung saat proses absensi)
            </label>
            <div className="flex justify-end gap-3 pt-2">
              <Button variant="secondary" onClick={() => setShowForm(false)}>Batal</Button>
              <Button type="submit" disabled={saving}>{saving ? "Menyimpan..." : "Simpan"}</Button>
            </div>
          </form>
        </div>
      )}

      {/* Modal Import Excel / CSV Karyawan */}
      {showImport && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ background: "rgba(21,34,48,0.5)" }}>
          <div className="bg-white rounded-lg p-6 w-full max-w-lg space-y-4 shadow-xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-lg font-semibold" style={{ color: "var(--ink)" }}>
                  Import Master Karyawan
                </h3>
                <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                  Unggah file Excel (.xlsx/.xls) atau CSV untuk menambahkan/memperbarui karyawan sekaligus.
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
                  <div>Karyawan baru: <strong style={{ color: "var(--moss)" }}>+{importResult.inserted}</strong></div>
                  <div>Data diperbarui: <strong style={{ color: "var(--ink)" }}>{importResult.updated}</strong></div>
                  <div>Baris dilewati/kosong: <strong>{importResult.skipped}</strong></div>
                </div>
                {importResult.errors && importResult.errors.length > 0 && (
                  <div className="mt-2 pt-2 border-t text-xs" style={{ borderColor: "var(--line)", color: "var(--clay)" }}>
                    <strong>Peringatan:</strong>
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
              <div className="grid grid-cols-2 gap-x-3 gap-y-1" style={{ color: "var(--text-muted)" }}>
                <div>• <strong>Nama</strong>: Nama lengkap (wajib)</div>
                <div>• <strong>Profil</strong>: Divisi (OFFICE, GUDANG, dsb.)</div>
                <div>• <strong>Cabang</strong>: Lokasi kerja/toko</div>
                <div>• <strong>ID_Mesin</strong>: PIN mesin absensi</div>
                <div>• <strong>Uang_Makan_Override</strong>: Angka nominal</div>
                <div>• <strong>Active</strong>: True / False</div>
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
