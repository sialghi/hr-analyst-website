"use client";
import { useEffect, useState, useRef } from "react";
import { api, isHrMaster, triggerBlobDownload } from "@/lib/api";
import { PageHeader, Card, Field, Button, Banner, inputCls, inputStyle } from "@/components/ui";

// ─── Types ────────────────────────────────────────────────────────────────────

interface EmploymentContract {
  id: number;
  contract_number: number;
  start_date: string;
  end_date: string;
  status: string;
  keterangan: string | null;
}

interface ContractReminderStatus {
  contract_id: number;
  contract_number: number;
  start_date: string;
  end_date: string;
  days_left: number;
  status_label: string;
  badge_color: string;
  message: string;
  is_expired: boolean;
  is_expiring: boolean;
}

interface Employee {
  id: number;
  nama: string;
  id_mesin: string | null;
  profile_code: string;
  cabang: string | null;
  uang_makan_override: number | null;
  bpjs_kesehatan: number | null;
  bpjs_tk: number | null;
  active: boolean;
  // Status kepegawaian
  employment_status: string;           // "TETAP" | "PKWT"
  join_date: string | null;
  tenure_display: string | null;
  contracts: EmploymentContract[];
  contract_reminder_status: ContractReminderStatus | null;
  // Override fields
  has_custom_rules: boolean;
  jam_masuk_override: string | null;
  jam_keluar_override: string | null;
  toleransi_telat_menit_override: number | null;
  bonus_lembur_per_jam_override: number | null;
}

interface Profile {
  code: string;
  nama: string;
  jam_masuk: { default: string; [key: string]: string } | null;
  jam_keluar: { default: string; [key: string]: string } | null;
}

interface ImportResult {
  status: string;
  total: number;
  inserted: number;
  updated: number;
  skipped: number;
  errors: string[];
  pesan: string;
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const BLANK_FORM = {
  nama: "",
  id_mesin: "",
  profile_code: "",
  cabang: "",
  uang_makan_override: "",
  bpjs_kesehatan: "",
  bpjs_tk: "",
  active: true,
  // Status kepegawaian & kontrak
  employment_status: "TETAP",
  join_date: "",
  contract_start_date: "",
  contract_end_date: "",
  contract_keterangan: "",
  // Override fields
  has_custom_rules: false,
  jam_masuk_override: "",
  jam_keluar_override: "",
  toleransi_telat_menit_override: "",
  bonus_lembur_per_jam_override: "",
};

function empToForm(emp: Employee) {
  // Untuk edit: pre-fill tanggal kontrak aktif bila ada
  const activeContract = emp.contracts?.find((c) => c.status === "ACTIVE") ?? emp.contracts?.[0];
  return {
    nama: emp.nama,
    id_mesin: emp.id_mesin || "",
    profile_code: emp.profile_code,
    cabang: emp.cabang || "",
    uang_makan_override: emp.uang_makan_override?.toString() || "",
    bpjs_kesehatan: emp.bpjs_kesehatan != null ? emp.bpjs_kesehatan.toString() : "",
    bpjs_tk: emp.bpjs_tk != null ? emp.bpjs_tk.toString() : "",
    active: emp.active,
    // Status kepegawaian & kontrak
    employment_status: emp.employment_status || "TETAP",
    join_date: emp.join_date || "",
    contract_start_date: activeContract?.start_date || "",
    contract_end_date: activeContract?.end_date || "",
    contract_keterangan: activeContract?.keterangan || "",
    // Override fields
    has_custom_rules: emp.has_custom_rules ?? false,
    jam_masuk_override: emp.jam_masuk_override || "",
    jam_keluar_override: emp.jam_keluar_override || "",
    toleransi_telat_menit_override: emp.toleransi_telat_menit_override?.toString() || "",
    bonus_lembur_per_jam_override: emp.bonus_lembur_per_jam_override?.toString() || "",
  };
}

function formToPayload(form: typeof BLANK_FORM) {
  const isPKWT = form.employment_status === "PKWT";
  return {
    nama: form.nama,
    id_mesin: form.id_mesin || null,
    profile_code: form.profile_code,
    cabang: form.cabang || null,
    uang_makan_override: form.uang_makan_override ? parseInt(form.uang_makan_override) : null,
    bpjs_kesehatan: form.bpjs_kesehatan ? parseInt(form.bpjs_kesehatan) : 0,
    bpjs_tk: form.bpjs_tk ? parseInt(form.bpjs_tk) : 0,
    active: form.active,
    // Status kepegawaian & kontrak
    employment_status: form.employment_status || "TETAP",
    join_date: form.join_date || null,
    contract_start_date: isPKWT && form.contract_start_date ? form.contract_start_date : null,
    contract_end_date: isPKWT && form.contract_end_date ? form.contract_end_date : null,
    contract_keterangan: isPKWT && form.contract_keterangan ? form.contract_keterangan : null,
    // Override fields
    has_custom_rules: form.has_custom_rules,
    jam_masuk_override: form.has_custom_rules && form.jam_masuk_override ? form.jam_masuk_override : null,
    jam_keluar_override: form.has_custom_rules && form.jam_keluar_override ? form.jam_keluar_override : null,
    toleransi_telat_menit_override: form.has_custom_rules && form.toleransi_telat_menit_override ? parseInt(form.toleransi_telat_menit_override) : null,
    bonus_lembur_per_jam_override: form.has_custom_rules && form.bonus_lembur_per_jam_override ? parseInt(form.bonus_lembur_per_jam_override) : null,
  };
}

// ─── Toggle Switch Component ──────────────────────────────────────────────────

function ToggleSwitch({ checked, onChange, label }: { checked: boolean; onChange: (v: boolean) => void; label: string }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      className="flex items-center gap-3 group"
      style={{ background: "none", border: "none", padding: 0, cursor: "pointer" }}
    >
      <span
        style={{
          display: "inline-flex",
          width: 44,
          height: 24,
          borderRadius: 12,
          background: checked ? "var(--accent)" : "var(--line)",
          position: "relative",
          transition: "background 0.2s",
          flexShrink: 0,
        }}
      >
        <span
          style={{
            position: "absolute",
            top: 3,
            left: checked ? 23 : 3,
            width: 18,
            height: 18,
            borderRadius: "50%",
            background: "#fff",
            boxShadow: "0 1px 3px rgba(0,0,0,0.18)",
            transition: "left 0.2s",
          }}
        />
      </span>
      <span className="text-sm font-medium" style={{ color: checked ? "var(--accent)" : "var(--text-muted)" }}>
        {label}
      </span>
    </button>
  );
}

// ─── Inheritance Preview Card ─────────────────────────────────────────────────

function InheritancePreviewCard({ profile, globalRules }: { profile: Profile | undefined; globalRules: any }) {
  const jamMasuk = profile?.jam_masuk?.default || globalRules?.jam_masuk_standar || "08:00";
  const jamKeluar = profile?.jam_keluar?.default || globalRules?.jam_keluar_standar || "16:00";
  const toleransi = globalRules?.toleransi_telat_max_menit ?? 10;
  const uangMakan = globalRules?.uang_makan_default ?? 100000;
  const lemburJam = globalRules?.bonus_lembur_per_jam ?? 10000;

  return (
    <div
      className="rounded-lg p-4 text-sm space-y-2"
      style={{ background: "var(--paper)", border: "1px solid var(--line)" }}
    >
      <p className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
        Aturan aktif dari profil {profile?.nama || "—"}
      </p>
      <div className="grid grid-cols-2 gap-x-6 gap-y-1.5" style={{ color: "var(--ink)" }}>
        <div className="flex justify-between">
          <span style={{ color: "var(--text-muted)" }}>Jam Masuk</span>
          <span className="font-medium" style={{ fontVariantNumeric: "tabular-nums" }}>{jamMasuk}</span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: "var(--text-muted)" }}>Jam Keluar</span>
          <span className="font-medium" style={{ fontVariantNumeric: "tabular-nums" }}>{jamKeluar}</span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: "var(--text-muted)" }}>Toleransi Telat</span>
          <span className="font-medium" style={{ fontVariantNumeric: "tabular-nums" }}>{toleransi} menit</span>
        </div>
        <div className="flex justify-between">
          <span style={{ color: "var(--text-muted)" }}>Uang Makan</span>
          <span className="font-medium" style={{ fontVariantNumeric: "tabular-nums" }}>Rp {uangMakan.toLocaleString("id-ID")}</span>
        </div>
        <div className="flex justify-between col-span-2">
          <span style={{ color: "var(--text-muted)" }}>Bonus Lembur</span>
          <span className="font-medium" style={{ fontVariantNumeric: "tabular-nums" }}>Rp {lemburJam.toLocaleString("id-ID")} / jam</span>
        </div>
      </div>
      <p className="text-xs pt-1" style={{ color: "var(--text-muted)" }}>
        Aktifkan toggle di atas untuk menambahkan pengecualian khusus bagi karyawan ini.
      </p>
    </div>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────────

export default function KaryawanPage() {
  const master = isHrMaster();
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [globalRules, setGlobalRules] = useState<any>(null);
  const [filter, setFilter] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<any>({ ...BLANK_FORM });
  const [activeTab, setActiveTab] = useState<"data" | "kontrak" | "aturan">("data");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Import modal state
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
    api.getRules().then(setGlobalRules).catch(() => {});
  }
  useEffect(load, []);

  const profileName = (code: string) => profiles.find((p) => p.code === code)?.nama || code;
  const activeProfile = profiles.find((p) => p.code === form.profile_code);

  function startCreate() {
    setEditingId(null);
    setForm({ ...BLANK_FORM, profile_code: profiles[0]?.code || "" });
    setActiveTab("data");
    setShowForm(true);
    setError(null);
  }

  // Helper: format date string YYYY-MM-DD dari ISO string API
  function fmtDate(d: string | null | undefined) {
    if (!d) return "—";
    return new Date(d).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
  }

  function startEdit(emp: Employee) {
    setEditingId(emp.id);
    setForm(empToForm(emp));
    setActiveTab("data");
    setShowForm(true);
    setError(null);
  }

  function handleResetOverrides() {
    setForm((f: any) => ({
      ...f,
      has_custom_rules: false,
      jam_masuk_override: "",
      jam_keluar_override: "",
      toleransi_telat_menit_override: "",
      bonus_lembur_per_jam_override: "",
      uang_makan_override: "",
    }));
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = formToPayload(form);
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

  const filtered = employees.filter((e) =>
    e.nama.toLowerCase().includes(filter.toLowerCase())
  );

  // ─── Tab styles ─────────────────────────────────────────────────────────────
  const tabStyle = (active: boolean) => ({
    padding: "8px 16px",
    fontSize: 13,
    fontWeight: active ? 600 : 400,
    color: active ? "var(--accent)" : "var(--text-muted)",
    cursor: "pointer",
    background: "none",
    border: "none",
    borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent",
    transition: "color 0.15s, border-color 0.15s",
  } as React.CSSProperties);


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
        className={inputCls}
        style={{ ...inputStyle, maxWidth: 320 }}
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
      />

      {/* ─── Tabel Karyawan ──────────────────────────────────────────────────── */}
      <Card className="mt-4 p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr
              className="border-b text-left"
              style={{ borderColor: "var(--line)", color: "var(--text-muted)" }}
            >
              <th className="px-4 py-3 font-medium">Nama</th>
              <th className="px-4 py-3 font-medium">Profil / Divisi</th>
              <th className="px-4 py-3 font-medium">Cabang</th>
              <th className="px-4 py-3 font-medium">BPJS Kes.</th>
              <th className="px-4 py-3 font-medium">BPJS TK</th>
              <th className="px-4 py-3 font-medium">Kepegawaian</th>
              <th className="px-4 py-3 font-medium">Status</th>
              {master && (
                <th className="px-4 py-3 font-medium text-right">Aksi</th>
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.map((emp) => (
              <tr
                key={emp.id}
                className="border-b last:border-0"
                style={{ borderColor: "var(--line)" }}
              >
                <td className="px-4 py-3 font-medium" style={{ color: "var(--ink)" }}>
                  {emp.nama}
                </td>
                <td className="px-4 py-3">
                  <span className="flex items-center gap-1.5 flex-wrap">
                    <span
                      className="px-2 py-0.5 rounded text-xs font-medium border"
                      style={{
                        background: emp.has_custom_rules ? "var(--amber-bg, #fef3c7)" : "var(--paper)",
                        borderColor: emp.has_custom_rules ? "var(--amber-border, #fcd34d)" : "var(--line)",
                        color: emp.has_custom_rules ? "#92400e" : "var(--ink)",
                      }}
                    >
                      {profileName(emp.profile_code)}
                    </span>
                    {emp.has_custom_rules && (
                      <span
                        className="px-1.5 py-0.5 rounded text-xs font-medium"
                        style={{
                          background: "#fef3c7",
                          color: "#92400e",
                          border: "1px solid #fcd34d",
                          fontSize: 10,
                        }}
                        title={[/* deslop-ignore 15 intentional: tooltip hover hint, not UI copy */
                          emp.jam_masuk_override ? `Jam Masuk: ${emp.jam_masuk_override}` : "",
                          emp.jam_keluar_override ? `Jam Keluar: ${emp.jam_keluar_override}` : "",
                          emp.toleransi_telat_menit_override != null ? `Toleransi Telat: ${emp.toleransi_telat_menit_override} menit` : "",
                          emp.uang_makan_override != null ? `Uang Makan: Rp ${emp.uang_makan_override.toLocaleString("id-ID")}` : "",
                          emp.bonus_lembur_per_jam_override != null ? `Lembur: Rp ${emp.bonus_lembur_per_jam_override.toLocaleString("id-ID")}/jam` : "",
                        ].filter(Boolean).join(" · ")}
                      >
                        Custom
                      </span>
                    )}
                  </span>
                </td>
                <td className="px-4 py-3" style={{ color: "var(--text-muted)" }}>
                  {emp.cabang || "—"}
                </td>
                <td className="px-4 py-3 font-mono text-xs">
                  {emp.bpjs_kesehatan
                    ? `Rp ${emp.bpjs_kesehatan.toLocaleString("id-ID")}`
                    : "Rp 0"}
                </td>
                <td className="px-4 py-3 font-mono text-xs">
                  {emp.bpjs_tk
                    ? `Rp ${emp.bpjs_tk.toLocaleString("id-ID")}`
                    : "Rp 0"}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-col gap-1">
                    <span
                      className="px-2 py-0.5 rounded text-xs font-semibold border w-fit"
                      style={{
                        background: emp.employment_status === "PKWT" ? "#eff6ff" : "var(--paper)",
                        borderColor: emp.employment_status === "PKWT" ? "#bfdbfe" : "var(--line)",
                        color: emp.employment_status === "PKWT" ? "#1e40af" : "var(--text-muted)",
                      }}
                    >
                      {emp.employment_status || "TETAP"}
                    </span>
                    {emp.contract_reminder_status?.is_expired && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-50 text-red-700 border border-red-200 w-fit">
                        Kontrak Berakhir!
                      </span>
                    )}
                    {emp.contract_reminder_status?.is_expiring && !emp.contract_reminder_status?.is_expired && (
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200 w-fit">
                        Sisa {emp.contract_reminder_status.days_left} hari
                      </span>
                    )}
                    {emp.join_date && (
                      <span className="text-[10px]" style={{ color: "var(--text-muted)" }}>
                        Join: {fmtDate(emp.join_date)}
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-4 py-3">
                  <span
                    className="px-2.5 py-0.5 rounded text-xs font-medium border"
                    style={{
                      background: emp.active ? "var(--moss-bg)" : "var(--clay-bg)",
                      borderColor: emp.active ? "var(--moss-border)" : "var(--clay-border)",
                      color: emp.active ? "var(--moss)" : "var(--clay)",
                    }}
                  >
                    {emp.active ? "Aktif" : "Nonaktif"}
                  </span>
                </td>
                {master && (
                  <td className="px-4 py-3 text-right space-x-3">
                    <button
                      onClick={() => startEdit(emp)}
                      className="text-xs underline"
                      style={{ color: "var(--ink)" }}
                    >
                      Edit
                    </button>
                    <button
                      onClick={() => handleDelete(emp.id, emp.nama)}
                      className="text-xs underline"
                      style={{ color: "var(--clay)" }}
                    >
                      Hapus
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={master ? 8 : 7}
                  className="px-4 py-8 text-center"
                  style={{ color: "var(--text-muted)" }}
                >
                  Tidak ada data.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </Card>

      {/* ─── Modal Tambah / Edit Karyawan (Tabbed) ───────────────────────────── */}
      {showForm && (
        <div
          className="fixed inset-0 flex items-center justify-center p-4 z-50"
          style={{ background: "rgba(21,34,48,0.55)" }}
        >
          <form
            onSubmit={handleSave}
            className="rounded-xl shadow-2xl w-full max-w-lg flex flex-col"
            style={{
              background: "var(--surface, #fff)",
              maxHeight: "90vh",
              overflow: "hidden",
            }}
          >
            {/* Modal Header */}
            <div
              className="px-6 pt-5 pb-0 flex items-start justify-between"
              style={{ borderBottom: "1px solid var(--line)" }}
            >
              <div>
                <h3 className="text-base font-semibold" style={{ color: "var(--ink)" }}>
                  {editingId ? "Edit Karyawan" : "Tambah Karyawan Baru"}
                </h3>
                {editingId && (
                  <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                    {form.nama}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setShowForm(false)}
                style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer", fontSize: 18, lineHeight: 1 }}
              >
                ✕
              </button>
            </div>

            {/* Tab Bar */}
            <div
              className="flex px-6"
              style={{ borderBottom: "1px solid var(--line)", gap: 0 }}
            >
              <button
                type="button"
                id="tab-data-utama"
                style={tabStyle(activeTab === "data")}
                onClick={() => setActiveTab("data")}
              >
                Data Utama
              </button>
              <button
                type="button"
                id="tab-kontrak"
                style={tabStyle(activeTab === "kontrak")}
                onClick={() => setActiveTab("kontrak")}
              >
                Kepegawaian
                {form.employment_status === "PKWT" && (
                  <span
                    style={{
                      marginLeft: 6,
                      display: "inline-block",
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: "#3b82f6",
                      verticalAlign: "middle",
                    }}
                  />
                )}
              </button>
              <button
                type="button"
                id="tab-aturan-khusus"
                style={tabStyle(activeTab === "aturan")}
                onClick={() => setActiveTab("aturan")}
              >
                Aturan Khusus
                {form.has_custom_rules && (
                  <span
                    style={{
                      marginLeft: 6,
                      display: "inline-block",
                      width: 7,
                      height: 7,
                      borderRadius: "50%",
                      background: "var(--accent)",
                      verticalAlign: "middle",
                    }}
                  />
                )}
              </button>



            </div>

            {/* Tab Content — scrollable */}
            <div className="overflow-y-auto flex-1 px-6 py-5 space-y-4">
              {error && <Banner kind="error">{error}</Banner>}

              {/* ── TAB 1: Data Utama ── */}
              {activeTab === "data" && (
                <>
                  <Field label="Nama Lengkap">
                    <input
                      required
                      className={inputCls}
                      style={inputStyle}
                      value={form.nama}
                      onChange={(e) => setForm({ ...form, nama: e.target.value })}
                    />
                  </Field>

                  <Field label="Profil / Divisi">
                    <select
                      required
                      className={inputCls}
                      style={inputStyle}
                      value={form.profile_code}
                      onChange={(e) => setForm({ ...form, profile_code: e.target.value })}
                    >
                      <option value="" disabled>Pilih profil...</option>
                      {profiles.map((p) => (
                        <option key={p.code} value={p.code}>{p.nama}</option>
                      ))}
                    </select>
                  </Field>

                  <div className="grid grid-cols-2 gap-3">
                    <Field label="ID Mesin Absen (opsional)">
                      <input
                        className={inputCls}
                        style={inputStyle}
                        value={form.id_mesin}
                        onChange={(e) => setForm({ ...form, id_mesin: e.target.value })}
                      />
                    </Field>
                    <Field label="Cabang (opsional)">
                      <input
                        className={inputCls}
                        style={inputStyle}
                        value={form.cabang}
                        onChange={(e) => setForm({ ...form, cabang: e.target.value })}
                      />
                    </Field>
                  </div>

                  <div className="grid grid-cols-2 gap-3">
                    <Field label="BPJS Kesehatan (Rp)">
                      <input
                        type="number"
                        className={inputCls}
                        style={inputStyle}
                        placeholder="0"
                        value={form.bpjs_kesehatan}
                        onChange={(e) => setForm({ ...form, bpjs_kesehatan: e.target.value })}
                      />
                    </Field>
                    <Field label="BPJS TK (Rp)">
                      <input
                        type="number"
                        className={inputCls}
                        style={inputStyle}
                        placeholder="0"
                        value={form.bpjs_tk}
                        onChange={(e) => setForm({ ...form, bpjs_tk: e.target.value })}
                      />
                    </Field>
                  </div>

                  <label className="flex items-center gap-2 text-sm" style={{ color: "var(--ink)" }}>
                    <input
                      type="checkbox"
                      checked={form.active}
                      onChange={(e) => setForm({ ...form, active: e.target.checked })}
                    />
                    Aktif (ikut dihitung saat proses absensi)
                  </label>
                </>
              )}

              {/* ── TAB 2: Kepegawaian & Kontrak ── */}
              {activeTab === "kontrak" && (
                <div className="space-y-4">

                  {/* Status Kepegawaian */}
                  <Field label="Status Kepegawaian">
                    <select
                      required
                      className={inputCls}
                      style={inputStyle}
                      value={form.employment_status}
                      onChange={(e) => setForm({ ...form, employment_status: e.target.value })}
                    >
                      <option value="TETAP">TETAP — Karyawan Tetap</option>
                      <option value="PKWT">PKWT — Karyawan Kontrak</option>
                    </select>
                  </Field>

                  {/* Tanggal Bergabung */}
                  <Field label="Tanggal Masuk / Bergabung" hint="Wajib diisi untuk semua karyawan. Digunakan untuk hitung masa kerja.">
                    <input
                      type="date"
                      required
                      className={inputCls}
                      style={inputStyle}
                      value={form.join_date}
                      onChange={(e) => setForm({ ...form, join_date: e.target.value })}
                    />
                  </Field>

                  {/* Kontrak PKWT — hanya tampil jika PKWT */}
                  {form.employment_status === "PKWT" && (
                    <>
                      <div
                        className="rounded-lg p-3 text-xs"
                        style={{ background: "#eff6ff", border: "1px solid #bfdbfe", color: "#1e40af" }}
                      >
                        <strong>PKWT:</strong> Isi periode kontrak di bawah. Jika sudah ada kontrak aktif, form ini akan memperbarui tanggalnya. Untuk riwayat perpanjangan, gunakan fitur Perpanjang Kontrak di dashboard.
                      </div>

                      <div className="grid grid-cols-2 gap-3">
                        <Field label="Tanggal Mulai Kontrak" hint="Wajib untuk PKWT">
                          <input
                            type="date"
                            required={form.employment_status === "PKWT"}
                            className={inputCls}
                            style={inputStyle}
                            value={form.contract_start_date}
                            onChange={(e) => setForm({ ...form, contract_start_date: e.target.value })}
                          />
                        </Field>
                        <Field label="Tanggal Selesai Kontrak" hint="Wajib untuk PKWT">
                          <input
                            type="date"
                            required={form.employment_status === "PKWT"}
                            className={inputCls}
                            style={inputStyle}
                            value={form.contract_end_date}
                            onChange={(e) => setForm({ ...form, contract_end_date: e.target.value })}
                          />
                        </Field>
                      </div>

                      <Field label="Keterangan Kontrak (opsional)" hint='Contoh: "PKWT Pertama", "Perpanjangan ke-2"'>
                        <input
                          className={inputCls}
                          style={inputStyle}
                          placeholder="Keterangan kontrak..."
                          value={form.contract_keterangan}
                          onChange={(e) => setForm({ ...form, contract_keterangan: e.target.value })}
                        />
                      </Field>
                    </>
                  )}

                  {/* Info masa kerja saat edit */}
                  {editingId && (
                    <div
                      className="rounded-lg p-3 text-xs space-y-1"
                      style={{ background: "var(--paper)", border: "1px solid var(--line)" }}
                    >
                      <p className="font-medium" style={{ color: "var(--text-muted)" }}>Info kontrak tersimpan:</p>
                      <p style={{ color: "var(--ink)" }}>
                        Status saat ini: <strong>{form.employment_status}</strong>
                        {form.join_date && (
                          <> · Join: <strong>{fmtDate(form.join_date)}</strong></>
                        )}
                      </p>
                      {form.employment_status === "PKWT" && form.contract_end_date && (
                        <p style={{ color: "var(--ink)" }}>
                          Kontrak aktif berakhir: <strong>{fmtDate(form.contract_end_date)}</strong>
                        </p>
                      )}
                    </div>
                  )}
                </div>
              )}

              {/* ── TAB 3: Aturan Khusus ── */}
              {activeTab === "aturan" && (
                <div className="space-y-5">
                  {/* Toggle */}
                  <ToggleSwitch
                    checked={form.has_custom_rules}
                    onChange={(v) => setForm({ ...form, has_custom_rules: v })}
                    label={
                      form.has_custom_rules
                        ? "Pengecualian Aturan Aktif"
                        : "Gunakan Pengecualian Aturan Karyawan"
                    }
                  />

                  {/* State OFF: Preview card */}
                  {!form.has_custom_rules && (
                    <InheritancePreviewCard
                      profile={activeProfile}
                      globalRules={globalRules}
                    />
                  )}

                  {/* State ON: Form override */}
                  {form.has_custom_rules && (
                    <div className="space-y-5">
                      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                        Isi hanya parameter yang ingin dibedakan. Kosongkan field untuk tetap mengikuti aturan divisi/global.
                      </p>

                      {/* Jam Kerja */}
                      <div>
                        <p
                          className="text-xs font-medium mb-3"
                          style={{ color: "var(--text-muted)" }}
                        >
                          Jam Kerja
                        </p>
                        <div className="grid grid-cols-2 gap-3">
                          <Field
                            label="Jam Masuk Khusus"
                            hint={`Standar divisi: ${activeProfile?.jam_masuk?.default || globalRules?.jam_masuk_standar || "08:00"}`}
                          >
                            <input
                              type="time"
                              className={inputCls}
                              style={inputStyle}
                              value={form.jam_masuk_override}
                              onChange={(e) => setForm({ ...form, jam_masuk_override: e.target.value })}
                              placeholder="Kosong = ikut divisi"
                            />
                          </Field>
                          <Field
                            label="Jam Keluar Khusus"
                            hint={`Standar divisi: ${activeProfile?.jam_keluar?.default || globalRules?.jam_keluar_standar || "16:00"}`}
                          >
                            <input
                              type="time"
                              className={inputCls}
                              style={inputStyle}
                              value={form.jam_keluar_override}
                              onChange={(e) => setForm({ ...form, jam_keluar_override: e.target.value })}
                            />
                          </Field>
                        </div>
                      </div>

                      {/* Kompensasi */}
                      <div>
                        <p
                          className="text-xs font-medium mb-3"
                          style={{ color: "var(--text-muted)" }}
                        >
                          Kompensasi
                        </p>
                        <div className="grid grid-cols-2 gap-3">
                          <Field
                            label="Uang Makan (Rp/hari)"
                            hint={`Default global: Rp ${(globalRules?.uang_makan_default ?? 100000).toLocaleString("id-ID")}`}
                          >
                            <input
                              type="number"
                              className={inputCls}
                              style={inputStyle}
                              placeholder="Kosong = ikut global"
                              value={form.uang_makan_override}
                              onChange={(e) => setForm({ ...form, uang_makan_override: e.target.value })}
                            />
                          </Field>
                          <Field
                            label="Bonus Lembur (Rp/jam)"
                            hint={`Default global: Rp ${(globalRules?.bonus_lembur_per_jam ?? 10000).toLocaleString("id-ID")}`}
                          >
                            <input
                              type="number"
                              className={inputCls}
                              style={inputStyle}
                              placeholder="Kosong = ikut global"
                              value={form.bonus_lembur_per_jam_override}
                              onChange={(e) => setForm({ ...form, bonus_lembur_per_jam_override: e.target.value })}
                            />
                          </Field>
                        </div>
                      </div>

                      {/* Toleransi */}
                      <div>
                        <p
                          className="text-xs font-medium mb-3"
                          style={{ color: "var(--text-muted)" }}
                        >
                          Toleransi
                        </p>
                        <Field
                          label="Toleransi Keterlambatan (menit)"
                          hint={`Default global: ${globalRules?.toleransi_telat_max_menit ?? 10} menit`}
                        >
                          <input
                            type="number"
                            className={inputCls}
                            style={{ ...inputStyle, maxWidth: "calc(50% - 6px)" }}
                            placeholder="Kosong = ikut global"
                            value={form.toleransi_telat_menit_override}
                            onChange={(e) => setForm({ ...form, toleransi_telat_menit_override: e.target.value })}
                          />
                        </Field>
                      </div>

                      {/* Reset Button */}
                      <div className="pt-1">
                        <button
                          type="button"
                          onClick={handleResetOverrides}
                          className="text-xs underline"
                          style={{ color: "var(--clay)", background: "none", border: "none", cursor: "pointer" }}
                        >
                          Reset ke default divisi
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              )}


            </div>


            {/* Modal Footer */}
            <div
              className="px-6 py-4 flex justify-end gap-3"
              style={{ borderTop: "1px solid var(--line)" }}
            >
              <Button variant="secondary" onClick={() => setShowForm(false)}>
                Batal
              </Button>
              <Button type="submit" disabled={saving}>
                {saving ? "Menyimpan..." : "Simpan"}
              </Button>
            </div>
          </form>
        </div>
      )}

      {/* ─── Modal Import Excel/CSV ───────────────────────────────────────────── */}
      {showImport && (
        <div
          className="fixed inset-0 flex items-center justify-center p-4 z-50"
          style={{ background: "rgba(21,34,48,0.5)" }}
        >
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
                style={{ background: "none", border: "none", cursor: "pointer" }}
              >
                ✕
              </button>
            </div>

            {importError && <Banner kind="error">{importError}</Banner>}

            {importResult && (
              <div
                className="p-4 rounded-md border text-sm space-y-2"
                style={{ borderColor: "var(--moss-border)", background: "var(--moss-bg)" }}
              >
                <div className="font-semibold text-base" style={{ color: "var(--moss)" }}>
                  ✓ {importResult.pesan}
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs" style={{ color: "var(--ink)" }}>
                  <div>Total baris: <strong>{importResult.total}</strong></div>
                  <div>Karyawan baru: <strong style={{ color: "var(--moss)" }}>+{importResult.inserted}</strong></div>
                  <div>Data diperbarui: <strong>{importResult.updated}</strong></div>
                  <div>Baris dilewati: <strong>{importResult.skipped}</strong></div>
                </div>
                {importResult.errors && importResult.errors.length > 0 && (
                  <div
                    className="mt-2 pt-2 border-t text-xs"
                    style={{ borderColor: "var(--line)", color: "var(--clay)" }}
                  >
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

            <div
              className="p-3.5 rounded-md border text-xs space-y-2.5"
              style={{ background: "var(--paper)", borderColor: "var(--line)" }}
            >
              <div className="flex items-center justify-between">
                <span className="font-semibold" style={{ color: "var(--ink)" }}>
                  Format Kolom Spreadsheet
                </span>
                <button
                  type="button"
                  onClick={handleDownloadTemplate}
                  disabled={downloadingTemplate}
                  className="underline font-medium text-xs transition disabled:opacity-50"
                  style={{ color: "var(--accent)", background: "none", border: "none", cursor: "pointer" }}
                >
                  {downloadingTemplate ? "Mengunduh..." : "Unduh Template Excel"}
                </button>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1" style={{ color: "var(--text-muted)" }}>
                <div>• <strong>Nama</strong>: Nama lengkap (wajib)</div>
                <div>• <strong>Profil</strong>: Divisi (OFFICE, GUDANG, dsb.)</div>
                <div>• <strong>Cabang</strong>: Lokasi kerja/toko</div>
                <div>• <strong>ID_Mesin</strong>: PIN mesin absensi</div>
                <div>• <strong>Uang_Makan</strong>: Nominal/hari</div>
                <div>• <strong>BPJS Kesehatan</strong>: Potongan Rp</div>
                <div>• <strong>BPJS TK</strong>: Potongan Rp</div>
                <div>• <strong>Active</strong>: True / False</div>
              </div>
            </div>

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
                    <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                    <polyline points="14 2 14 8 20 8" />
                    <line x1="12" y1="18" x2="12" y2="12" />
                    <line x1="9" y1="15" x2="15" y2="15" />
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
                    <p className="text-xs text-gray-500 mt-1">Mendukung format .xlsx, .xls, atau .csv</p>
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
                <Button type="submit" disabled={!importFile || importing}>
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
