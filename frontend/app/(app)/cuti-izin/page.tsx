"use client";
import { useEffect, useState, useMemo } from "react";
import { api, isHrMaster, API_BASE } from "@/lib/api";

interface LeaveItem {
  id: number;
  nama: string;
  telegram_user_id?: string | null;
  whatsapp_user_id?: string | null;
  kategori: string;
  tanggal_mulai: string;
  tanggal_selesai: string;
  jumlah_hari?: number | null;
  jam_izin?: string | null;
  alasan?: string | null;
  foto_bukti?: string | null;
  catatan_hr?: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED";
  approved_by?: string | null;
  approved_at?: string | null;
  created_at: string;
  tipe_absensi?: string | null;
  location_cabang?: string | null;
}

interface AnnualBalanceItem {
  nama: string;
  total_quota: number;
  used_days: number;
  approved_days: number;
  pending_days: number;
  remaining_days: number;
  is_exceeded: boolean;
  excess_days: number;
  year: number;
  join_date?: string | null;
  eligible_from?: string | null;
  anniversary_date?: string | null;
  has_quota?: boolean;
  is_eligible?: boolean;
  error?: string | null;
}

const KATEGORI_MAP: Record<string, { label: string; badge: string }> = {
  CUTI_TAHUNAN:      { label: "Cuti Tahunan",            badge: "bg-slate-50 text-slate-700 border-slate-200" },
  CUTI_SETENGAH_HARI:{ label: "Cuti 1/2 Hari (CS)",       badge: "bg-amber-50 text-amber-700 border-amber-200" },
  SAKIT:             { label: "Sakit (SKD)",              badge: "bg-slate-50 text-slate-700 border-slate-200" },
  IZIN_PULANG_CEPAT: { label: "Izin Pulang Cepat",       badge: "bg-slate-50 text-slate-700 border-slate-200" },
  IZIN_TELAT:        { label: "Izin Datang Terlambat",   badge: "bg-slate-50 text-slate-700 border-slate-200" },
  LAINNYA:           { label: "Izin Lainnya",             badge: "bg-slate-50 text-slate-700 border-slate-200" },
  WORK_FROM_LOCATION:{ label: "Absensi Jarak Jauh",      badge: "bg-indigo-50 text-indigo-700 border-indigo-200" },
};

export default function CutiIzinPage() {
  const [activeTab, setActiveTab] = useState<"LOG" | "BALANCE">("LOG");
  const [leaves, setLeaves] = useState<LeaveItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Balance tab states
  const [balanceData, setBalanceData] = useState<AnnualBalanceItem[]>([]);
  const [balanceLoading, setBalanceLoading] = useState(false);
  const [balanceYear, setBalanceYear] = useState<number>(2026);
  const [filterBalanceStatus, setFilterBalanceStatus] = useState<string>("ALL");
  const [searchBalanceNama, setSearchBalanceNama] = useState<string>("");
  const [syncingQuota, setSyncingQuota] = useState(false);

  // Detail Karyawan Modal State
  const [detailModalOpen, setDetailModalOpen] = useState(false);
  const [selectedEmpNama, setSelectedEmpNama] = useState<string | null>(null);
  const [employeeDetailData, setEmployeeDetailData] = useState<any>(null);
  const [employeeLedgerData, setEmployeeLedgerData] = useState<any[]>([]);
  const [detailTab, setDetailTab] = useState<"OVERVIEW" | "LEDGER">("OVERVIEW");
  const [detailLoading, setDetailLoading] = useState(false);

  // Media / Foto Bukti Modal State
  const [previewMediaUrl, setPreviewMediaUrl] = useState<string | null>(null);
  const [previewMediaTitle, setPreviewMediaTitle] = useState<string>("");

  async function openDetailModal(nama: string) {
    setSelectedEmpNama(nama);
    setDetailModalOpen(true);
    setDetailLoading(true);
    setDetailTab("OVERVIEW");
    try {
      const [data, ledger] = await Promise.all([
        api.getEmployeeLeaveDetail(nama, balanceYear),
        api.getLeaveLedger(nama, balanceYear).catch(() => []),
      ]);
      setEmployeeDetailData(data);
      setEmployeeLedgerData(ledger || []);
    } catch (err: any) {
      console.error("Gagal memuat detail rincian karyawan:", err);
    } finally {
      setDetailLoading(false);
    }
  }

  async function handleSyncQuota() {
    if (!confirm(`Jalankan kalkulasi kuota cuti tahunan (anniversary & reset) secara otomatis melalui ledger?`)) return;
    setSyncingQuota(true);
    try {
      const res = await api.runLeaveQuotaJob();
      alert(`Sinkronisasi kuota berhasil:\n- Anniversary granted: ${res.anniversary_granted ?? 0}\n- Reset tahunan granted: ${res.annual_reset_granted ?? 0}\n- Tanggal proses: ${res.date}`);
      await loadBalanceData(balanceYear);
    } catch (err: any) {
      alert(err.message || "Gagal menjalankan sinkronisasi kuota.");
    } finally {
      setSyncingQuota(false);
    }
  }

  // Filters
  const [filterStatus, setFilterStatus] = useState<string>("ALL");
  const [filterKategori, setFilterKategori] = useState<string>("ALL");
  const [filterCabang, setFilterCabang] = useState<string>("ALL");
  const [searchNama, setSearchNama] = useState<string>("");

  // Modal tambah
  const [modalOpen, setModalOpen] = useState(false);
  const [employees, setEmployees] = useState<any[]>([]);
  const [formCabang, setFormCabang] = useState("");
  const [formNama, setFormNama] = useState("");
  const [isManualNama, setIsManualNama] = useState(false);
  const [formKategori, setFormKategori] = useState("CUTI_TAHUNAN");
  const [formTglMulai, setFormTglMulai] = useState("");
  const [formTglSelesai, setFormTglSelesai] = useState("");
  const [formJamIzin, setFormJamIzin] = useState("");
  const [formAlasan, setFormAlasan] = useState("");
  const [saving, setSaving] = useState(false);

  // Action status loading ID
  const [actionLoadingId, setActionLoadingId] = useState<number | null>(null);

  const canApprove = isHrMaster();

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [leavesData, empsData] = await Promise.all([
        api.getLeaves(),
        api.getEmployees().catch(() => []),
      ]);
      setLeaves(leavesData);
      setEmployees(empsData || []);
    } catch (err: any) {
      setError(err.message || "Gagal memuat data cuti & izin.");
    } finally {
      setLoading(false);
    }
  }

  async function loadBalanceData(year: number) {
    setBalanceLoading(true);
    try {
      const res = await api.getAnnualLeaveBalances(year);
      setBalanceData(res.data || []);
    } catch (err: any) {
      console.error("Gagal memuat saldo cuti:", err);
    } finally {
      setBalanceLoading(false);
    }
  }

  useEffect(() => {
    loadData();
    loadBalanceData(balanceYear);
  }, []);

  useEffect(() => {
    if (activeTab === "BALANCE") {
      loadBalanceData(balanceYear);
    }
  }, [activeTab, balanceYear]);

  const cabangList = useMemo(() => {
    const s = new Set<string>();
    employees.forEach((emp) => {
      if (emp.cabang && typeof emp.cabang === "string") {
        s.add(emp.cabang.trim());
      }
    });
    return Array.from(s).sort();
  }, [employees]);

  const employeesByCabang = useMemo(() => {
    if (!formCabang) return employees;
    return employees.filter((emp: any) => emp.cabang === formCabang);
  }, [employees, formCabang]);

  const currentYear = new Date().getFullYear();

  const selectedUserQuota = useMemo(() => {
    if (!formNama) return null;
    const nameClean = formNama.trim().toLowerCase();
    const item = balanceData.find((b) => b.nama.trim().toLowerCase() === nameClean);
    if (item) {
      const isEligible = item.is_eligible ?? (item.eligible_from ? new Date(item.eligible_from) <= new Date() : false);
      return {
        usedDays: item.used_days,
        remaining: item.remaining_days,
        total: item.total_quota,
        has_quota: item.has_quota,
        is_eligible: isEligible,
        join_date: item.join_date,
        eligible_from: item.eligible_from,
        anniversary_date: item.anniversary_date,
        error: item.error,
      };
    }

    let usedDays = 0;
    leaves.forEach((lv) => {
      if (
        lv.nama.trim().toLowerCase() === nameClean &&
        (lv.kategori === "CUTI_TAHUNAN" || lv.kategori === "CUTI_SETENGAH_HARI") &&
        (lv.status === "APPROVED" || lv.status === "PENDING")
      ) {
        if (lv.tanggal_mulai && lv.tanggal_selesai) {
          const start = new Date(lv.tanggal_mulai);
          if (start.getFullYear() === currentYear) {
            usedDays += lv.jumlah_hari ?? (lv.kategori === "CUTI_TAHUNAN" ? 1.0 : 0.5);
          }
        }
      }
    });

    const remaining = Math.max(0, 12 - usedDays);
    return {
      usedDays,
      remaining,
      total: 12,
      has_quota: true,
      is_eligible: true,
      join_date: null,
      eligible_from: null,
      anniversary_date: null,
      error: null,
    };
  }, [formNama, balanceData, leaves, currentYear]);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!formNama.trim() || !formTglMulai || !formTglSelesai) {
      alert("Nama dan tanggal wajib diisi.");
      return;
    }

    // Validasi client-side hak cuti tahunan
    if (formKategori === "CUTI_TAHUNAN" || formKategori === "CUTI_SETENGAH_HARI") {
      if (selectedUserQuota) {
        if (selectedUserQuota.is_eligible === false) {
          if (selectedUserQuota.eligible_from && new Date(selectedUserQuota.eligible_from) > new Date(formTglMulai)) {
            alert(
              `⚠️ Pengajuan Cuti Ditolak:\n` +
              `Karyawan ${formNama} belum memiliki hak cuti tahunan (belum 1 tahun masa kerja).\n` +
              `Hak cuti baru aktif mulai tanggal ${selectedUserQuota.eligible_from}.`
            );
            return;
          } else if (selectedUserQuota.error) {
            alert(`⚠️ Pengajuan Cuti Ditolak:\n${selectedUserQuota.error}`);
            return;
          }
        }
        if (selectedUserQuota.remaining <= 0) {
          alert(
            `⚠️ Pengajuan Cuti Ditolak:\n` +
            `Sisa saldo cuti tahunan ${formNama} untuk tahun ini sudah habis ` +
            `(sisa: ${selectedUserQuota.remaining} hari).`
          );
          return;
        }
      }
    }

    setSaving(true);
    try {
      await api.createLeave({
        nama: formNama.trim(),
        kategori: formKategori,
        tanggal_mulai: formTglMulai,
        tanggal_selesai: formTglSelesai,
        jumlah_hari: formKategori === "CUTI_SETENGAH_HARI" ? 0.5 : (formKategori === "CUTI_TAHUNAN" ? 1.0 : null),
        jam_izin: formJamIzin.trim() || null,
        alasan: formAlasan.trim() || null,
        tipe_absensi: formKategori === "WORK_FROM_LOCATION" ? "remote_work" : "normal",
        location_cabang: formKategori === "WORK_FROM_LOCATION" ? (formCabang || null) : null,
      });
      setModalOpen(false);
      // Reset form
      setFormNama("");
      setFormTglMulai("");
      setFormTglSelesai("");
      setFormJamIzin("");
      setFormAlasan("");
      await loadData();
      await loadBalanceData(balanceYear);
    } catch (err: any) {
      alert(err.message || "Gagal menyimpan pengajuan.");
    } finally {
      setSaving(false);
    }
  }

  async function handleStatus(id: number, status: "APPROVED" | "REJECTED") {
    const actionText = status === "APPROVED" ? "menyetujui" : "menolak";
    if (!confirm(`Apakah Anda yakin ingin ${actionText} permohonan ini?`)) return;
    setActionLoadingId(id);
    try {
      await api.updateLeaveStatus(id, status);
      await loadData();
      if (activeTab === "BALANCE") loadBalanceData(balanceYear);
    } catch (err: any) {
      alert(err.message || "Gagal memperbarui status.");
    } finally {
      setActionLoadingId(null);
    }
  }

  async function handleDelete(id: number, nama: string) {
    if (!confirm(`Hapus permohonan cuti untuk ${nama}?`)) return;
    try {
      await api.deleteLeave(id);
      await loadData();
      if (activeTab === "BALANCE") loadBalanceData(balanceYear);
    } catch (err: any) {
      alert(err.message || "Gagal menghapus permohonan.");
    }
  }

  const filteredLeaves = useMemo(() => {
    return leaves.filter((item) => {
      // Absensi Jarak Jauh ditampilkan di halaman Absensi Request Approval, bukan di sini
      if (item.kategori === "WORK_FROM_LOCATION") return false;
      if (filterStatus !== "ALL" && item.status !== filterStatus) return false;
      if (filterKategori !== "ALL" && item.kategori !== filterKategori) return false;
      if (searchNama && !item.nama.toLowerCase().includes(searchNama.toLowerCase())) return false;
      return true;
    });
  }, [leaves, filterStatus, filterKategori, searchNama]);

  const filteredBalances = useMemo(() => {
    return balanceData.filter((item) => {
      if (searchBalanceNama && !item.nama.toLowerCase().includes(searchBalanceNama.toLowerCase())) return false;
      if (filterBalanceStatus === "EXCEEDED" && !item.is_exceeded) return false;
      if (filterBalanceStatus === "CRITICAL" && (item.is_exceeded || item.remaining_days > 3 || !item.has_quota)) return false;
      if (filterBalanceStatus === "SAFE" && (item.is_exceeded || item.remaining_days <= 3 || !item.has_quota)) return false;
      if (filterBalanceStatus === "ELIGIBLE" && !item.has_quota) return false;
      if (filterBalanceStatus === "NOT_ELIGIBLE" && item.has_quota) return false;
      return true;
    });
  }, [balanceData, searchBalanceNama, filterBalanceStatus]);

  // Balance Stats
  const countEligible = balanceData.filter((b) => b.has_quota).length;
  const countNotEligible = balanceData.filter((b) => !b.has_quota).length;
  const countExceededBalance = balanceData.filter((b) => b.is_exceeded).length;
  const countCriticalBalance = balanceData.filter((b) => b.has_quota && !b.is_exceeded && b.remaining_days <= 3).length;
  const countSafeBalance = balanceData.filter((b) => b.has_quota && !b.is_exceeded && b.remaining_days > 3).length;
  const totalLeaveDaysUsedAll = balanceData.reduce((acc, b) => acc + b.used_days, 0);

  // Log Stats (mengecualikan WORK_FROM_LOCATION — ada di halaman Absensi Request Approval)
  const countPending = leaves.filter((l) => l.status === "PENDING" && l.kategori !== "WORK_FROM_LOCATION").length;
  const countApproved = leaves.filter((l) => l.status === "APPROVED" && l.kategori !== "WORK_FROM_LOCATION").length;
  const countRejected = leaves.filter((l) => l.status === "REJECTED" && l.kategori !== "WORK_FROM_LOCATION").length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Manajemen Cuti & Izin</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Kelola pengajuan perizinan harian dan rekap saldo kuota cuti tahunan karyawan.
          </p>
        </div>
        <button
          onClick={() => setModalOpen(true)}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-indigo-600 text-white text-xs font-semibold hover:bg-indigo-700 transition-colors shadow-xs cursor-pointer shrink-0"
        >
          <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
            <line x1="12" y1="5" x2="12" y2="19" />
            <line x1="5" y1="12" x2="19" y2="12" />
          </svg>
          <span>Input Pengajuan Baru</span>
        </button>
      </div>

      {/* Tabs Navigation */}
      <div className="flex items-center border-b border-slate-200 text-xs font-semibold gap-6">
        <button
          onClick={() => setActiveTab("LOG")}
          className={`pb-3 relative cursor-pointer transition-colors ${
            activeTab === "LOG"
              ? "text-indigo-600 border-b-2 border-indigo-600 font-bold"
              : "text-slate-500 hover:text-slate-800"
          }`}
        >
          <span>Daftar Pengajuan & Approval</span>
          {countPending > 0 && (
            <span className="ml-2 px-1.5 py-0.5 text-[10px] bg-amber-100 text-amber-800 rounded-full font-bold">
              {countPending}
            </span>
          )}
        </button>

        <button
          onClick={() => setActiveTab("BALANCE")}
          className={`pb-3 relative cursor-pointer transition-colors ${
            activeTab === "BALANCE"
              ? "text-indigo-600 border-b-2 border-indigo-600 font-bold"
              : "text-slate-500 hover:text-slate-800"
          }`}
        >
          <span>Rekap Saldo Cuti Tahunan</span>
          {countExceededBalance > 0 && (
            <span className="ml-2 px-1.5 py-0.5 text-[10px] bg-rose-100 text-rose-700 rounded-full font-bold">
              {countExceededBalance} Kelebihan
            </span>
          )}
        </button>
      </div>

      {activeTab === "LOG" && (
        <>
          {/* KPI Cards LOG */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-white border border-slate-200/90 shadow-2xs">
              <p className="text-[11px] font-semibold text-amber-600 uppercase tracking-wider">Menunggu Persetujuan</p>
              <p className="text-2xl font-bold text-slate-900 mt-1">{countPending}</p>
              <p className="text-[11px] text-slate-400 mt-0.5">Perlu konfirmasi HR Master</p>
            </div>
            <div className="p-4 rounded-xl bg-white border border-slate-200/90 shadow-2xs">
              <p className="text-[11px] font-semibold text-emerald-600 uppercase tracking-wider">Telah Disetujui</p>
              <p className="text-2xl font-bold text-slate-900 mt-1">{countApproved}</p>
              <p className="text-[11px] text-slate-400 mt-0.5">Otomatis diakui saat proses absensi</p>
            </div>
            <div className="p-4 rounded-xl bg-white border border-slate-200/90 shadow-2xs">
              <p className="text-[11px] font-semibold text-rose-600 uppercase tracking-wider">Ditolak</p>
              <p className="text-2xl font-bold text-slate-900 mt-1">{countRejected}</p>
              <p className="text-[11px] text-slate-400 mt-0.5">Tetap dihitung sesuai aturan biasa</p>
            </div>
            <div className="p-4 rounded-xl bg-white border border-slate-200/90 shadow-2xs">
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Total Pengajuan</p>
              <p className="text-2xl font-bold text-slate-900 mt-1">{countPending + countApproved + countRejected}</p>
              <p className="text-[11px] text-slate-400 mt-0.5">Cuti &amp; izin (tanpa Absen Jarak Jauh)</p>
            </div>
          </div>
        </>
      )}

      {activeTab === "BALANCE" && (
        <>
          {/* KPI Cards BALANCE */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
            <div className="p-4 rounded-xl bg-white border border-slate-200/90 shadow-2xs">
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider">Total Karyawan</p>
              <p className="text-2xl font-bold text-slate-900 mt-1">{balanceData.length}</p>
              <p className="text-[11px] text-slate-400 mt-0.5">Tahun {balanceYear}</p>
            </div>
            <div className="p-4 rounded-xl bg-white border border-indigo-200/90 shadow-2xs bg-indigo-50/20">
              <p className="text-[11px] font-semibold text-indigo-600 uppercase tracking-wider">Hak Cuti Aktif (&ge; 1 Thn)</p>
              <p className="text-2xl font-bold text-indigo-900 mt-1">
                {countEligible} <span className="text-xs font-normal text-slate-400">/ {balanceData.length}</span>
              </p>
              <p className="text-[11px] text-slate-500 mt-0.5">{countNotEligible} belum 1 tahun kerja</p>
            </div>
            <div className="p-4 rounded-xl bg-white border border-amber-200/90 shadow-2xs bg-amber-50/20">
              <p className="text-[11px] font-semibold text-amber-700 uppercase tracking-wider">Sisa Kritis (&le; 3 Hari)</p>
              <p className="text-2xl font-bold text-amber-700 mt-1">{countCriticalBalance}</p>
              <p className="text-[11px] text-amber-600/80 mt-0.5">{countExceededBalance} karyawan kelebihan cuti</p>
            </div>
            <div className="p-4 rounded-xl bg-white border border-emerald-200/90 shadow-2xs bg-emerald-50/20">
              <p className="text-[11px] font-semibold text-emerald-600 uppercase tracking-wider">Total Cuti Terpakai</p>
              <p className="text-2xl font-bold text-emerald-700 mt-1">{totalLeaveDaysUsedAll.toFixed(1)} <span className="text-xs font-normal">Hari</span></p>
              <p className="text-[11px] text-emerald-500 mt-0.5">Akumulasi seluruh tim ({balanceYear})</p>
            </div>
          </div>
        </>
      )}


      {/* Filter Bar LOG */}
      {activeTab === "LOG" && (
        <div className="p-3.5 rounded-xl bg-white border border-slate-200/90 shadow-2xs flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2 flex-1">
            <input
              type="text"
              placeholder="Cari nama karyawan..."
              value={searchNama}
              onChange={(e) => setSearchNama(e.target.value)}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-indigo-500 w-48"
            />

            <select
              value={filterStatus}
              onChange={(e) => setFilterStatus(e.target.value)}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 focus:outline-none focus:border-indigo-500 cursor-pointer"
            >
              <option value="ALL">Semua Status</option>
              <option value="PENDING">Menunggu (Pending)</option>
              <option value="APPROVED">Disetujui (Approved)</option>
              <option value="REJECTED">Ditolak (Rejected)</option>
            </select>

            <select
              value={filterKategori}
              onChange={(e) => setFilterKategori(e.target.value)}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 focus:outline-none focus:border-indigo-500 cursor-pointer"
            >
              <option value="ALL">Semua Kategori</option>
              <option value="CUTI_TAHUNAN">Cuti Tahunan (Full Day)</option>
              <option value="CUTI_SETENGAH_HARI">Cuti 1/2 Hari (CS)</option>
              <option value="SAKIT">Sakit (SKD)</option>
              <option value="IZIN_PULANG_CEPAT">Izin Pulang Cepat</option>
              <option value="IZIN_TELAT">Izin Datang Terlambat</option>
              <option value="LAINNYA">Lainnya</option>
            </select>
          </div>

          <button
            onClick={loadData}
            className="text-xs text-slate-500 hover:text-slate-800 px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
          >
            Muat Ulang ↻
          </button>
        </div>
      )}

      {/* Filter Bar BALANCE */}
      {activeTab === "BALANCE" && (
        <div className="p-3.5 rounded-xl bg-white border border-slate-200/90 shadow-2xs flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2 flex-1">
            <input
              type="text"
              placeholder="Cari nama karyawan..."
              value={searchBalanceNama}
              onChange={(e) => setSearchBalanceNama(e.target.value)}
              className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-indigo-500 w-48"
            />

            <select
              value={balanceYear}
              onChange={(e) => setBalanceYear(Number(e.target.value))}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 font-semibold focus:outline-none focus:border-indigo-500 cursor-pointer"
            >
              <option value={2026}>Tahun 2026</option>
              <option value={2025}>Tahun 2025</option>
              <option value={2027}>Tahun 2027</option>
            </select>

            <select
              value={filterBalanceStatus}
              onChange={(e) => setFilterBalanceStatus(e.target.value)}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 focus:outline-none focus:border-indigo-500 cursor-pointer"
            >
              <option value="ALL">Semua Status Saldo</option>
              <option value="ELIGIBLE">Sudah Berhak (Aktif)</option>
              <option value="NOT_ELIGIBLE">Belum Berhak (&lt; 1 Tahun)</option>
              <option value="SAFE">Saldo Aman (&gt; 3 Hari)</option>
              <option value="CRITICAL">Sisa Kritis (&le; 3 Hari)</option>
              <option value="EXCEEDED">Kelebihan Cuti</option>
            </select>
          </div>

          <div className="flex items-center gap-2">
            {canApprove && (
              <button
                type="button"
                onClick={handleSyncQuota}
                disabled={syncingQuota}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200 transition-colors cursor-pointer disabled:opacity-50"
                title="Hitung dan berikan kuota cuti tahunan (anniversary & reset 1 Jan) secara otomatis via Ledger"
              >
                <svg className={`w-3.5 h-3.5 ${syncingQuota ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/>
                </svg>
                <span>{syncingQuota ? "Memproses..." : "Sync Kuota Otomatis"}</span>
              </button>
            )}

            <button
              onClick={() => loadBalanceData(balanceYear)}
              className="text-xs text-slate-500 hover:text-slate-800 px-2 py-1 rounded hover:bg-slate-100 transition-colors cursor-pointer"
            >
              Muat Ulang ↻
            </button>
          </div>
        </div>
      )}

      {/* Table LOG */}
      {activeTab === "LOG" && (
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-2xs">
          {loading ? (
            <div className="p-8 text-center text-xs text-slate-400">Memuat data permohonan cuti & izin...</div>
          ) : error ? (
            <div className="p-8 text-center text-xs text-rose-600 bg-rose-50/50">{error}</div>
          ) : filteredLeaves.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-400">
              Tidak ada permohonan cuti/izin yang sesuai filter.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">Nama Karyawan</th>
                    <th className="px-4 py-3">Kategori</th>
                    <th className="px-4 py-3">Cabang</th>
                    <th className="px-4 py-3">Periode / Jam</th>

                    <th className="px-4 py-3">Alasan</th>
                    <th className="px-4 py-3 text-center">Foto Bukti / SKD</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Verifikator</th>
                    <th className="px-4 py-3 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {filteredLeaves.map((item) => {
                  const kat = KATEGORI_MAP[item.kategori] || KATEGORI_MAP.LAINNYA;
                  const isSameDay = item.tanggal_mulai === item.tanggal_selesai;
                  const tglDisplay = isSameDay
                    ? item.tanggal_mulai
                    : `${item.tanggal_mulai} s/d ${item.tanggal_selesai}`;

                  return (
                    <tr key={item.id} className={`hover:bg-slate-50/80 transition-colors ${item.kategori === "WORK_FROM_LOCATION" ? "bg-indigo-50/30" : ""}`}>
                      <td className="px-4 py-3 font-semibold text-slate-900">
                        {item.nama}
                        {item.telegram_user_id && (
                          <span className="block text-[10px] font-normal text-slate-400">
                            Telegram ID: {item.telegram_user_id}
                          </span>
                        )}
                        {item.whatsapp_user_id && (
                          <span className="inline-flex items-center gap-1 text-[10px] font-normal text-emerald-700 bg-emerald-50 px-1.5 py-0.5 rounded border border-emerald-200 mt-0.5">
                            WA: +{item.whatsapp_user_id}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-block text-[10px] font-semibold px-2 py-0.5 rounded-md border ${kat.badge}`}>
                          {kat.label}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[11px] text-slate-600">
                        {item.location_cabang ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200 font-medium">
                            {item.location_cabang}
                          </span>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-medium text-slate-800">{tglDisplay}</span>
                        {item.jam_izin && (
                          <span className="block text-[11px] text-slate-600 font-medium">
                            Pukul {item.jam_izin}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 max-w-xs truncate text-slate-600" title={item.alasan || "-"}>
                        {item.alasan || "-"}
                      </td>
                      <td className="px-4 py-3 text-center">
                        {item.foto_bukti ? (
                          item.foto_bukti.toLowerCase().endsWith(".pdf") ? (
                            <a
                              href={`${API_BASE}/${item.foto_bukti}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200 hover:bg-rose-100 hover:border-rose-300 transition-colors shadow-2xs"
                              title="Buka / Unduh Dokumen PDF Surat Dokter"
                            >
                              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                                <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                                <polyline points="14 2 14 8 20 8" />
                                <line x1="16" y1="13" x2="8" y2="13" />
                                <line x1="16" y1="17" x2="8" y2="17" />
                              </svg>
                              <span>PDF SKD</span>
                            </a>
                          ) : (
                            <button
                              type="button"
                              onClick={() => {
                                setPreviewMediaUrl(`${API_BASE}/${item.foto_bukti}`);
                                setPreviewMediaTitle(`${item.nama} - ${kat.label} (${tglDisplay})`);
                              }}
                              className="group relative inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg border border-slate-200 bg-white hover:border-indigo-400 hover:bg-indigo-50/40 hover:shadow-2xs transition-all cursor-pointer text-[11px] font-medium text-slate-700"
                              title="Klik untuk melihat foto bukti"
                            >
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={`${API_BASE}/${item.foto_bukti}`}
                                alt="Bukti"
                                className="w-4 h-4 rounded object-cover border border-slate-200"
                              />
                              <span>Lihat Foto</span>
                            </button>
                          )
                        ) : (
                          <span className="text-slate-300 text-[11px]">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {item.status === "PENDING" && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                            Pending
                          </span>
                        )}
                        {item.status === "APPROVED" && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                            Disetujui
                          </span>
                        )}
                        {item.status === "REJECTED" && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                            Ditolak
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-[11px] text-slate-500">
                        {item.approved_by ? (
                          <div>
                            <span className="font-medium text-slate-700">{item.approved_by}</span>
                            {item.approved_at && (
                              <span className="block text-[10px] text-slate-400">
                                {new Date(item.approved_at).toLocaleDateString("id-ID")}
                              </span>
                            )}
                          </div>
                        ) : (
                          "-"
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {canApprove && item.status === "PENDING" && (
                            <>
                              <button
                                onClick={() => handleStatus(item.id, "APPROVED")}
                                disabled={actionLoadingId === item.id}
                                className="px-2 py-1 rounded text-[11px] font-semibold bg-emerald-600 text-white hover:bg-emerald-700 transition-colors cursor-pointer disabled:opacity-50"
                                title="Setujui Izin"
                              >
                                Setujui
                              </button>
                              <button
                                onClick={() => handleStatus(item.id, "REJECTED")}
                                disabled={actionLoadingId === item.id}
                                className="px-2 py-1 rounded text-[11px] font-semibold bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200 transition-colors cursor-pointer disabled:opacity-50"
                                title="Tolak Izin"
                              >
                                Tolak
                              </button>
                            </>
                          )}
                          {canApprove && (
                            <button
                              onClick={() => handleDelete(item.id, item.nama)}
                              className="p-1 rounded text-slate-400 hover:text-rose-600 hover:bg-slate-100 transition-colors cursor-pointer"
                              title="Hapus Data"
                            >
                              <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                                <polyline points="3 6 5 6 21 6" />
                                <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                              </svg>
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      )}

      {/* Table BALANCE */}
      {activeTab === "BALANCE" && (
        <div className="rounded-xl border border-slate-200 bg-white overflow-hidden shadow-2xs">
          {balanceLoading ? (
            <div className="p-8 text-center text-xs text-slate-400">Memuat rekap saldo cuti tahunan...</div>
          ) : filteredBalances.length === 0 ? (
            <div className="p-8 text-center text-xs text-slate-400">
              Tidak ada data saldo cuti karyawan yang sesuai filter.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 border-b border-slate-200 text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
                  <tr>
                    <th className="px-4 py-3">Nama Karyawan</th>
                    <th className="px-4 py-3">Mulai Kerja &amp; 1 Thn</th>
                    <th className="px-4 py-3 text-center">Hak Cuti</th>
                    <th className="px-4 py-3 text-center">Jatah Kuota</th>
                    <th className="px-4 py-3 text-center">Terpakai</th>
                    <th className="px-4 py-3 text-center">Sisa Saldo</th>
                    <th className="px-4 py-3 text-center">Status</th>
                    <th className="px-4 py-3 text-right">Aksi</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700">
                  {filteredBalances.map((item, idx) => {
                    const isExceeded = item.is_exceeded;
                    const isEmpEligible = item.is_eligible || (item.eligible_from ? new Date(item.eligible_from) <= new Date() : false);
                    const isCritical = isEmpEligible && !isExceeded && item.remaining_days <= 3 && item.remaining_days > 0;

                    return (
                      <tr
                        key={idx}
                        className={`hover:bg-slate-50/80 transition-colors ${
                          isExceeded ? "bg-rose-50/40" : isCritical ? "bg-amber-50/30" : ""
                        }`}
                      >
                        <td className="px-4 py-3 font-semibold text-slate-900">
                          <button
                            type="button"
                            onClick={() => openDetailModal(item.nama)}
                            className="text-left font-bold text-indigo-700 hover:text-indigo-900 hover:underline cursor-pointer flex items-center gap-1.5"
                            title="Klik untuk melihat rincian sakit, cuti, dan ledger kuota"
                          >
                            <span>{item.nama}</span>
                            <svg className="w-3.5 h-3.5 text-indigo-400 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                              <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                              <polyline points="15 3 21 3 21 9" />
                              <line x1="10" y1="14" x2="21" y2="3" />
                            </svg>
                          </button>
                        </td>
                        <td className="px-4 py-3 text-slate-600">
                          <div className="font-medium text-slate-800 text-[11px]">
                            {item.join_date ? `Join: ${item.join_date}` : <span className="text-slate-400 italic">Belum ada join date</span>}
                          </div>
                          {item.anniversary_date && (
                            <div className="text-[10px] text-slate-400">
                              1 Thn: {item.anniversary_date}
                            </div>
                          )}
                        </td>
                        <td className="px-4 py-3 text-center">
                          {isEmpEligible ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                              Aktif
                            </span>
                          ) : item.eligible_from ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200" title={`Aktif mulai ${item.eligible_from}`}>
                              <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                              Belum 1 Thn
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold bg-slate-100 text-slate-500 border border-slate-200">
                              No Data
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-center font-semibold text-slate-700">
                          <div>{item.total_quota} Hari</div>
                          {item.total_quota > 0 && item.total_quota < 12 && (
                            <span className="text-[10px] font-normal text-indigo-600 block">Proporsional</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-center">
                          <span className={`font-bold ${isExceeded ? "text-rose-600" : "text-slate-900"}`}>
                            {item.used_days.toFixed(1)} Hari
                          </span>
                          {item.pending_days > 0 && (
                            <span className="block text-[10px] text-amber-600">Pending: {item.pending_days.toFixed(1)}h</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-center font-bold">
                          {isExceeded ? (
                            <span className="text-rose-600">-{item.excess_days.toFixed(1)} Hari</span>
                          ) : isEmpEligible ? (
                            <span className="text-emerald-700">{item.remaining_days.toFixed(1)} Hari</span>
                          ) : (
                            <span className="text-slate-400">0 Hari</span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-center">
                          {isExceeded ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-rose-100 text-rose-700 border border-rose-300">
                              Kelebihan (+{item.excess_days.toFixed(1)}h)
                            </span>
                          ) : !isEmpEligible ? (
                            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-50 text-amber-800 border border-amber-200">
                              {item.eligible_from ? `Mulai ${item.eligible_from}` : "Belum Berhak"}
                            </span>
                          ) : item.remaining_days <= 0 ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold bg-slate-100 text-slate-700 border border-slate-300">
                              Saldo Habis (0h)
                            </span>
                          ) : isCritical ? (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-300">
                              ⚡ Sisa {item.remaining_days.toFixed(1)}h
                            </span>
                          ) : (
                            <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                              ✅ Sisa {item.remaining_days.toFixed(1)}h
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => openDetailModal(item.nama)}
                            className="px-2.5 py-1 rounded-lg text-[11px] font-semibold bg-slate-100 text-slate-700 hover:bg-indigo-50 hover:text-indigo-700 hover:border-indigo-200 border border-slate-200 transition-colors cursor-pointer"
                          >
                            Rincian &amp; Ledger
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Modal Tambah Pengajuan */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-md bg-white rounded-xl shadow-xl border border-slate-200 overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
              <h2 className="text-sm font-bold text-slate-900">Input Pengajuan Cuti / Izin</h2>
              <button
                onClick={() => setModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 text-sm cursor-pointer"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleAdd} className="p-5 space-y-3.5 text-xs">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Pilih Cabang</label>
                  <select
                    value={formCabang}
                    onChange={(e) => {
                      setFormCabang(e.target.value);
                      setFormNama("");
                    }}
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  >
                    <option value="">-- Semua Cabang ({employees.length}) --</option>
                    {cabangList.map((cb) => (
                      <option key={cb} value={cb}>
                        {cb}
                      </option>
                    ))}
                  </select>
                </div>

                <div>
                  <div className="flex items-center justify-between mb-1">
                    <label className="block font-semibold text-slate-700">Nama Karyawan *</label>
                    <button
                      type="button"
                      onClick={() => {
                        setIsManualNama(!isManualNama);
                        setFormNama("");
                      }}
                      className="text-[10px] text-indigo-600 hover:underline cursor-pointer"
                    >
                      {isManualNama ? "Pilih dari daftar" : "Ketik manual"}
                    </button>
                  </div>

                  {isManualNama ? (
                    <input
                      type="text"
                      required
                      placeholder="Ketik nama karyawan..."
                      value={formNama}
                      onChange={(e) => setFormNama(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500"
                    />
                  ) : (
                    <select
                      required
                      value={formNama}
                      onChange={(e) => setFormNama(e.target.value)}
                      className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500 cursor-pointer"
                    >
                      <option value="">-- Pilih Karyawan ({employeesByCabang.length}) --</option>
                      {employeesByCabang.map((emp) => (
                        <option key={emp.id} value={emp.nama}>
                          {emp.nama} {emp.cabang ? `(${emp.cabang})` : ""}
                        </option>
                      ))}
                    </select>
                  )}

                  {selectedUserQuota && (() => {
                    const isFormEmpEligible = selectedUserQuota.is_eligible || (selectedUserQuota.eligible_from ? new Date(selectedUserQuota.eligible_from) <= new Date() : false);
                    return (
                      <div className={`mt-2 p-2.5 rounded-lg text-[11px] border ${
                        !isFormEmpEligible
                          ? "bg-amber-50 text-amber-900 border-amber-200"
                          : selectedUserQuota.remaining > 0
                          ? "bg-emerald-50 text-emerald-800 border-emerald-200"
                          : "bg-rose-50 text-rose-800 border-rose-200"
                      }`}>
                        <div className="flex items-center justify-between">
                          <span className="font-semibold">
                            {!isFormEmpEligible
                              ? "⏳ Hak Cuti Belum Aktif"
                              : `Sisa Cuti Tahunan (${currentYear}):`}
                          </span>
                          <span className="font-bold">
                            {!isFormEmpEligible
                              ? `Mulai ${selectedUserQuota.eligible_from || "-"}`
                              : `${selectedUserQuota.remaining} / ${selectedUserQuota.total} Hari`}
                          </span>
                        </div>
                        {!isFormEmpEligible ? (
                          <p className="mt-1 text-[10px] text-amber-700 leading-tight">
                            {selectedUserQuota.join_date
                              ? `Mulai kerja: ${selectedUserQuota.join_date}. Genap 1 tahun pada ${selectedUserQuota.eligible_from}. Cuti tahunan belum dapat diajukan.`
                              : "Karyawan belum memiliki data Tanggal Masuk (join_date). Lengkapi data di menu Karyawan."}
                          </p>
                        ) : (
                          <div className="mt-1 text-[10px] text-slate-500 flex justify-between">
                            <span>Terpakai: {selectedUserQuota.usedDays} Hari</span>
                            {selectedUserQuota.join_date && (
                              <span>Join: {selectedUserQuota.join_date}</span>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })()}
                </div>
              </div>

                <div>
                <label className="block font-semibold text-slate-700 mb-1">Kategori Permohonan *</label>
                <select
                  value={formKategori}
                  onChange={(e) => setFormKategori(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500 cursor-pointer"
                >
                  <option value="CUTI_TAHUNAN">Cuti Tahunan (Full Day)</option>
                  <option value="CUTI_SETENGAH_HARI">Cuti 1/2 Hari / CS (potong 0.5 hari)</option>
                  <option value="SAKIT">Izin Sakit / SKD (Full Day)</option>
                  <option value="IZIN_PULANG_CEPAT">Izin Pulang Lebih Awal (Parsial)</option>
                  <option value="IZIN_TELAT">Izin Datang Terlambat (Parsial)</option>
                  <option value="LAINNYA">Izin Lainnya</option>
                  <option value="WORK_FROM_LOCATION">Absensi Jarak Jauh</option>
                </select>
                {formKategori === "CUTI_SETENGAH_HARI" && (
                  <p className="text-[10px] text-amber-700 mt-1.5 bg-amber-50 rounded px-2 py-1 border border-amber-200">
                    Cuti Setengah Hari (CS) memotong <strong>0.5 hari</strong> dari kuota cuti tahunan.
                  </p>
                )}
                {formKategori === "WORK_FROM_LOCATION" && (
                  <p className="text-[10px] text-indigo-600 mt-1.5 bg-indigo-50 rounded px-2 py-1 border border-indigo-100">
                    Hari ini akan dihitung sebagai <strong>Hari Kerja Valid</strong> setelah disetujui HR Master. Pilih cabang karyawan di atas.
                  </p>
                )}
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Tanggal Mulai *</label>
                  <input
                    type="date"
                    required
                    value={formTglMulai}
                    onChange={(e) => {
                      setFormTglMulai(e.target.value);
                      if (!formTglSelesai) setFormTglSelesai(e.target.value);
                    }}
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  />
                </div>
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">Tanggal Selesai *</label>
                  <input
                    type="date"
                    required
                    value={formTglSelesai}
                    onChange={(e) => setFormTglSelesai(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  />
                </div>
              </div>

              {(formKategori === "IZIN_PULANG_CEPAT" || formKategori === "IZIN_TELAT") && (
                <div>
                  <label className="block font-semibold text-slate-700 mb-1">
                    Jam Izin (Format HH:MM)
                  </label>
                  <input
                    type="time"
                    value={formJamIzin}
                    onChange={(e) => setFormJamIzin(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500 cursor-pointer"
                  />
                  <p className="text-[10px] text-slate-400 mt-1">
                    Contoh: Pulang jam 14:00 atau masuk jam 09:30 agar potongan tidak dikenakan.
                  </p>
                </div>
              )}

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Alasan / Keterangan</label>
                <textarea
                  rows={2}
                  placeholder="Keterangan keperluan cuti/izin..."
                  value={formAlasan}
                  onChange={(e) => setFormAlasan(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setModalOpen(false)}
                  className="px-3 py-2 rounded-lg text-slate-600 hover:bg-slate-100 cursor-pointer font-medium"
                >
                  Batal
                </button>
                <button
                  type="submit"
                  disabled={saving}
                  className="px-4 py-2 rounded-lg bg-indigo-600 text-white font-semibold hover:bg-indigo-700 disabled:opacity-50 cursor-pointer"
                >
                  {saving ? "Menyimpan..." : "Simpan Pengajuan"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal Detail Rincian Cuti & Izin Karyawan */}
      {detailModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4">
          <div className="w-full max-w-2xl bg-white rounded-2xl shadow-2xl border border-slate-200 overflow-hidden flex flex-col max-h-[90vh]">
            <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-slate-50/50">
              <div>
                <h2 className="text-base font-bold text-slate-900">Rincian Cuti &amp; Perizinan</h2>
                <p className="text-xs text-slate-500">{selectedEmpNama} — Tahun {balanceYear}</p>
              </div>
              <button
                onClick={() => setDetailModalOpen(false)}
                className="w-7 h-7 flex items-center justify-center rounded-full text-slate-400 hover:text-slate-700 hover:bg-slate-200/60 transition-colors cursor-pointer text-sm"
              >
                ✕
              </button>
            </div>

            {/* Modal Tabs Navigation */}
            <div className="flex border-b border-slate-200 bg-slate-50/70 text-xs px-6 pt-2 gap-4">
              <button
                type="button"
                onClick={() => setDetailTab("OVERVIEW")}
                className={`pb-2.5 px-2 font-semibold transition-colors cursor-pointer ${
                  detailTab === "OVERVIEW"
                    ? "text-indigo-600 border-b-2 border-indigo-600 font-bold"
                    : "text-slate-500 hover:text-slate-800"
                }`}
              >
                Rincian &amp; Statistik
              </button>
              <button
                type="button"
                onClick={() => setDetailTab("LEDGER")}
                className={`pb-2.5 px-2 font-semibold transition-colors cursor-pointer flex items-center gap-1.5 ${
                  detailTab === "LEDGER"
                    ? "text-indigo-600 border-b-2 border-indigo-600 font-bold"
                    : "text-slate-500 hover:text-slate-800"
                }`}
              >
                <span>Buku Besar Kuota (Ledger)</span>
                {employeeLedgerData.length > 0 && (
                  <span className="px-1.5 py-0.2 rounded-full text-[10px] bg-indigo-100 text-indigo-700 font-bold">
                    {employeeLedgerData.length}
                  </span>
                )}
              </button>
            </div>

            <div className="p-6 overflow-y-auto space-y-5 text-xs">
              {detailLoading ? (
                <div className="py-12 text-center text-slate-400">Memuat rincian data perizinan &amp; ledger...</div>
              ) : !employeeDetailData ? (
                <div className="py-12 text-center text-slate-400">Data perizinan tidak ditemukan.</div>
              ) : detailTab === "OVERVIEW" ? (
                <>
                  {/* Info Kontrak & Hak Cuti */}
                  {employeeDetailData.balance_info && (() => {
                    const bInfo = employeeDetailData.balance_info;
                    const isEmpEligible = bInfo.is_eligible || bInfo.has_quota || (bInfo.eligible_from ? new Date(bInfo.eligible_from) <= new Date() : false);
                    return (
                      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 p-3 bg-slate-50 rounded-xl border border-slate-200 text-[11px]">
                        <div>
                          <span className="text-slate-400 block text-[10px]">Tanggal Mulai Kerja</span>
                          <span className="font-semibold text-slate-800">
                            {bInfo.join_date || <span className="text-slate-400 italic font-normal">Belum diset</span>}
                          </span>
                        </div>
                        <div>
                          <span className="text-slate-400 block text-[10px]">Anniversary 1 Tahun</span>
                          <span className="font-semibold text-slate-800">
                            {bInfo.anniversary_date || "—"}
                          </span>
                        </div>
                        <div>
                          <span className="text-slate-400 block text-[10px]">Status Hak Cuti</span>
                          <span className={`font-semibold ${isEmpEligible ? "text-emerald-700" : "text-amber-700"}`}>
                            {isEmpEligible
                              ? "Sudah Berhak (Aktif)"
                              : `Belum (Mulai ${bInfo.eligible_from || "-"})`}
                          </span>
                        </div>
                      </div>
                    );
                  })()}

                  {/* Card Highlight Saldo */}
                  <div className={`p-4 rounded-xl border flex items-center justify-between ${
                    employeeDetailData.is_exceeded
                      ? "bg-rose-50/80 border-rose-200 text-rose-950"
                      : "bg-emerald-50/80 border-emerald-200 text-emerald-950"
                  }`}>
                    <div>
                      <p className="text-[11px] font-semibold uppercase tracking-wider opacity-75">Sisa Saldo Cuti Tahunan ({employeeDetailData.year})</p>
                      <p className="text-3xl font-black mt-1">
                        {employeeDetailData.is_exceeded
                          ? `-${employeeDetailData.excess_days.toFixed(1)} Hari`
                          : `${employeeDetailData.remaining_days.toFixed(1)} Hari`}
                      </p>
                      <p className="text-xs mt-1 opacity-80">
                        Jatah Kuota: <strong>{employeeDetailData.total_quota} Hari</strong> &bull; Terpakai: <strong>{employeeDetailData.used_days.toFixed(1)} Hari</strong>
                      </p>
                    </div>
                    <div>
                      {employeeDetailData.is_exceeded ? (
                        <span className="px-3.5 py-1.5 rounded-full text-xs font-bold bg-rose-200/80 text-rose-900 border border-rose-300 shadow-2xs">
                          Kelebihan Cuti (+{employeeDetailData.excess_days.toFixed(1)}h)
                        </span>
                      ) : (
                        <span className="px-3.5 py-1.5 rounded-full text-xs font-semibold bg-emerald-200/80 text-emerald-900 border border-emerald-300 shadow-2xs">
                          Saldo Aman (Sisa {employeeDetailData.remaining_days.toFixed(1)}h)
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Breakdown Grid 6 Perizinan */}
                  <div>
                    <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider mb-2.5">
                      Rincian Berdasarkan Kategori ({employeeDetailData.year})
                    </h3>
                    <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5">
                      <div className="p-3 rounded-xl border border-slate-200 bg-slate-50/60">
                        <span className="text-slate-500 block text-[11px]">Cuti Tahunan (1.0)</span>
                        <span className="font-extrabold text-slate-900 text-base mt-0.5 block">
                          {employeeDetailData.breakdown.cuti_tahunan.days.toFixed(1)} Hari
                        </span>
                        <span className="text-[10px] text-slate-400 block mt-0.5">({employeeDetailData.breakdown.cuti_tahunan.count} kali pengajuan)</span>
                      </div>

                      <div className="p-3 rounded-xl border border-amber-200 bg-amber-50/60">
                        <span className="text-amber-800 block text-[11px]">Cuti 1/2 Hari (CS - 0.5)</span>
                        <span className="font-extrabold text-amber-950 text-base mt-0.5 block">
                          {employeeDetailData.breakdown.cuti_setengah.days.toFixed(1)} Hari
                        </span>
                        <span className="text-[10px] text-amber-700 block mt-0.5">({employeeDetailData.breakdown.cuti_setengah.count} kali pengajuan)</span>
                      </div>

                      <div className="p-3 rounded-xl border border-slate-200 bg-slate-50/60">
                        <span className="text-slate-500 block text-[11px]">Sakit (SKD)</span>
                        <span className="font-extrabold text-slate-900 text-base mt-0.5 block">
                          {employeeDetailData.breakdown.sakit.days.toFixed(1)} Hari
                        </span>
                        <span className="text-[10px] text-slate-400 block mt-0.5">({employeeDetailData.breakdown.sakit.count} kali pengajuan)</span>
                      </div>

                      <div className="p-3 rounded-xl border border-slate-200 bg-slate-50/60">
                        <span className="text-slate-500 block text-[11px]">Izin Pulang Cepat</span>
                        <span className="font-extrabold text-slate-900 text-base mt-0.5 block">
                          {employeeDetailData.breakdown.izin_pulang_cepat.count} Kali
                        </span>
                        <span className="text-[10px] text-slate-400 block mt-0.5">Izin keluar jam kerja</span>
                      </div>

                      <div className="p-3 rounded-xl border border-slate-200 bg-slate-50/60">
                        <span className="text-slate-500 block text-[11px]">Izin Datang Telat</span>
                        <span className="font-extrabold text-slate-900 text-base mt-0.5 block">
                          {employeeDetailData.breakdown.izin_telat.count} Kali
                        </span>
                        <span className="text-[10px] text-slate-400 block mt-0.5">Izin masuk terlambat</span>
                      </div>

                      <div className="p-3 rounded-xl border border-indigo-200 bg-indigo-50/50">
                        <span className="text-indigo-700 block text-[11px]">Absensi Jarak Jauh</span>
                        <span className="font-extrabold text-indigo-950 text-base mt-0.5 block">
                          {employeeDetailData.breakdown.absensi_jarak_jauh.count} Hari
                        </span>
                        <span className="text-[10px] text-indigo-500 block mt-0.5">Hari kerja valid</span>
                      </div>
                    </div>
                  </div>

                  {/* Tabel Riwayat Pengajuan Cuti */}
                  <div className="pt-2">
                    <h3 className="text-xs font-bold text-slate-800 uppercase tracking-wider mb-2">
                      Riwayat Permohonan ({employeeDetailData.history.length})
                    </h3>
                    {employeeDetailData.history.length === 0 ? (
                      <p className="text-xs text-slate-400 py-3 text-center border border-dashed rounded-lg">Belum ada riwayat permohonan di tahun ini.</p>
                    ) : (
                      <div className="max-h-56 overflow-y-auto border border-slate-200 rounded-xl overflow-hidden shadow-2xs">
                        <table className="w-full text-[11px] text-left">
                          <thead className="bg-slate-50 border-b border-slate-200 font-semibold text-slate-600 uppercase tracking-wider text-[10px]">
                            <tr>
                              <th className="px-3.5 py-2.5">Tanggal</th>
                              <th className="px-3.5 py-2.5">Kategori</th>
                              <th className="px-3.5 py-2.5">Alasan</th>
                              <th className="px-3.5 py-2.5 text-right">Status</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-slate-100 text-slate-700">
                            {employeeDetailData.history.map((h: any) => {
                              const katObj = KATEGORI_MAP[h.kategori] || { label: h.kategori, badge: "bg-slate-50 text-slate-700" };
                              return (
                                <tr key={h.id} className="hover:bg-slate-50/80 transition-colors">
                                  <td className="px-3.5 py-2 font-mono text-slate-800 font-medium">
                                    {h.tanggal_mulai === h.tanggal_selesai ? h.tanggal_mulai : `${h.tanggal_mulai} s/d ${h.tanggal_selesai}`}
                                  </td>
                                  <td className="px-3.5 py-2">
                                    <span className={`inline-block text-[10px] font-semibold px-2 py-0.5 rounded border ${katObj.badge}`}>
                                      {katObj.label}
                                    </span>
                                  </td>
                                  <td className="px-3.5 py-2 text-slate-600 max-w-[150px] truncate" title={h.alasan || "-"}>
                                    {h.alasan || "-"}
                                  </td>
                                  <td className="px-3.5 py-2 text-right font-semibold">
                                    <span className={
                                      h.status === "APPROVED" ? "text-emerald-700 bg-emerald-50 px-2 py-0.5 rounded-full border border-emerald-200" :
                                      h.status === "PENDING" ? "text-amber-700 bg-amber-50 px-2 py-0.5 rounded-full border border-amber-200" :
                                      "text-rose-700 bg-rose-50 px-2 py-0.5 rounded-full border border-rose-200"
                                    }>
                                      {h.status === "APPROVED" ? "Disetujui" : h.status === "PENDING" ? "Pending" : "Ditolak"}
                                    </span>
                                  </td>
                                </tr>
                              );
                            })}
                          </tbody>
                        </table>
                      </div>
                    )}
                  </div>
                </>
              ) : (
                /* Tab LEDGER MUTASI KUOTA */
                <div className="space-y-3">
                  <div className="p-3 bg-slate-50 rounded-xl border border-slate-200 text-[11px] text-slate-600 flex items-center justify-between">
                    <span>Audit buku besar mutasi saldo kuota cuti tahunan (Ledger).</span>
                    <span className="font-semibold text-slate-700">Tahun {balanceYear}</span>
                  </div>

                  {employeeLedgerData.length === 0 ? (
                    <div className="py-12 text-center text-slate-400 border border-dashed rounded-xl">
                      Belum ada entri mutasi ledger kuota cuti untuk karyawan ini di tahun {balanceYear}.
                    </div>
                  ) : (
                    <div className="border border-slate-200 rounded-xl overflow-hidden shadow-2xs max-h-72 overflow-y-auto">
                      <table className="w-full text-left text-[11px]">
                        <thead className="bg-slate-50 border-b border-slate-200 text-[10px] font-semibold text-slate-600 uppercase tracking-wider sticky top-0">
                          <tr>
                            <th className="px-3 py-2.5">Waktu</th>
                            <th className="px-3 py-2.5">Tipe Mutasi</th>
                            <th className="px-3 py-2.5 text-right">Jumlah</th>
                            <th className="px-3 py-2.5">Keterangan</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 text-slate-700">
                          {employeeLedgerData.map((entry: any) => {
                            const isPositive = entry.amount > 0;
                            const typeLabels: Record<string, { label: string; badge: string }> = {
                              GRANT_ANNIVERSARY: { label: "Anniversary (+)", badge: "bg-emerald-50 text-emerald-700 border-emerald-200" },
                              GRANT_ANNUAL_RESET: { label: "Reset Tahunan (+)", badge: "bg-indigo-50 text-indigo-700 border-indigo-200" },
                              USED: { label: "Pemotongan Cuti (-)", badge: "bg-rose-50 text-rose-700 border-rose-200" },
                              REVERSED: { label: "Pengembalian (+)", badge: "bg-amber-50 text-amber-700 border-amber-200" },
                              EXPIRED: { label: "Hangus / Expired (-)", badge: "bg-slate-100 text-slate-600 border-slate-200" },
                            };
                            const tInfo = typeLabels[entry.entry_type] || { label: entry.entry_type, badge: "bg-slate-50 text-slate-700 border-slate-200" };
                            return (
                              <tr key={entry.id} className="hover:bg-slate-50/80">
                                <td className="px-3 py-2 text-slate-500 font-mono text-[10px]">
                                  {new Date(entry.created_at).toLocaleDateString("id-ID", {
                                    day: "2-digit",
                                    month: "short",
                                    year: "numeric",
                                  })}
                                </td>
                                <td className="px-3 py-2">
                                  <span className={`inline-block px-2 py-0.5 rounded text-[10px] font-semibold border ${tInfo.badge}`}>
                                    {tInfo.label}
                                  </span>
                                </td>
                                <td className={`px-3 py-2 text-right font-bold ${isPositive ? "text-emerald-700" : "text-rose-600"}`}>
                                  {isPositive ? `+${entry.amount.toFixed(1)}` : `${entry.amount.toFixed(1)}`} Hari
                                </td>
                                <td className="px-3 py-2 text-slate-600 max-w-[220px] truncate" title={entry.note || "-"}>
                                  {entry.note || "-"}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="px-6 py-3 border-t border-slate-100 bg-slate-50/50 flex justify-end">
              <button
                type="button"
                onClick={() => setDetailModalOpen(false)}
                className="px-4 py-2 rounded-xl bg-slate-800 text-white font-semibold text-xs hover:bg-slate-900 transition-colors cursor-pointer"
              >
                Tutup
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ===== MODAL PREVIEW FOTO BUKTI / SKD ===== */}
      {previewMediaUrl && (
        <div
          className="fixed inset-0 z-[9999] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
          onClick={() => { setPreviewMediaUrl(null); setPreviewMediaTitle(""); }}
        >
          <div
            className="relative bg-white rounded-2xl shadow-2xl overflow-hidden max-w-3xl w-full max-h-[90vh] flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="flex items-center justify-between px-5 py-3.5 border-b border-slate-100 bg-slate-50">
              <div className="flex items-center gap-2.5 min-w-0">
                <svg className="w-4 h-4 text-indigo-500 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="3" y="3" width="18" height="18" rx="2" ry="2" />
                  <circle cx="8.5" cy="8.5" r="1.5" />
                  <polyline points="21 15 16 10 5 21" />
                </svg>
                <span className="text-xs font-semibold text-slate-800 truncate">{previewMediaTitle || "Foto Bukti"}</span>
              </div>
              <div className="flex items-center gap-2 shrink-0 ml-3">
                <a
                  href={previewMediaUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold bg-indigo-600 text-white hover:bg-indigo-700 transition-colors"
                  title="Buka di tab baru"
                >
                  <svg className="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
                    <polyline points="15 3 21 3 21 9" />
                    <line x1="10" y1="14" x2="21" y2="3" />
                  </svg>
                  Buka
                </a>
                <button
                  type="button"
                  onClick={() => { setPreviewMediaUrl(null); setPreviewMediaTitle(""); }}
                  className="p-1.5 rounded-lg text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
                  title="Tutup"
                >
                  <svg className="w-4 h-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                  </svg>
                </button>
              </div>
            </div>

            {/* Image Body */}
            <div className="flex-1 overflow-auto bg-slate-100 flex items-center justify-center p-4 min-h-[300px]">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={previewMediaUrl}
                alt={previewMediaTitle || "Foto Bukti"}
                className="max-w-full max-h-[68vh] rounded-lg object-contain shadow-lg"
                onError={(e) => {
                  const img = e.target as HTMLImageElement;
                  img.style.display = "none";
                  const parent = img.parentElement;
                  if (parent && !parent.querySelector(".img-error-msg")) {
                    const msg = document.createElement("div");
                    msg.className = "img-error-msg text-center text-slate-400 text-sm py-12 px-6";
                    msg.innerHTML = "⚠️ Gagal memuat gambar.<br/><small>Coba klik tombol <strong>Buka</strong> di atas untuk melihat file langsung.</small>";
                    parent.appendChild(msg);
                  }
                }}
              />
            </div>

            {/* Footer hint */}
            <div className="px-5 py-2.5 border-t border-slate-100 bg-slate-50 text-[10px] text-slate-400 text-center">
              Klik di luar gambar untuk menutup · Atau klik tombol <strong>Buka</strong> untuk melihat full size
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
