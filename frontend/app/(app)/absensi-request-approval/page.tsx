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

export default function AbsensiRequestApprovalPage() {
  const [leaves, setLeaves] = useState<LeaveItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [filterStatus, setFilterStatus] = useState<string>("ALL");
  const [filterCabang, setFilterCabang] = useState<string>("ALL");
  const [searchNama, setSearchNama] = useState<string>("");

  // Photo modal state
  const [previewPhotoUrl, setPreviewPhotoUrl] = useState<string | null>(null);
  const [previewPhotoTitle, setPreviewPhotoTitle] = useState<string>("");

  // Action status loading ID
  const [actionLoadingId, setActionLoadingId] = useState<number | null>(null);

  const canApprove = isHrMaster();

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      // Ambil permohonan dengan kategori WORK_FROM_LOCATION (Absensi Jarak Jauh)
      const leavesData = await api.getRemoteAttendances();
      setLeaves(leavesData || []);
    } catch (err: any) {
      setError(err.message || "Gagal memuat data absensi jarak jauh.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  const cabangList = useMemo(() => {
    const s = new Set<string>();
    leaves.forEach((item) => {
      if (item.location_cabang && typeof item.location_cabang === "string") {
        s.add(item.location_cabang.trim());
      }
    });
    return Array.from(s).sort();
  }, [leaves]);

  async function handleStatus(id: number, status: "APPROVED" | "REJECTED") {
    const actionText = status === "APPROVED" ? "menyetujui" : "menolak";
    if (!confirm(`Apakah Anda yakin ingin ${actionText} absensi jarak jauh ini?`)) return;
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
    if (!confirm(`Hapus pengajuan absensi jarak jauh untuk ${nama}?`)) return;
    try {
      await api.deleteLeave(id);
      await loadData();
    } catch (err: any) {
      alert(err.message || "Gagal menghapus pengajuan.");
    }
  }

  const filteredLeaves = useMemo(() => {
    return leaves.filter((item) => {
      if (filterStatus !== "ALL" && item.status !== filterStatus) return false;
      if (filterCabang !== "ALL") {
        const itemCabang = item.location_cabang || "";
        if (!itemCabang.toLowerCase().includes(filterCabang.toLowerCase())) return false;
      }
      if (searchNama && !item.nama.toLowerCase().includes(searchNama.toLowerCase())) return false;
      return true;
    });
  }, [leaves, filterStatus, filterCabang, searchNama]);

  // General statistics
  const countPending = leaves.filter((l) => l.status === "PENDING").length;
  const countApproved = leaves.filter((l) => l.status === "APPROVED").length;
  const countRejected = leaves.filter((l) => l.status === "REJECTED").length;

  function getPhotoSrc(path?: string | null) {
    if (!path) return null;
    if (path.startsWith("http://") || path.startsWith("https://")) return path;
    return `${API_BASE}${path.startsWith("/") ? "" : "/"}${path}`;
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-slate-900 tracking-tight">Absensi Request Approval</h1>
          <p className="text-xs text-slate-500 mt-0.5">
            Daftar persetujuan Absensi Jarak Jauh (Work From Location) lengkap dengan verifikasi foto bukti dari Chatbot WhatsApp.
          </p>
        </div>
        <button
          onClick={loadData}
          className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl bg-slate-900 text-white text-xs font-semibold hover:bg-slate-800 transition-colors shadow-xs cursor-pointer shrink-0"
        >
          <span>Muat Ulang Data ↻</span>
        </button>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
        <div className="p-4 rounded-lg bg-white border border-slate-200">
          <p className="text-[11px] font-medium text-slate-500">Total Permohonan</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{leaves.length}</p>
          <p className="text-[11px] text-slate-400 mt-0.5">Absensi Jarak Jauh</p>
        </div>
        <div className="p-4 rounded-lg bg-slate-50 border border-slate-200">
          <p className="text-[11px] font-medium text-slate-600">Menunggu Approval</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{countPending}</p>
          <p className="text-[11px] text-slate-500 mt-0.5">Perlu verifikasi HR</p>
        </div>
        <div className="p-4 rounded-lg bg-slate-50 border border-slate-200">
          <p className="text-[11px] font-medium text-slate-600">Telah Disetujui</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{countApproved}</p>
          <p className="text-[11px] text-slate-500 mt-0.5">Masuk ke Hari Kerja Valid</p>
        </div>
        <div className="p-4 rounded-lg bg-slate-50 border border-slate-200">
          <p className="text-[11px] font-medium text-slate-600">Ditolak</p>
          <p className="text-2xl font-bold text-slate-900 mt-1">{countRejected}</p>
          <p className="text-[11px] text-slate-500 mt-0.5">Tidak menambah Hari Kerja Valid</p>
        </div>
      </div>

      {/* Filter Bar */}
      <div className="p-3.5 rounded-lg bg-white border border-slate-200 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2 flex-1">
          <input
            type="text"
            placeholder="Cari nama karyawan..."
            value={searchNama}
            onChange={(e) => setSearchNama(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-indigo-500 w-52"
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
            value={filterCabang}
            onChange={(e) => setFilterCabang(e.target.value)}
            className="text-xs px-2.5 py-1.5 rounded-lg border border-slate-200 bg-slate-50 text-slate-700 focus:outline-none focus:border-indigo-500 cursor-pointer"
          >
            <option value="ALL">Semua Cabang</option>
            {cabangList.map((cb) => (
              <option key={cb} value={cb}>{cb}</option>
            ))}
          </select>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-slate-200 bg-white overflow-hidden">
        {loading ? (
          <div className="p-8 text-center text-xs text-slate-400">Memuat data absensi jarak jauh...</div>
        ) : error ? (
          <div className="p-8 text-center text-xs text-rose-600 bg-rose-50/50">{error}</div>
        ) : filteredLeaves.length === 0 ? (
          <div className="p-8 text-center text-xs text-slate-400">
            Tidak ada permohonan absensi jarak jauh yang sesuai filter.
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
                  <th className="px-4 py-3 text-center">Foto</th>
                  <th className="px-4 py-3">Status</th>
                  <th className="px-4 py-3">Verifikator</th>
                  <th className="px-4 py-3 text-right">Aksi</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {filteredLeaves.map((item) => {
                  const photoSrc = getPhotoSrc(item.foto_bukti);
                  const isSameDay = item.tanggal_mulai === item.tanggal_selesai;
                  const tglDisplay = isSameDay
                    ? item.tanggal_mulai
                    : `${item.tanggal_mulai} s/d ${item.tanggal_selesai}`;

                  return (
                    <tr key={item.id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="px-4 py-3 font-semibold text-slate-900">
                        {item.nama}
                        {item.whatsapp_user_id && (
                          <span className="block text-[10px] font-normal text-emerald-700 mt-0.5">
                            WA: +{item.whatsapp_user_id}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span className="inline-block text-[10px] font-semibold px-2 py-0.5 rounded-md border bg-indigo-50 text-indigo-700 border-indigo-200">
                          Absensi Jarak Jauh
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[11px]">
                        {item.location_cabang ? (
                          <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded bg-slate-100 text-slate-700 font-medium">
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
                        {photoSrc ? (
                          <button
                            type="button"
                            onClick={() => {
                              setPreviewPhotoUrl(photoSrc);
                              setPreviewPhotoTitle(`${item.nama} - ${tglDisplay}`);
                            }}
                            className="group relative inline-block rounded-lg overflow-hidden border border-slate-200 shadow-2xs hover:border-indigo-500 transition-all cursor-pointer focus:outline-none"
                            title="Klik untuk melihat foto ukuran penuh"
                          >
                            {/* eslint-disable-next-line @next/next/no-img-element */}
                            <img
                              src={photoSrc}
                              alt="Foto Bukti"
                              className="w-12 h-12 object-cover rounded-lg group-hover:scale-105 transition-transform"
                            />
                            <div className="absolute inset-0 bg-black/20 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center text-white text-[10px] font-bold">
                              Lihat
                            </div>
                          </button>
                        ) : (
                          <span className="text-slate-300 text-[11px] italic">Tidak ada foto</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        {item.status === "PENDING" && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] font-medium bg-slate-100 text-slate-700 border border-slate-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                            Pending
                          </span>
                        )}
                        {item.status === "APPROVED" && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] font-medium bg-slate-100 text-slate-700 border border-slate-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
                            Disetujui
                          </span>
                        )}
                        {item.status === "REJECTED" && (
                          <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md text-[10px] font-medium bg-slate-100 text-slate-700 border border-slate-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-slate-500" />
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
                                title="Setujui Absensi Jarak Jauh"
                              >
                                Setujui
                              </button>
                              <button
                                onClick={() => handleStatus(item.id, "REJECTED")}
                                disabled={actionLoadingId === item.id}
                                className="px-2 py-1 rounded text-[11px] font-semibold bg-rose-50 text-rose-700 hover:bg-rose-100 border border-rose-200 transition-colors cursor-pointer disabled:opacity-50"
                                title="Tolak Absensi Jarak Jauh"
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

      {/* Modal Preview Foto Lightbox */}
      {previewPhotoUrl && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4 backdrop-blur-xs">
          <div className="w-full max-w-2xl bg-white rounded-2xl shadow-2xl overflow-hidden border border-slate-800">
            <div className="px-5 py-4 bg-slate-900 text-white flex items-center justify-between">
              <div>
                <h3 className="text-sm font-bold">Bukti Foto Absensi Jarak Jauh</h3>
                <p className="text-xs text-slate-400 mt-0.5">{previewPhotoTitle}</p>
              </div>
              <button
                onClick={() => setPreviewPhotoUrl(null)}
                className="w-7 h-7 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white flex items-center justify-center transition-colors cursor-pointer"
              >
                ✕
              </button>
            </div>
            <div className="p-4 bg-slate-950 flex items-center justify-center min-h-[300px] max-h-[80vh] overflow-auto">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={previewPhotoUrl}
                alt="Foto Bukti Absensi Jarak Jauh"
                className="max-w-full max-h-[70vh] object-contain rounded-lg shadow-lg"
              />
            </div>
            <div className="px-5 py-3 bg-slate-900 border-t border-slate-800 flex justify-end">
              <button
                onClick={() => setPreviewPhotoUrl(null)}
                className="px-4 py-1.5 rounded-lg bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold transition-colors cursor-pointer"
              >
                Tutup Preview
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
