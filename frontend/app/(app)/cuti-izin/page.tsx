"use client";
import { useEffect, useState, useMemo } from "react";
import { api, isHrMaster } from "@/lib/api";

interface LeaveItem {
  id: number;
  nama: string;
  telegram_user_id?: string | null;
  kategori: string;
  tanggal_mulai: string;
  tanggal_selesai: string;
  jam_izin?: string | null;
  alasan?: string | null;
  catatan_hr?: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED";
  approved_by?: string | null;
  approved_at?: string | null;
  created_at: string;
}

const KATEGORI_MAP: Record<string, { label: string; badge: string }> = {
  CUTI_TAHUNAN: { label: "Cuti Tahunan", badge: "bg-blue-50 text-blue-700 border-blue-200" },
  SAKIT: { label: "Sakit (SKD)", badge: "bg-amber-50 text-amber-700 border-amber-200" },
  IZIN_PULANG_CEPAT: { label: "Izin Pulang Cepat", badge: "bg-purple-50 text-purple-700 border-purple-200" },
  IZIN_TELAT: { label: "Izin Datang Terlambat", badge: "bg-orange-50 text-orange-700 border-orange-200" },
  LAINNYA: { label: "Izin Lainnya", badge: "bg-slate-50 text-slate-700 border-slate-200" },
};

export default function CutiIzinPage() {
  const [leaves, setLeaves] = useState<LeaveItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterStatus, setFilterStatus] = useState<string>("ALL");
  const [filterKategori, setFilterKategori] = useState<string>("ALL");
  const [searchNama, setSearchNama] = useState<string>("");

  // Modal tambah
  const [modalOpen, setModalOpen] = useState(false);
  const [formNama, setFormNama] = useState("");
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
      const data = await api.getLeaves();
      setLeaves(data);
    } catch (err: any) {
      setError(err.message || "Gagal memuat data cuti & izin.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!formNama.trim() || !formTglMulai || !formTglSelesai) {
      alert("Nama dan tanggal wajib diisi.");
      return;
    }
    setSaving(true);
    try {
      await api.createLeave({
        nama: formNama.trim(),
        kategori: formKategori,
        tanggal_mulai: formTglMulai,
        tanggal_selesai: formTglSelesai,
        jam_izin: formJamIzin.trim() || null,
        alasan: formAlasan.trim() || null,
      });
      setModalOpen(false);
      // Reset form
      setFormNama("");
      setFormTglMulai("");
      setFormTglSelesai("");
      setFormJamIzin("");
      setFormAlasan("");
      await loadData();
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
    } catch (err: any) {
      alert(err.message || "Gagal menghapus permohonan.");
    }
  }

  const filteredLeaves = useMemo(() => {
    return leaves.filter((item) => {
      if (filterStatus !== "ALL" && item.status !== filterStatus) return false;
      if (filterKategori !== "ALL" && item.kategori !== filterKategori) return false;
      if (searchNama && !item.nama.toLowerCase().includes(searchNama.toLowerCase())) return false;
      return true;
    });
  }, [leaves, filterStatus, filterKategori, searchNama]);

  // Statistik ringkas
  const countPending = leaves.filter((l) => l.status === "PENDING").length;
  const countApproved = leaves.filter((l) => l.status === "APPROVED").length;
  const countRejected = leaves.filter((l) => l.status === "REJECTED").length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Manajemen Cuti & Izin</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Daftar pengajuan izin dan cuti resmi (dari Telegram Bot atau Web) untuk bypass anomali absensi.
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

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
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
      </div>

      {/* Filter Bar */}
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
            <option value="CUTI_TAHUNAN">Cuti Tahunan</option>
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

      {/* Table */}
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
                  <th className="px-4 py-3">Periode / Jam</th>
                  <th className="px-4 py-3">Alasan</th>
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
                    <tr key={item.id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="px-4 py-3 font-semibold text-slate-900">
                        {item.nama}
                        {item.telegram_user_id && (
                          <span className="block text-[10px] font-normal text-slate-400">
                            Telegram ID: {item.telegram_user_id}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-block text-[10px] font-semibold px-2 py-0.5 rounded-md border ${kat.badge}`}>
                          {kat.label}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-medium text-slate-800">{tglDisplay}</span>
                        {item.jam_izin && (
                          <span className="block text-[11px] text-purple-600 font-medium">
                            Pukul {item.jam_izin}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 max-w-xs truncate text-slate-600" title={item.alasan || "-"}>
                        {item.alasan || "-"}
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
              <div>
                <label className="block font-semibold text-slate-700 mb-1">Nama Karyawan *</label>
                <input
                  type="text"
                  required
                  placeholder="Contoh: Eri Mutaqin"
                  value={formNama}
                  onChange={(e) => setFormNama(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500"
                />
              </div>

              <div>
                <label className="block font-semibold text-slate-700 mb-1">Kategori Permohonan *</label>
                <select
                  value={formKategori}
                  onChange={(e) => setFormKategori(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 focus:outline-none focus:border-indigo-500 cursor-pointer"
                >
                  <option value="CUTI_TAHUNAN">Cuti Tahunan (Full Day)</option>
                  <option value="SAKIT">Izin Sakit / SKD (Full Day)</option>
                  <option value="IZIN_PULANG_CEPAT">Izin Pulang Lebih Awal (Parsial)</option>
                  <option value="IZIN_TELAT">Izin Datang Terlambat (Parsial)</option>
                  <option value="LAINNYA">Izin Lainnya</option>
                </select>
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
    </div>
  );
}
