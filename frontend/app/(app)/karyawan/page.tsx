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

interface PHLToPKWTTransition {
  id: number;
  employment_contract_id: number;
  phl_start_date: string;
  phl_end_date: string;
  transition_date: string;
  created_at: string;
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
  employee_code: string | null;
  nik: string | null;
  id_mesin: string | null;
  profile_code: string;
  cabang: string | null;
  uang_makan_override: number | null;
  bpjs_kesehatan: number | null;
  bpjs_tk: number | null;
  active: boolean;
  // Status kepegawaian
  employment_status: string;           // "PKWTT" | "PKWT" | "PHL"
  join_date: string | null;
  tenure_display: string | null;
  contracts: EmploymentContract[];
  phl_to_pkwt_transitions: PHLToPKWTTransition[];
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
  cabang: string[] | null;
  jam_masuk: { default: string; [key: string]: string } | null;
  jam_keluar: { default: string; [key: string]: string } | null;
}

interface WhatsAppIdentity {
  id: number;
  phone_number: string;
  employee_id: number;
  employee_name: string | null;
  employee_nik_last4: string | null;
  status: string;
  verified_at: string | null;
  last_seen_at: string | null;
  failed_attempts: number;
}

interface WhatsAppAudit {
  id: number;
  phone_number: string;
  employee_id: number | null;
  employee_name: string | null;
  event_type: string;
  detail: string | null;
  created_at: string;
}

interface ImportResult {
  status: string;
  total: number;
  inserted: number;
  updated: number;
  skipped: number;
  errors: string[];
  pesan: string;
  contract_required?: string[];
}

interface MasterUpdateResult {
  dry_run: boolean;
  total_updated: number;
  total_skipped: number;
  total_not_found: number;
  total_nik_conflict: number;
  total_invalid_nik: number;
  total_invalid_status: number;
  total_invalid_profile: number;
  total_invalid_join_date: number;
  total_contract_required: number;
  detail: {
    updated: { nama: string; employee_code: string; fields: string }[];
    skipped: { row: number; employee_code?: string; reason?: string }[];
    not_found: string[];
    nik_conflict: { employee_code: string; nik: string; konflik_dengan: string }[];
    invalid_nik: { employee_code: string; nik_raw: string }[];
    invalid_status: { employee_code: string; status: string }[];
    invalid_profile: { employee_code: string; profile_code: string }[];
    invalid_join_date: { employee_code: string; value: string }[];
    contract_required: string[];
  };
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

const normalizeEmploymentStatus = (status?: string | null) => {
  const normalized = (status || "PKWTT").toUpperCase().trim();
  const aliases: Record<string, string> = {
    TETAP: "PKWTT",
    KARYAWAN_TETAP: "PKWTT",
    PKWTT: "PKWTT",
    PKWT: "PKWT",
    PHL: "PHL",
  };
  return aliases[normalized] || normalized;
};

const BLANK_FORM = {
  nama: "",
  nik: "",
  id_mesin: "",
  profile_code: "",
  cabang: "",
  uang_makan_override: "",
  bpjs_kesehatan: "",
  bpjs_tk: "",
  active: true,
  // Status kepegawaian & kontrak
  employment_status: "PKWTT",
  join_date: "",
  contract_start_date: "",
  contract_end_date: "",
  contract_keterangan: "",
  phl_period_start_date: "",
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
    nik: emp.nik || "",
    id_mesin: emp.id_mesin || "",
    profile_code: emp.profile_code,
    cabang: emp.cabang || "",
    uang_makan_override: emp.uang_makan_override?.toString() || "",
    bpjs_kesehatan: emp.bpjs_kesehatan != null ? emp.bpjs_kesehatan.toString() : "",
    bpjs_tk: emp.bpjs_tk != null ? emp.bpjs_tk.toString() : "",
    active: emp.active,
    // Status kepegawaian & kontrak
    employment_status: normalizeEmploymentStatus(emp.employment_status),
    join_date: emp.join_date || "",
    contract_start_date: activeContract?.start_date || "",
    contract_end_date: activeContract?.end_date || "",
    contract_keterangan: activeContract?.keterangan || "",
    phl_period_start_date: emp.phl_to_pkwt_transitions?.[0]?.phl_start_date || emp.join_date || "",
    // Override fields
    has_custom_rules: emp.has_custom_rules ?? false,
    jam_masuk_override: emp.jam_masuk_override || "",
    jam_keluar_override: emp.jam_keluar_override || "",
    toleransi_telat_menit_override: emp.toleransi_telat_menit_override?.toString() || "",
    bonus_lembur_per_jam_override: emp.bonus_lembur_per_jam_override?.toString() || "",
  };
}

function formToPayload(form: typeof BLANK_FORM) {
  const normalizedStatus = normalizeEmploymentStatus(form.employment_status || "PKWTT");
  const isPKWT = normalizedStatus === "PKWT";
  return {
    nama: form.nama,
    nik: form.nik || null,
    id_mesin: form.id_mesin || null,
    profile_code: form.profile_code,
    cabang: form.cabang || null,
    uang_makan_override: form.uang_makan_override.trim() === "" ? null : parseInt(form.uang_makan_override, 10) || 0,
    bpjs_kesehatan: form.bpjs_kesehatan ? parseInt(form.bpjs_kesehatan) : 0,
    bpjs_tk: form.bpjs_tk ? parseInt(form.bpjs_tk) : 0,
    active: form.active,
    // Status kepegawaian & kontrak
    employment_status: normalizedStatus,
    join_date: form.join_date || null,
    contract_start_date: isPKWT && form.contract_start_date ? form.contract_start_date : null,
    contract_end_date: isPKWT && form.contract_end_date ? form.contract_end_date : null,
    contract_keterangan: isPKWT && form.contract_keterangan ? form.contract_keterangan : null,
    phl_period_start_date: form.phl_period_start_date || null,
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
  const uangMakan = globalRules?.uang_makan_default ?? 0;
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
  const [master, setMaster] = useState(false);
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [employeesLoaded, setEmployeesLoaded] = useState(false);
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [globalRules, setGlobalRules] = useState<any>(null);
  const [filter, setFilter] = useState("");
  const [filterStatus, setFilterStatus] = useState("ALL");
  const [filterProfile, setFilterProfile] = useState("ALL");
  const [filterEmploymentStatus, setFilterEmploymentStatus] = useState("ALL");
  const [pageTab, setPageTab] = useState<"employees" | "whatsapp">("employees");
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [form, setForm] = useState<any>({ ...BLANK_FORM });
  const [activeTab, setActiveTab] = useState<"data" | "kontrak" | "aturan">("data");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [renewalForm, setRenewalForm] = useState({
    start_date: "",
    end_date: "",
    keterangan: "",
  });
  const [renewing, setRenewing] = useState(false);
  const [contractEditId, setContractEditId] = useState<number | null>(null);
  const [contractEditForm, setContractEditForm] = useState({
    start_date: "",
    end_date: "",
    status: "ACTIVE",
    keterangan: "",
  });
  const [transitionEditId, setTransitionEditId] = useState<number | null>(null);
  const [transitionStartDate, setTransitionStartDate] = useState("");
  const [savingHistory, setSavingHistory] = useState(false);

  // Import modal state (import karyawan baru dari Excel)
  const [showImport, setShowImport] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importing, setImporting] = useState(false);
  const [downloadingTemplate, setDownloadingTemplate] = useState(false);
  const [downloadingMasterTemplate, setDownloadingMasterTemplate] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportResult | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const masterUpdateInputRef = useRef<HTMLInputElement>(null);
  const [masterUpdateFile, setMasterUpdateFile] = useState<File | null>(null);
  const [masterUpdatePreview, setMasterUpdatePreview] = useState<MasterUpdateResult | null>(null);
  const [masterUpdateLoading, setMasterUpdateLoading] = useState(false);
  const [masterUpdateError, setMasterUpdateError] = useState<string | null>(null);
  const [whatsappIdentities, setWhatsappIdentities] = useState<WhatsAppIdentity[]>([]);
  const [whatsappLoading, setWhatsappLoading] = useState(false);
  const [whatsappError, setWhatsappError] = useState<string | null>(null);
  const [whatsappAudit, setWhatsappAudit] = useState<WhatsAppAudit[]>([]);
  const handledEditParam = useRef<string | null>(null);

  useEffect(() => {
    setMaster(isHrMaster());
  }, []);

  function load() {
    api.getEmployees()
      .then((data) => {
        setEmployees(data);
        setEmployeesLoaded(true);
      })
      .catch((e) => {
        setError(e.message);
      });
    api.getProfiles().then(setProfiles).catch(() => {});
    api.getRules().then(setGlobalRules).catch(() => {});
    if (master) {
      setWhatsappLoading(true);
      api.getWhatsAppIdentities()
        .then(setWhatsappIdentities)
        .catch((e) => setWhatsappError(e.message))
        .finally(() => setWhatsappLoading(false));
      api.getWhatsAppAudit()
        .then(setWhatsappAudit)
        .catch((e) => setWhatsappError(e.message));
    }
  }
  useEffect(load, [master]);

  const profileName = (code: string) => profiles.find((p) => p.code === code)?.nama || code;
  const activeProfile = profiles.find((p) => p.code === form.profile_code);
  const editingEmployee = editingId ? employees.find((emp) => emp.id === editingId) : undefined;
  const branchOptions = Array.from(new Set([
    ...profiles.flatMap((profile) => profile.cabang || []),
    ...employees.map((employee) => employee.cabang || ""),
  ].map((branch) => branch.trim()).filter(Boolean))).sort((a, b) => a.localeCompare(b));

  function startCreate() {
    if (profiles.length === 0) {
      setError("Profil/divisi belum tersedia. Muat ulang halaman lalu coba lagi.");
      return;
    }
    setEditingId(null);
    setForm({ ...BLANK_FORM, profile_code: profiles[0]?.code || "" });
    setActiveTab("data");
    setShowForm(true);
    setError(null);
    setRenewalForm({ start_date: "", end_date: "", keterangan: "" });
  }

  async function revokeWhatsAppIdentity(identity: WhatsAppIdentity) {
    if (!confirm(`Cabut linking WhatsApp ${identity.phone_number} dari ${identity.employee_name || "karyawan ini"}?`)) return;
    try {
      await api.revokeWhatsAppIdentity(identity.id);
      setWhatsappIdentities((items) =>
        items.map((item) => item.id === identity.id ? { ...item, status: "REVOKED" } : item)
      );
    } catch (e: any) {
      setWhatsappError(e.message || "Gagal mencabut linking WhatsApp.");
    }
  }

  async function moveWhatsAppIdentity(identity: WhatsAppIdentity) {
    const candidates = employees
      .filter((employee) => employee.id !== identity.employee_id && employee.employee_code)
      .map((employee) =>
        `${employee.employee_code}: ${employee.nama}${employee.active ? "" : " (Nonaktif)"}`
      )
      .join("\n");
    if (!candidates) {
      setWhatsappError("Tidak ada karyawan lain dengan Kode Karyawan untuk tujuan linking.");
      return;
    }
    const employeeCodeInput = window.prompt(`Masukkan Kode Karyawan tujuan:\n\n${candidates}`);
    if (!employeeCodeInput) return;
    const target = employees.find(
      (employee) =>
        employee.id !== identity.employee_id &&
        employee.employee_code?.toLocaleLowerCase() === employeeCodeInput.trim().toLocaleLowerCase()
    );
    if (!target?.employee_code) {
      setWhatsappError("Kode Karyawan tujuan tidak ditemukan.");
      return;
    }
    const reason = window.prompt("Alasan pemindahan linking (wajib):");
    if (!reason?.trim()) return;
    try {
      const updated = await api.moveWhatsAppIdentity(identity.id, target.employee_code, reason.trim());
      setWhatsappIdentities((items) =>
        items.map((item) => item.id === identity.id ? {
          ...item,
          employee_id: updated.employee_id,
          employee_name: target.nama,
          employee_nik_last4: target.nik ? target.nik.slice(-4) : null,
          status: updated.new_status,
        } : item)
      );
      setWhatsappAudit(await api.getWhatsAppAudit());
    } catch (e: any) {
      setWhatsappError(e.message || "Gagal memindahkan linking WhatsApp.");
    }
  }

  // Helper: format date string YYYY-MM-DD dari ISO string API
  function fmtDate(d: string | null | undefined) {
    if (!d) return "—";
    return new Date(d).toLocaleDateString("id-ID", { day: "2-digit", month: "short", year: "numeric" });
  }

  function dateBefore(value: string) {
    if (!value) return "";
    const date = new Date(`${value}T00:00:00Z`);
    date.setUTCDate(date.getUTCDate() - 1);
    return date.toISOString().slice(0, 10);
  }

  function startEdit(emp: Employee, tab: "data" | "kontrak" | "aturan" = "data") {
    setEditingId(emp.id);
    setForm(empToForm(emp));
    setActiveTab(tab);
    setShowForm(true);
    setError(null);
    setRenewalForm({ start_date: "", end_date: "", keterangan: "" });
  }

  useEffect(() => {
    const requestedId = new URLSearchParams(window.location.search).get("edit");
    if (!requestedId || !employeesLoaded || handledEditParam.current === requestedId) return;

    handledEditParam.current = requestedId;
    const clearEditParam = () => {
      const url = new URL(window.location.href);
      url.searchParams.delete("edit");
      window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
    };

    if (!master) {
      setError("Hanya HR Master yang dapat mengelola kontrak karyawan.");
      clearEditParam();
      return;
    }

    const employeeId = Number(requestedId);
    if (!Number.isSafeInteger(employeeId) || employeeId < 1) {
      setError("ID karyawan pada tautan Kelola Kontrak tidak valid.");
      clearEditParam();
      return;
    }

    const employee = employees.find((item) => item.id === employeeId);
    if (!employee) {
      setError("Karyawan pada tautan Kelola Kontrak tidak ditemukan.");
      clearEditParam();
      return;
    }

    setPageTab("employees");
    startEdit(employee, "kontrak");
    clearEditParam();
  }, [employees, employeesLoaded, master]);

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
      const employmentStatus = normalizeEmploymentStatus(form.employment_status);
      if (!form.nama.trim()) {
        setError("Nama karyawan wajib diisi.");
        setActiveTab("data");
        return;
      }
      if (!form.profile_code) {
        setError("Profil/divisi wajib dipilih.");
        setActiveTab("data");
        return;
      }
      if (!form.join_date) {
        setError("Tanggal masuk / bergabung wajib diisi.");
        setActiveTab("kontrak");
        return;
      }
      if (
        employmentStatus === "PKWT" &&
        (!form.contract_start_date || !form.contract_end_date)
      ) {
        setError("Untuk PKWT, tanggal mulai dan selesai kontrak wajib diisi.");
        setActiveTab("kontrak");
        return;
      }
      const isPhlToPkwt =
        !!editingEmployee &&
        normalizeEmploymentStatus(editingEmployee.employment_status) === "PHL" &&
        employmentStatus === "PKWT";
      if (isPhlToPkwt && !form.phl_period_start_date) {
        setError("Tanggal mulai periode PHL wajib diisi untuk merekap perubahan status.");
        setActiveTab("kontrak");
        return;
      }
      if (
        isPhlToPkwt &&
        form.contract_start_date <= form.phl_period_start_date
      ) {
        setError("Kontrak PKWT harus dimulai setelah periode PHL berakhir.");
        setActiveTab("kontrak");
        return;
      }
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

  async function handleAddRenewal() {
    if (!editingId) return;
    if (!renewalForm.start_date || !renewalForm.end_date) {
      setError("Tanggal mulai dan tanggal selesai kontrak wajib diisi.");
      return;
    }
    setRenewing(true);
    setError(null);
    try {
      await api.addContractRenewal(editingId, renewalForm);
      setRenewalForm({ start_date: "", end_date: "", keterangan: "" });
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setRenewing(false);
    }
  }

  async function refreshEmployees() {
    const updatedEmployees = await api.getEmployees();
    setEmployees(updatedEmployees);
    return updatedEmployees as Employee[];
  }

  function startContractEdit(contract: EmploymentContract) {
    setContractEditId(contract.id);
    setContractEditForm({
      start_date: contract.start_date,
      end_date: contract.end_date,
      status: contract.status,
      keterangan: contract.keterangan || "",
    });
    setTransitionEditId(null);
    setError(null);
  }

  async function handleSaveContractEdit(contractId: number) {
    if (!editingId) return;
    if (!contractEditForm.start_date || !contractEditForm.end_date) {
      setError("Tanggal mulai dan selesai kontrak wajib diisi.");
      return;
    }
    if (contractEditForm.end_date <= contractEditForm.start_date) {
      setError("Tanggal selesai kontrak harus setelah tanggal mulai kontrak.");
      return;
    }
    setSavingHistory(true);
    setError(null);
    try {
      await api.updateEmploymentContract(editingId, contractId, {
        ...contractEditForm,
        keterangan: contractEditForm.keterangan.trim() || null,
      });
      await refreshEmployees();
      setContractEditId(null);
    } catch (err: any) {
      setError(err.message || "Gagal memperbarui histori kontrak.");
    } finally {
      setSavingHistory(false);
    }
  }

  async function handleDeleteContract(contract: EmploymentContract) {
    if (!editingId) return;
    const linkedTransition = editingEmployee?.phl_to_pkwt_transitions.some(
      (transition) => transition.employment_contract_id === contract.id,
    );
    const warning = linkedTransition
      ? `Hapus kontrak #${contract.contract_number} dan rekap periode PHL yang terkait?${contract.status === "ACTIVE" ? " Status karyawan akan dikembalikan menjadi PHL." : ""}`
      : `Hapus histori kontrak #${contract.contract_number}?`;
    if (!window.confirm(warning)) return;

    setSavingHistory(true);
    setError(null);
    try {
      await api.deleteEmploymentContract(editingId, contract.id);
      const updatedEmployees = await refreshEmployees();
      if (contract.status === "ACTIVE" && linkedTransition) {
        const updatedEmployee = updatedEmployees.find((employee) => employee.id === editingId);
        if (updatedEmployee) {
          setForm(empToForm(updatedEmployee));
        }
      }
      setContractEditId(null);
    } catch (err: any) {
      setError(err.message || "Gagal menghapus histori kontrak.");
    } finally {
      setSavingHistory(false);
    }
  }

  function startTransitionEdit(transition: PHLToPKWTTransition) {
    setTransitionEditId(transition.id);
    setTransitionStartDate(transition.phl_start_date);
    setContractEditId(null);
    setError(null);
  }

  async function handleSaveTransitionEdit(transition: PHLToPKWTTransition) {
    if (!editingId) return;
    if (!transitionStartDate) {
      setError("Tanggal mulai periode PHL wajib diisi.");
      return;
    }
    setSavingHistory(true);
    setError(null);
    try {
      await api.updatePHLTransition(editingId, transition.id, transitionStartDate);
      await refreshEmployees();
      setTransitionEditId(null);
    } catch (err: any) {
      setError(err.message || "Gagal memperbarui rekap periode PHL.");
    } finally {
      setSavingHistory(false);
    }
  }

  async function handleDeleteTransition(transition: PHLToPKWTTransition) {
    if (!editingId) return;
    if (!window.confirm("Hapus rekap periode PHL ini? Kontrak PKWT terkait tetap tersimpan dan status karyawan tidak berubah.")) return;

    setSavingHistory(true);
    setError(null);
    try {
      await api.deletePHLTransition(editingId, transition.id);
      await refreshEmployees();
      setTransitionEditId(null);
    } catch (err: any) {
      setError(err.message || "Gagal menghapus rekap periode PHL.");
    } finally {
      setSavingHistory(false);
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

  async function handleDownloadMasterTemplate() {
    setDownloadingMasterTemplate(true);
    try {
      const blob = await api.downloadNikImportTemplate();
      triggerBlobDownload(blob, "template_update_master_karyawan.xlsx");
    } catch (err: any) {
      setMasterUpdateError("Gagal mengunduh template pembaruan: " + err.message);
    } finally {
      setDownloadingMasterTemplate(false);
    }
  }

  async function handleImportSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!importFile) {
      setImportError("Silakan pilih file .xlsx/.xlsm atau CSV dengan template terbaru.");
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

  async function handleMasterUpdateSelect(files: FileList | null) {
    const file = files?.[0];
    if (!file) return;
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!["xlsx", "xlsm"].includes(ext || "")) {
      setMasterUpdateError("File pembaruan master harus berformat .xlsx atau .xlsm dari template terbaru.");
      return;
    }

    setMasterUpdateFile(file);
    setMasterUpdatePreview(null);
    setMasterUpdateError(null);
    setMasterUpdateLoading(true);
    try {
      const preview = await api.importNikData(file, true);
      setMasterUpdatePreview(preview);
    } catch (err: any) {
      setMasterUpdateError(err.message);
      setMasterUpdateFile(null);
    } finally {
      setMasterUpdateLoading(false);
    }
  }

  async function confirmMasterUpdate() {
    if (!masterUpdateFile) return;
    setMasterUpdateLoading(true);
    setMasterUpdateError(null);
    try {
      await api.importNikData(masterUpdateFile, false);
      setMasterUpdateFile(null);
      setMasterUpdatePreview(null);
      load();
    } catch (err: any) {
      setMasterUpdateError(err.message);
    } finally {
      setMasterUpdateLoading(false);
    }
  }

  function handleFileSelect(files: FileList | null) {
    if (!files || files.length === 0) return;
    const file = files[0];
    const ext = file.name.split(".").pop()?.toLowerCase();
    if (!["xlsx", "xlsm", "csv"].includes(ext || "")) {
      setImportError("File harus berformat Excel (.xlsx/.xlsm) atau CSV (.csv) dengan template terbaru.");
      return;
    }
    setImportFile(file);
    setImportError(null);
    setImportResult(null);
  }

  const filtered = employees.filter((employee) => {
    const search = filter.trim().toLocaleLowerCase();
    if (search && ![
      employee.nama,
      employee.employee_code,
      employee.nik,
    ].some((value) => value?.toLocaleLowerCase().includes(search))) return false;
    if (filterStatus === "ACTIVE" && !employee.active) return false;
    if (filterStatus === "INACTIVE" && employee.active) return false;
    if (filterProfile !== "ALL" && employee.profile_code !== filterProfile) return false;
    if (
      filterEmploymentStatus !== "ALL" &&
      normalizeEmploymentStatus(employee.employment_status) !== filterEmploymentStatus
    ) return false;
    return true;
  });

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
        description={
          pageTab === "employees"
            ? "Daftar karyawan dan profil/divisi masing-masing. Dipakai otomatis saat memproses absensi."
            : "Kelola nomor WhatsApp yang terhubung dengan karyawan dan lihat riwayat tindakannya."
        }
        action={
          pageTab === "employees" && master && (
            <div className="flex items-center gap-2.5">
              <input
                ref={masterUpdateInputRef}
                type="file"
                accept=".xlsx,.xlsm"
                className="hidden"
                onChange={(e) => handleMasterUpdateSelect(e.target.files)}
              />
              <Button
                variant="secondary"
                onClick={handleDownloadMasterTemplate}
                disabled={downloadingMasterTemplate}
              >
                {downloadingMasterTemplate ? "Mengunduh..." : "Unduh Template Update"}
              </Button>
              <Button
                variant="secondary"
                onClick={() => masterUpdateInputRef.current?.click()}
              >
                Update Master Excel
              </Button>
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

      <div
        role="tablist"
        aria-label="Informasi karyawan"
        className="flex items-center border-b mt-3"
        style={{ borderColor: "var(--line)" }}
      >
        <button
          type="button"
          role="tab"
          aria-selected={pageTab === "employees"}
          onClick={() => setPageTab("employees")}
          style={tabStyle(pageTab === "employees")}
        >
          Informasi Karyawan
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={pageTab === "whatsapp"}
          aria-disabled={!master}
          disabled={!master}
          onClick={() => setPageTab("whatsapp")}
          style={{
            ...tabStyle(pageTab === "whatsapp"),
            opacity: master ? 1 : 0.5,
            cursor: master ? "pointer" : "not-allowed",
          }}
          title={master ? undefined : "Hanya HR Master yang dapat mengelola linking WhatsApp."}
        >
          Informasi Linking WhatsApp Karyawan
        </button>
      </div>

      {pageTab === "employees" && error && <Banner kind="error">{error}</Banner>}

      {master && pageTab === "whatsapp" && (
        <Card className="mt-4 p-4">
          <div className="flex items-center justify-between gap-3 mb-3">
            <div>
              <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                Linking WhatsApp Karyawan
              </h3>
              <p className="text-xs mt-1" style={{ color: "var(--text-muted)" }}>
                Satu nomor WhatsApp hanya dapat terhubung ke satu NIK. Cabut linking jika nomor perlu diverifikasi ulang.
              </p>
            </div>
            <Button
              variant="secondary"
              onClick={() => {
                setWhatsappLoading(true);
                api.getWhatsAppIdentities()
                  .then(setWhatsappIdentities)
                  .catch((e) => setWhatsappError(e.message))
                  .finally(() => setWhatsappLoading(false));
                api.getWhatsAppAudit()
                  .then(setWhatsappAudit)
                  .catch((e) => setWhatsappError(e.message));
              }}
              disabled={whatsappLoading}
            >
              Muat Ulang
            </Button>
          </div>
          {whatsappError && <Banner kind="error">{whatsappError}</Banner>}
          {whatsappLoading ? (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>Memuat linking WhatsApp...</p>
          ) : whatsappIdentities.length === 0 ? (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>Belum ada nomor WhatsApp yang tertaut.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-left" style={{ borderColor: "var(--line)", color: "var(--text-muted)" }}>
                    <th className="py-2 pr-3 font-medium">Nomor</th>
                    <th className="py-2 pr-3 font-medium">Karyawan</th>
                    <th className="py-2 pr-3 font-medium">NIK</th>
                    <th className="py-2 pr-3 font-medium">Status</th>
                    <th className="py-2 pr-3 font-medium">Aktif Terakhir</th>
                    <th className="py-2 font-medium">Aksi</th>
                  </tr>
                </thead>
                <tbody>
                  {whatsappIdentities.map((identity) => (
                    <tr key={identity.id} className="border-b" style={{ borderColor: "var(--line)" }}>
                      <td className="py-2 pr-3" style={{ color: "var(--ink)" }}>{identity.phone_number}</td>
                      <td className="py-2 pr-3" style={{ color: "var(--ink)" }}>{identity.employee_name || "-"}</td>
                      <td className="py-2 pr-3" style={{ color: "var(--text-muted)" }}>
                        {identity.employee_nik_last4 ? `••••${identity.employee_nik_last4}` : "-"}
                      </td>
                      <td className="py-2 pr-3" style={{ color: identity.status === "ACTIVE" ? "var(--success)" : "var(--text-muted)" }}>
                        {identity.status}
                      </td>
                      <td className="py-2 pr-3" style={{ color: "var(--text-muted)" }}>
                        {identity.last_seen_at ? new Date(identity.last_seen_at).toLocaleString("id-ID") : "-"}
                      </td>
                      <td className="py-2">
                        {identity.status === "ACTIVE" && (
                          <div className="flex gap-3">
                            <button
                              type="button"
                              className="text-xs underline"
                              style={{ color: "var(--ink)", background: "none", border: "none", cursor: "pointer" }}
                              onClick={() => moveWhatsAppIdentity(identity)}
                            >
                              Pindahkan
                            </button>
                            <button
                              type="button"
                              className="text-xs underline"
                              style={{ color: "var(--clay)", background: "none", border: "none", cursor: "pointer" }}
                              onClick={() => revokeWhatsAppIdentity(identity)}
                            >
                              Cabut Linking
                            </button>
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {whatsappAudit.length > 0 && (
            <details className="mt-4">
              <summary className="cursor-pointer text-xs font-medium" style={{ color: "var(--ink)" }}>
                Lihat histori audit WhatsApp ({whatsappAudit.length})
              </summary>
              <div className="overflow-x-auto mt-3">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b text-left" style={{ borderColor: "var(--line)", color: "var(--text-muted)" }}>
                      <th className="py-2 pr-3 font-medium">Waktu</th>
                      <th className="py-2 pr-3 font-medium">Nomor</th>
                      <th className="py-2 pr-3 font-medium">Event</th>
                      <th className="py-2 font-medium">Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {whatsappAudit.map((audit) => (
                      <tr key={audit.id} className="border-b" style={{ borderColor: "var(--line)" }}>
                        <td className="py-2 pr-3" style={{ color: "var(--text-muted)" }}>
                          {new Date(audit.created_at).toLocaleString("id-ID")}
                        </td>
                        <td className="py-2 pr-3" style={{ color: "var(--ink)" }}>{audit.phone_number}</td>
                        <td className="py-2 pr-3" style={{ color: "var(--ink)" }}>{audit.event_type}</td>
                        <td className="py-2" style={{ color: "var(--text-muted)" }}>{audit.detail || "-"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </details>
          )}
        </Card>
      )}

      <div hidden={pageTab !== "employees"}>
      {(masterUpdateLoading || masterUpdateError || masterUpdatePreview) && (
        <Card className="mt-4 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-semibold" style={{ color: "var(--ink)" }}>
                Preview Pembaruan Master
              </h3>
              {masterUpdateFile && (
                <p className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                  {masterUpdateFile.name}
                </p>
              )}
            </div>
            {!masterUpdateLoading && (
              <button
                type="button"
                className="text-xs underline"
                style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer" }}
                onClick={() => {
                  setMasterUpdateFile(null);
                  setMasterUpdatePreview(null);
                  setMasterUpdateError(null);
                }}
              >
                Tutup
              </button>
            )}
          </div>
          {masterUpdateLoading && (
            <p className="text-xs" style={{ color: "var(--text-muted)" }}>Menganalisis file...</p>
          )}
          {masterUpdateError && <Banner kind="error">{masterUpdateError}</Banner>}
          {masterUpdatePreview && (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs" style={{ color: "var(--ink)" }}>
                <div>Diubah: <strong>{masterUpdatePreview.total_updated}</strong></div>
                <div>Tidak ditemukan: <strong>{masterUpdatePreview.total_not_found}</strong></div>
                <div>Konflik NIK: <strong>{masterUpdatePreview.total_nik_conflict}</strong></div>
                <div>PKWT perlu kontrak: <strong>{masterUpdatePreview.total_contract_required}</strong></div>
              </div>
              {(masterUpdatePreview.total_not_found > 0 ||
                masterUpdatePreview.total_nik_conflict > 0 ||
                masterUpdatePreview.total_invalid_status > 0 ||
                masterUpdatePreview.total_invalid_profile > 0 ||
                masterUpdatePreview.total_invalid_join_date > 0 ||
                masterUpdatePreview.total_contract_required > 0) && (
                <div className="text-xs space-y-1" style={{ color: "var(--clay)" }}>
                  <strong>Perhatian sebelum menerapkan:</strong>
                  {masterUpdatePreview.total_not_found > 0 && <div>• Ada Kode Karyawan yang tidak ditemukan.</div>}
                  {masterUpdatePreview.total_nik_conflict > 0 && <div>• Ada NIK yang sudah digunakan karyawan lain.</div>}
                  {masterUpdatePreview.total_invalid_status > 0 && <div>• Ada status kepegawaian yang tidak valid.</div>}
                  {masterUpdatePreview.total_invalid_profile > 0 && <div>• Ada Kode Profil yang tidak ditemukan.</div>}
                  {masterUpdatePreview.total_invalid_join_date > 0 && <div>• Ada Tanggal Masuk yang tidak valid.</div>}
                  {masterUpdatePreview.total_contract_required > 0 && <div>• Karyawan PKWT tanpa kontrak aktif akan dinonaktifkan sampai data kontrak dilengkapi di form Karyawan.</div>}
                </div>
              )}
              <div className="flex justify-end gap-2">
                <Button
                  variant="secondary"
                  onClick={() => {
                    setMasterUpdateFile(null);
                    setMasterUpdatePreview(null);
                  }}
                >
                  Batalkan
                </Button>
                <Button
                  onClick={confirmMasterUpdate}
                  disabled={masterUpdateLoading || masterUpdatePreview.total_updated === 0}
                >
                  Terapkan Pembaruan
                </Button>
              </div>
            </>
          )}
        </Card>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <input
          placeholder="Cari nama, Kode Karyawan, atau NIK..."
          aria-label="Cari nama, Kode Karyawan, atau NIK"
          className={inputCls}
          style={{ ...inputStyle, maxWidth: 320 }}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
        />
        <select
          aria-label="Filter status karyawan"
          className={inputCls}
          style={{ ...inputStyle, width: "auto", minWidth: 150 }}
          value={filterStatus}
          onChange={(e) => setFilterStatus(e.target.value)}
        >
          <option value="ALL">Semua status</option>
          <option value="ACTIVE">Aktif</option>
          <option value="INACTIVE">Nonaktif</option>
        </select>
        <select
          aria-label="Filter profil atau divisi"
          className={inputCls}
          style={{ ...inputStyle, width: "auto", minWidth: 190 }}
          value={filterProfile}
          onChange={(e) => setFilterProfile(e.target.value)}
        >
          <option value="ALL">Semua profil / divisi</option>
          {profiles.map((profile) => (
            <option key={profile.code} value={profile.code}>
              {profile.nama}
            </option>
          ))}
        </select>
        <select
          aria-label="Filter status kepegawaian"
          className={inputCls}
          style={{ ...inputStyle, width: "auto", minWidth: 170 }}
          value={filterEmploymentStatus}
          onChange={(e) => setFilterEmploymentStatus(e.target.value)}
        >
          <option value="ALL">Semua kepegawaian</option>
          <option value="PKWTT">PKWTT</option>
          <option value="PKWT">PKWT</option>
          <option value="PHL">PHL</option>
        </select>
        <span className="text-xs" style={{ color: "var(--text-muted)" }} aria-live="polite">
          {filtered.length} dari {employees.length} karyawan
        </span>
        {(filter || filterStatus !== "ALL" || filterProfile !== "ALL" || filterEmploymentStatus !== "ALL") && (
          <button
            type="button"
            className="text-xs underline"
            style={{ color: "var(--text-muted)", background: "none", border: "none", cursor: "pointer" }}
            onClick={() => {
              setFilter("");
              setFilterStatus("ALL");
              setFilterProfile("ALL");
              setFilterEmploymentStatus("ALL");
            }}
          >
            Hapus filter
          </button>
        )}
      </div>

      {/* ─── Tabel Karyawan ──────────────────────────────────────────────────── */}
      <Card className="mt-4 p-0 overflow-hidden">
        <div className="max-h-[70vh] overflow-auto">
          <table className="w-full text-sm">
          <thead
            className="sticky top-0 z-10"
            style={{ background: "var(--surface, #fff)" }}
          >
            <tr
              className="border-b text-left"
              style={{ borderColor: "var(--line)", color: "var(--text-muted)" }}
            >
              <th className="px-4 py-3 font-medium">Kode Karyawan</th>
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
                <td className="px-4 py-3 font-mono text-xs" style={{ color: "var(--text-muted)" }}>
                  {emp.employee_code || "—"}
                </td>
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
                        background: normalizeEmploymentStatus(emp.employment_status) === "PKWT"
                          ? "#eff6ff"
                          : normalizeEmploymentStatus(emp.employment_status) === "PHL"
                            ? "#fff7ed"
                            : "var(--paper)",
                        borderColor: normalizeEmploymentStatus(emp.employment_status) === "PKWT"
                          ? "#bfdbfe"
                          : normalizeEmploymentStatus(emp.employment_status) === "PHL"
                            ? "#fdba74"
                            : "var(--line)",
                        color: normalizeEmploymentStatus(emp.employment_status) === "PKWT"
                          ? "#1e40af"
                          : normalizeEmploymentStatus(emp.employment_status) === "PHL"
                            ? "#c2410c"
                            : "var(--text-muted)",
                      }}
                    >
                      {normalizeEmploymentStatus(emp.employment_status)}
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
                    {emp.nik && (
                      <span className="text-[10px] font-mono" style={{ color: "var(--text-muted)" }}>
                        NIK: {emp.nik}
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
                  colSpan={master ? 9 : 8}
                  className="px-4 py-8 text-center"
                  style={{ color: "var(--text-muted)" }}
                >
                  Tidak ada data.
                </td>
              </tr>
            )}
          </tbody>
          </table>
        </div>
      </Card>
      </div>

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

                  <Field label="NIK (16 digit KTP, opsional)">
                    <input
                      className={inputCls}
                      style={inputStyle}
                      maxLength={16}
                      placeholder="Contoh: 3175012345670001"
                      value={form.nik}
                      onChange={(e) => {
                        const v = e.target.value.replace(/\D/g, "").slice(0, 16);
                        setForm({ ...form, nik: v });
                      }}
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
                    <Field label="Cabang (opsional)" hint="Pilihan mencakup cabang Profil dan nilai lama pada data karyawan.">
                      <select
                        className={inputCls}
                        style={inputStyle}
                        value={form.cabang}
                        onChange={(e) => setForm({ ...form, cabang: e.target.value })}
                      >
                        <option value="">Pilih cabang...</option>
                        {branchOptions.map((branch) => (
                          <option key={branch} value={branch}>{branch}</option>
                        ))}
                      </select>
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

                  <Field
                    label="Uang Makan (Rp/hari)"
                    hint="Kosong mengikuti default global Rp0 untuk semua cabang; isi nominal hanya jika ada override karyawan."
                  >
                    <input
                      type="number"
                      min="0"
                      className={inputCls}
                      style={inputStyle}
                      placeholder="0"
                      value={form.uang_makan_override}
                      onChange={(e) => setForm({ ...form, uang_makan_override: e.target.value })}
                    />
                  </Field>

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
                      onChange={(e) => {
                        const nextStatus = e.target.value;
                        setForm({
                          ...form,
                          employment_status: nextStatus,
                          phl_period_start_date:
                            normalizeEmploymentStatus(form.employment_status) === "PHL" &&
                            nextStatus === "PKWT"
                              ? form.phl_period_start_date || form.join_date
                              : form.phl_period_start_date,
                        });
                      }}
                    >
                      <option value="PKWTT">PKWTT — Karyawan Tetap</option>
                      <option value="PKWT">PKWT — Karyawan Kontrak</option>
                      <option value="PHL">PHL — Pekerja Harian Lapangan</option>
                    </select>
                  </Field>

                  {/* Tanggal Bergabung */}
                  <Field label="Tanggal Masuk / Bergabung" hint="Wajib diisi untuk semua karyawan. Digunakan untuk hitung masa kerja.">
                    <input
                      type="date"
                      className={inputCls}
                      style={inputStyle}
                      value={form.join_date}
                      onChange={(e) => setForm({ ...form, join_date: e.target.value })}
                    />
                  </Field>

                  {/* Kontrak PKWT — hanya tampil jika PKWT */}
                  {form.employment_status === "PKWT" && (
                    <>
                      {editingEmployee &&
                        normalizeEmploymentStatus(editingEmployee.employment_status) === "PHL" && (
                          <div
                            className="rounded-lg p-3 space-y-2 text-xs"
                            style={{ background: "#fff7ed", border: "1px solid #fdba74", color: "#9a3412" }}
                          >
                            <strong>Perubahan status PHL ke PKWT</strong>
                            <p>
                              Periode PHL dicatat terpisah. Tanggal Masuk utama tidak berubah; periode PHL berakhir sehari sebelum kontrak dimulai.
                            </p>
                            <Field label="Tanggal Mulai Periode PHL" hint="Terisi dari Tanggal Masuk dan dapat dikoreksi khusus untuk histori.">
                              <input
                                type="date"
                                required
                                className={inputCls}
                                style={inputStyle}
                                value={form.phl_period_start_date}
                                onChange={(e) => setForm({ ...form, phl_period_start_date: e.target.value })}
                              />
                            </Field>
                            <p>
                              Akhir periode PHL: <strong>{fmtDate(dateBefore(form.contract_start_date))}</strong>
                              {form.contract_start_date ? ` (sehari sebelum ${fmtDate(form.contract_start_date)})` : " — isi tanggal mulai kontrak PKWT."}
                            </p>
                          </div>
                        )}
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
                            className={inputCls}
                            style={inputStyle}
                            value={form.contract_start_date}
                            onChange={(e) => setForm({ ...form, contract_start_date: e.target.value })}
                          />
                        </Field>
                        <Field label="Tanggal Selesai Kontrak" hint="Wajib untuk PKWT">
                          <input
                            type="date"
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

                  {editingId && (editingEmployee?.contracts?.length ?? 0) > 0 && (
                    <div
                      className="rounded-lg p-3 space-y-3"
                      style={{ background: "var(--paper)", border: "1px solid var(--line)" }}
                    >
                      <div>
                        <p className="text-xs font-semibold" style={{ color: "var(--ink)" }}>
                          Rekapan Histori Kontrak PKWT
                        </p>
                        <p className="text-[11px] mt-0.5" style={{ color: "var(--text-muted)" }}>
                          Setiap perpanjangan tersimpan sebagai kontrak terpisah dengan nomor, periode, status, dan catatan.
                        </p>
                      </div>
                      <div className="space-y-2">
                        {editingEmployee?.contracts.map((contract) => (
                          <div
                            key={contract.id}
                            data-testid={`contract-history-${contract.id}`}
                            className="rounded-md border px-3 py-2 text-xs space-y-2"
                            style={{ borderColor: "var(--line)", background: "var(--surface, #fff)" }}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <strong style={{ color: "var(--ink)" }}>
                                Kontrak #{contract.contract_number}
                              </strong>
                              <span style={{ color: contract.status === "ACTIVE" ? "var(--moss)" : "var(--text-muted)" }}>
                                {contract.status}
                              </span>
                            </div>
                            <div className="mt-1" style={{ color: "var(--text-muted)" }}>
                              {fmtDate(contract.start_date)} s/d {fmtDate(contract.end_date)}
                            </div>
                            {contract.keterangan && (
                              <div className="mt-1" style={{ color: "var(--ink)" }}>
                                Catatan: {contract.keterangan}
                              </div>
                            )}
                            {contractEditId === contract.id ? (
                              <div className="space-y-3 border-t pt-3" style={{ borderColor: "var(--line)" }}>
                                <div className="grid grid-cols-2 gap-3">
                                  <Field label="Tanggal Mulai Kontrak">
                                    <input
                                      type="date"
                                      required
                                      className={inputCls}
                                      style={inputStyle}
                                      value={contractEditForm.start_date}
                                      onChange={(e) => setContractEditForm({ ...contractEditForm, start_date: e.target.value })}
                                    />
                                  </Field>
                                  <Field label="Tanggal Selesai Kontrak">
                                    <input
                                      type="date"
                                      required
                                      className={inputCls}
                                      style={inputStyle}
                                      value={contractEditForm.end_date}
                                      onChange={(e) => setContractEditForm({ ...contractEditForm, end_date: e.target.value })}
                                    />
                                  </Field>
                                </div>
                                <Field label="Status Kontrak">
                                  <select
                                    className={inputCls}
                                    style={inputStyle}
                                    value={contractEditForm.status}
                                    onChange={(e) => setContractEditForm({ ...contractEditForm, status: e.target.value })}
                                  >
                                    <option value="ACTIVE">ACTIVE</option>
                                    <option value="EXPIRED">EXPIRED</option>
                                    <option value="RENEWED">RENEWED</option>
                                    <option value="PROMOTED_TO_PERMANENT">PROMOTED_TO_PERMANENT</option>
                                  </select>
                                </Field>
                                <Field label="Keterangan">
                                  <input
                                    className={inputCls}
                                    style={inputStyle}
                                    value={contractEditForm.keterangan}
                                    onChange={(e) => setContractEditForm({ ...contractEditForm, keterangan: e.target.value })}
                                  />
                                </Field>
                                {editingEmployee.phl_to_pkwt_transitions.some(
                                  (transition) => transition.employment_contract_id === contract.id,
                                ) && (
                                  <p className="text-[11px]" style={{ color: "var(--text-muted)" }}>
                                    Tanggal transisi mengikuti tanggal mulai kontrak; akhir periode PHL otomatis sehari sebelumnya.
                                  </p>
                                )}
                                <div className="flex gap-2">
                                  <Button
                                    onClick={() => handleSaveContractEdit(contract.id)}
                                    disabled={savingHistory}
                                    className="px-3 py-1.5 text-xs"
                                  >
                                    Simpan
                                  </Button>
                                  <Button
                                    variant="secondary"
                                    onClick={() => setContractEditId(null)}
                                    disabled={savingHistory}
                                    className="px-3 py-1.5 text-xs"
                                  >
                                    Batal
                                  </Button>
                                </div>
                              </div>
                            ) : (
                              <div className="flex gap-2">
                                <Button
                                  variant="secondary"
                                  onClick={() => startContractEdit(contract)}
                                  disabled={savingHistory}
                                  className="px-3 py-1.5 text-xs"
                                >
                                  Edit Kontrak
                                </Button>
                                <Button
                                  variant="danger"
                                  onClick={() => handleDeleteContract(contract)}
                                  disabled={savingHistory}
                                  className="px-3 py-1.5 text-xs"
                                >
                                  Hapus Kontrak
                                </Button>
                              </div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}

                  {editingId && (editingEmployee?.phl_to_pkwt_transitions?.length ?? 0) > 0 && (
                    <div
                      className="rounded-lg p-3 space-y-3"
                      style={{ background: "#fff7ed", border: "1px solid #fdba74" }}
                    >
                      <div>
                        <p className="text-xs font-semibold" style={{ color: "#9a3412" }}>
                          Rekapan Perubahan PHL ke PKWT
                        </p>
                        <p className="text-[11px] mt-0.5" style={{ color: "#9a3412" }}>
                          Histori ini hanya mencatat transisi yang direkam melalui aplikasi.
                        </p>
                      </div>
                      <div className="space-y-2">
                        {editingEmployee?.phl_to_pkwt_transitions.map((transition) => {
                          const contract = editingEmployee.contracts.find(
                            (item) => item.id === transition.employment_contract_id,
                          );
                          return (
                            <div
                              key={transition.id}
                              data-testid={`phl-history-${transition.id}`}
                              className="rounded-md border px-3 py-2 text-xs space-y-2"
                              style={{ borderColor: "#fdba74", background: "var(--surface, #fff)" }}
                            >
                              <div style={{ color: "var(--ink)" }}>
                                Periode PHL: <strong>{fmtDate(transition.phl_start_date)} s/d {fmtDate(transition.phl_end_date)}</strong>
                              </div>
                              <div className="mt-1" style={{ color: "var(--ink)" }}>
                                Mulai PKWT: <strong>{fmtDate(transition.transition_date)}</strong>
                                {contract && <> · Kontrak #{contract.contract_number} ({fmtDate(contract.start_date)} s/d {fmtDate(contract.end_date)})</>}
                              </div>
                              {transitionEditId === transition.id ? (
                                <div className="space-y-3 border-t pt-3" style={{ borderColor: "#fdba74" }}>
                                  <Field
                                    label="Tanggal Mulai Periode PHL"
                                    hint={`Tanggal akhir akan mengikuti kontrak: ${fmtDate(dateBefore(transition.transition_date))}.`}
                                  >
                                    <input
                                      type="date"
                                      required
                                      className={inputCls}
                                      style={inputStyle}
                                      value={transitionStartDate}
                                      onChange={(e) => setTransitionStartDate(e.target.value)}
                                    />
                                  </Field>
                                  <div className="flex gap-2">
                                    <Button
                                      onClick={() => handleSaveTransitionEdit(transition)}
                                      disabled={savingHistory}
                                      className="px-3 py-1.5 text-xs"
                                    >
                                      Simpan Periode PHL
                                    </Button>
                                    <Button
                                      variant="secondary"
                                      onClick={() => setTransitionEditId(null)}
                                      disabled={savingHistory}
                                      className="px-3 py-1.5 text-xs"
                                    >
                                      Batal
                                    </Button>
                                  </div>
                                </div>
                              ) : (
                                <div className="flex gap-2">
                                  <Button
                                    variant="secondary"
                                    onClick={() => startTransitionEdit(transition)}
                                    disabled={savingHistory}
                                    className="px-3 py-1.5 text-xs"
                                  >
                                    Edit Periode PHL
                                  </Button>
                                  <Button
                                    variant="danger"
                                    onClick={() => handleDeleteTransition(transition)}
                                    disabled={savingHistory}
                                    className="px-3 py-1.5 text-xs"
                                  >
                                    Hapus Rekap PHL
                                  </Button>
                                </div>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  )}

                  {editingId && form.employment_status === "PKWT" && (
                    <div
                      className="rounded-lg p-3 space-y-3"
                      style={{ background: "#eff6ff", border: "1px solid #bfdbfe" }}
                    >
                      <div>
                        <p className="text-xs font-semibold" style={{ color: "#1e40af" }}>
                          Tambah Perpanjangan PKWT
                        </p>
                        <p className="text-[11px] mt-0.5" style={{ color: "#1e40af" }}>
                          Kontrak aktif sebelumnya akan disimpan sebagai histori dan ditandai RENEWED.
                        </p>
                      </div>
                      <div className="grid grid-cols-2 gap-3">
                        <Field label="Tanggal Mulai">
                          <input
                            type="date"
                            className={inputCls}
                            style={inputStyle}
                            value={renewalForm.start_date}
                            onChange={(e) => setRenewalForm({ ...renewalForm, start_date: e.target.value })}
                          />
                        </Field>
                        <Field label="Tanggal Selesai">
                          <input
                            type="date"
                            className={inputCls}
                            style={inputStyle}
                            value={renewalForm.end_date}
                            onChange={(e) => setRenewalForm({ ...renewalForm, end_date: e.target.value })}
                          />
                        </Field>
                      </div>
                      <Field label="Catatan Tertulis" hint='Contoh: "Perpanjangan PKWT ke-2"'>
                        <input
                          className={inputCls}
                          style={inputStyle}
                          value={renewalForm.keterangan}
                          onChange={(e) => setRenewalForm({ ...renewalForm, keterangan: e.target.value })}
                        />
                      </Field>
                      <div className="flex justify-end">
                        <Button type="button" onClick={handleAddRenewal} disabled={renewing}>
                          {renewing ? "Menyimpan..." : "Simpan Perpanjangan"}
                        </Button>
                      </div>
                    </div>
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
                  Unggah template terbaru (.xlsx/.xlsm atau CSV) untuk menambahkan atau memperbarui karyawan berdasarkan Kode Karyawan.
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
                {!!importResult.contract_required?.length && (
                  <p className="text-xs" style={{ color: "var(--clay)" }}>
                    PKWT belum memiliki kontrak aktif dan disimpan nonaktif: {importResult.contract_required.join(", ")}.
                    Lengkapi tanggal kontrak melalui form Karyawan sebelum mengaktifkannya.
                  </p>
                )}
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
                <div>• <strong>Kode Karyawan</strong>: Kunci pencocokan wajib</div>
                <div>• <strong>Nama, Cabang</strong>: Identitas dan lokasi kerja</div>
                <div>• <strong>Kode Profil</strong>: Kode dari menu Profil/Divisi</div>
                <div>• <strong>Status Kepegawaian</strong>: PKWTT, PKWT, atau PHL</div>
                <div>• <strong>NIK</strong>: Opsional, 16 digit</div>
                <div>• <strong>Tanggal Masuk</strong>: Wajib untuk karyawan baru</div>
                <div>• <strong>Status Aktif</strong>: Aktif atau Nonaktif</div>
                <div>• PKWT tanpa kontrak aktif diimpor nonaktif; lengkapi kontraknya di form.</div>
              </div>
            </div>

            <form onSubmit={handleImportSubmit} className="space-y-4">
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xlsm,.csv"
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
                    <p className="text-xs text-gray-500 mt-1">Mendukung template terbaru .xlsx, .xlsm, atau .csv</p>
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
