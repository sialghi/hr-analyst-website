"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { PageHeader, Card } from "@/components/ui";

interface ExpiringContractItem {
  employee_id: number;
  nama: string;
  cabang: string | null;
  profile_code: string;
  join_date: string | null;
  tenure_display: string;
  contract_id: number;
  contract_number: number;
  start_date: string;
  end_date: string;
  days_left: number;
  status_label: string;
  is_expired: boolean;
  message: string;
}

export default function Dashboard() {
  const [profileCount, setProfileCount] = useState<number | null>(null);
  const [employeeCount, setEmployeeCount] = useState<number | null>(null);
  const [holidayCount, setHolidayCount] = useState<number | null>(null);
  const [expiringContracts, setExpiringContracts] = useState<ExpiringContractItem[]>([]);
  const [reminderConfigDays, setReminderConfigDays] = useState<number>(10);
  const [loadingContracts, setLoadingContracts] = useState<boolean>(true);

  useEffect(() => {
    api.getProfiles().then((d) => setProfileCount(d.length)).catch(() => {});
    api.getEmployees().then((d) => setEmployeeCount(d.length)).catch(() => {});
    api.getHolidays().then((d) => setHolidayCount(d.length)).catch(() => {});

    api.getExpiringContracts()
      .then((res) => {
        setExpiringContracts(res.data || []);
        if (res.reminder_days_config) setReminderConfigDays(res.reminder_days_config);
      })
      .catch(() => {})
      .finally(() => setLoadingContracts(false));
  }, []);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Ringkasan Sistem"
        description="Gambaran konfigurasi aturan bisnis, master karyawan, status kontrak kerja PKWT, dan operasional absensi."
      />

      {/* Top Stat Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-5">
        <StatCard
          label="Profil & Aturan Divisi"
          value={profileCount}
          href="/aturan-bisnis"
          desc="Jadwal jam kerja & lembur aktif"
          icon={
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--text-muted)" }}>
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z" />
              <circle cx="12" cy="12" r="3" />
            </svg>
          }
        />
        <StatCard
          label="Karyawan Terdaftar"
          value={employeeCount}
          href="/karyawan"
          desc="Database karyawan terintegrasi"
          icon={
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--text-muted)" }}>
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
          }
        />
        <StatCard
          label={`Kontrak Segera Berakhir (H-${reminderConfigDays})`}
          value={expiringContracts.length}
          href="/karyawan"
          desc="Karyawan PKWT perlu ditindaklanjuti"
          highlight={expiringContracts.length > 0}
          icon={
            <svg className="w-5 h-5 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
              <line x1="12" y1="9" x2="12" y2="13" />
              <line x1="12" y1="17" x2="12.01" y2="17" />
            </svg>
          }
        />
        <StatCard
          label="Tanggal Merah Tersimpan"
          value={holidayCount}
          href="/tanggal-merah"
          desc="Hari libur nasional & cuti bersama"
          icon={
            <svg className="w-5 h-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ color: "var(--text-muted)" }}>
              <rect width="18" height="18" x="3" y="4" rx="2" ry="2" />
              <line x1="16" x2="16" y1="2" y2="6" />
              <line x1="8" x2="8" y1="2" y2="6" />
              <line x1="3" x2="21" y1="10" y2="10" />
            </svg>
          }
        />
      </div>

      {/* Widget Reminder Kontrak Segera Berakhir */}
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-2xs">
        <div className="flex items-center justify-between border-b border-slate-100 pb-4 mb-4">
          <div>
            <h2 className="text-base font-bold text-slate-900">
              Widget Reminder Kontrak PKWT (H-{reminderConfigDays})
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Daftar karyawan kontrak PKWT yang habis masa berlakunya dalam {reminderConfigDays} hari ke depan atau sudah lewat, diurutkan dari yang terdekat.
            </p>
          </div>
          <Link
            href="/karyawan"
            className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 transition-colors"
          >
            Lihat Semua Karyawan →
          </Link>
        </div>

        {loadingContracts ? (
          <div className="p-6 text-center text-xs text-slate-400">Memuat data reminder kontrak...</div>
        ) : expiringContracts.length === 0 ? (
          <div className="p-6 text-center text-xs text-emerald-700 bg-emerald-50/50 rounded-xl border border-emerald-200/60">
            Tidak ada kontrak PKWT yang akan berakhir dalam waktu dekat ({reminderConfigDays} hari). Semua kontrak karyawan aman.
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-[11px] font-semibold text-slate-600 uppercase tracking-wider border-b border-slate-200">
                <tr>
                  <th className="px-4 py-3">Nama Karyawan</th>
                  <th className="px-4 py-3">Cabang / Divisi</th>
                  <th className="px-4 py-3">Masa Kerja</th>
                  <th className="px-4 py-3">Periode Kontrak</th>
                  <th className="px-4 py-3">Status Kontrak</th>
                  <th className="px-4 py-3 text-right">Aksi HR</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700">
                {expiringContracts.map((item) => {
                  const startDisplay = new Date(item.start_date).toLocaleDateString("id-ID");
                  const endDisplay = new Date(item.end_date).toLocaleDateString("id-ID");

                  return (
                    <tr key={item.employee_id} className="hover:bg-slate-50 transition-colors">
                      <td className="px-4 py-3 font-semibold text-slate-900">
                        {item.nama}
                        <span className="block text-[10px] text-slate-400 font-normal">
                          PKWT Kontrak #{item.contract_number}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-medium text-slate-800">{item.cabang || "Pusat"}</span>
                        <span className="block text-[10px] text-slate-400">{item.profile_code}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-medium text-slate-800">{item.tenure_display}</span>
                        {item.join_date && (
                          <span className="block text-[10px] text-slate-400">
                            Join: {new Date(item.join_date).toLocaleDateString("id-ID")}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-600">
                        {startDisplay} s/d <strong className="text-slate-900">{endDisplay}</strong>
                      </td>
                      <td className="px-4 py-3">
                        {item.is_expired ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-rose-50 text-rose-700 border border-rose-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-rose-500" />
                            Berakhir {Math.abs(item.days_left)} hari lalu
                          </span>
                        ) : item.days_left === 0 ? (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-800 border border-amber-300">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                            Berakhir Hari Ini!
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[10px] font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                            <span className="w-1.5 h-1.5 rounded-full bg-amber-500" />
                            Sisa {item.days_left} Hari
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <Link
                          href={`/karyawan?edit=${item.employee_id}`}
                          className="inline-flex items-center gap-1 px-3 py-1 rounded-lg bg-indigo-50 text-indigo-700 font-semibold hover:bg-indigo-100 transition-colors border border-indigo-200 text-[11px]"
                        >
                          Kelola Kontrak →
                        </Link>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <ActionCard
          title="Atur Jadwal & Divisi"
          desc="Sesuaikan jam masuk, jam pulang, toleransi telat, dan aturan lembur per profil divisi."
          href="/aturan-bisnis"
        />
        <ActionCard
          title="Kelola Master Karyawan"
          desc="Sinkronisasi status TETAP/PKWT, tanggal join, perpanjangan kontrak, dan penugasan profil kerja."
          href="/karyawan"
        />
        <ActionCard
          title="Jalankan Proses Absensi"
          desc="Unggah log mesin absensi mentah dan dapatkan laporan 14 sheet interaktif & file Excel."
          href="/proses"
          primary
        />
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
  href,
  desc,
  icon,
  highlight,
}: {
  label: string;
  value: number | null;
  href: string;
  desc?: string;
  icon?: React.ReactNode;
  highlight?: boolean;
}) {
  return (
    <Link href={href} className="group">
      <Card className={`hover:border-slate-300 hover:shadow-xs transition-colors duration-150 p-5 flex flex-col justify-between h-full ${
        highlight ? "bg-amber-50/40 border-amber-200" : ""
      }`}>
        <div className="flex items-start justify-between">
          <span className="text-xs font-medium" style={{ color: "var(--text-muted)" }}>
            {label}
          </span>
          {icon}
        </div>
        <div className="mt-4">
          <div className={`text-3xl font-extrabold tabular ${highlight ? "text-amber-900" : ""}`} style={!highlight ? { color: "var(--ink)" } : {}}>
            {value === null ? "—" : value.toLocaleString("id-ID")}
          </div>
          {desc && <div className="text-xs font-medium mt-1" style={{ color: "var(--text-muted)" }}>{desc}</div>}
        </div>
      </Card>
    </Link>
  );
}

function ActionCard({
  title,
  desc,
  href,
  primary,
}: {
  title: string;
  desc: string;
  href: string;
  primary?: boolean;
}) {
  return (
    <Link href={href} className="group">
      <div
        className={`h-full rounded-xl border p-5 transition-colors duration-150 flex flex-col justify-between ${
          primary
            ? "text-white hover:opacity-95 shadow-xs"
            : "bg-white border-slate-200/90 text-slate-800 hover:border-slate-300 hover:shadow-xs"
        }`}
        style={primary ? { background: "var(--accent)", borderColor: "var(--accent)" } : {}}
      >
        <div>
          <h3 className={`text-base font-bold mb-1.5 ${primary ? "text-white" : ""}`} style={!primary ? { color: "var(--ink)" } : {}}>
            {title}
          </h3>
          <p className={`text-xs leading-relaxed ${primary ? "opacity-85" : ""}`} style={!primary ? { color: "var(--text-muted)" } : {}}>
            {desc}
          </p>
        </div>
        <div className={`mt-4 pt-3 flex items-center justify-between text-xs font-medium border-t ${
          primary ? "border-white/20" : ""
        }`} style={!primary ? { borderColor: "var(--line)", color: "var(--text-muted)" } : {}}>
          <span>Buka Halaman</span>
          <span className="transition-transform group-hover:translate-x-1">→</span>
        </div>
      </div>
    </Link>
  );
}
