"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api } from "@/lib/api";
import { PageHeader, Card } from "@/components/ui";

export default function Dashboard() {
  const [profileCount, setProfileCount] = useState<number | null>(null);
  const [employeeCount, setEmployeeCount] = useState<number | null>(null);
  const [holidayCount, setHolidayCount] = useState<number | null>(null);

  useEffect(() => {
    api.getProfiles().then((d) => setProfileCount(d.length)).catch(() => {});
    api.getEmployees().then((d) => setEmployeeCount(d.length)).catch(() => {});
    api.getHolidays().then((d) => setHolidayCount(d.length)).catch(() => {});
  }, []);

  return (
    <div>
      <PageHeader
        title="Ringkasan Sistem"
        description="Gambaran konfigurasi aturan bisnis, master karyawan, dan status operasional sistem absensi saat ini."
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-5 mb-8">
        <StatCard
          label="Profil & Aturan Divisi"
          value={profileCount}
          href="/aturan-bisnis"
          desc="Jadwal jam kerja & lembur aktif"
          icon={
            <svg className="w-5 h-5 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
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
            <svg className="w-5 h-5 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
              <circle cx="9" cy="7" r="4" />
              <path d="M22 21v-2a4 4 0 0 0-3-3.87" />
              <path d="M16 3.13a4 4 0 0 1 0 7.75" />
            </svg>
          }
        />
        <StatCard
          label="Tanggal Merah Tersimpan"
          value={holidayCount}
          href="/tanggal-merah"
          desc="Hari libur nasional & cuti bersama"
          icon={
            <svg className="w-5 h-5 text-indigo-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <rect width="18" height="18" x="3" y="4" rx="2" ry="2" />
              <line x1="16" x2="16" y1="2" y2="6" />
              <line x1="8" x2="8" y1="2" y2="6" />
              <line x1="3" x2="21" y1="10" y2="10" />
            </svg>
          }
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        <ActionCard
          title="Atur Jadwal & Divisi"
          desc="Sesuaikan jam masuk, jam pulang, toleransi telat, dan aturan lembur per profil divisi."
          href="/aturan-bisnis"
          badge="Aturan Kerja"
        />
        <ActionCard
          title="Kelola Master Karyawan"
          desc="Sinkronisasi NIK, nama lengkap, penugasan profil kerja, dan cabang masing-masing staf."
          href="/karyawan"
          badge="Database"
        />
        <ActionCard
          title="Jalankan Proses Absensi"
          desc="Unggah log mesin absensi mentah dan dapatkan laporan 14 sheet interaktif & file Excel."
          href="/proses"
          badge="Pipeline Utama"
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
}: {
  label: string;
  value: number | null;
  href: string;
  desc?: string;
  icon?: React.ReactNode;
}) {
  return (
    <Link href={href} className="group">
      <Card className="hover:border-slate-300 hover:shadow-xs transition-colors duration-150 p-5 flex flex-col justify-between h-full">
        <div className="flex items-start justify-between">
          <span className="text-xs font-semibold text-slate-500">
            {label}
          </span>
          <div className="p-2 rounded-lg bg-indigo-50 group-hover:bg-indigo-100 transition-colors">
            {icon}
          </div>
        </div>
        <div className="mt-4">
          <div className="text-3xl font-extrabold text-slate-900 tabular">
            {value === null ? "—" : value.toLocaleString("id-ID")}
          </div>
          {desc && <div className="text-xs text-slate-400 font-medium mt-1">{desc}</div>}
        </div>
      </Card>
    </Link>
  );
}

function ActionCard({
  title,
  desc,
  href,
  badge,
  primary,
}: {
  title: string;
  desc: string;
  href: string;
  badge: string;
  primary?: boolean;
}) {
  return (
    <Link href={href} className="group">
      <div
        className={`h-full rounded-xl border p-5 transition-colors duration-150 flex flex-col justify-between ${
          primary
            ? "bg-indigo-600 text-white border-indigo-600 hover:bg-indigo-700 shadow-xs"
            : "bg-white border-slate-200/90 text-slate-800 hover:border-slate-300 hover:shadow-xs"
        }`}
      >
        <div>
          <span
            className={`text-xs font-semibold px-2 py-0.5 rounded-md inline-block mb-3 ${
              primary ? "bg-indigo-700 text-indigo-100" : "bg-slate-100 text-slate-600"
            }`}
          >
            {badge}
          </span>
          <h3 className={`text-base font-bold mb-1.5 ${primary ? "text-white" : "text-slate-900"}`}>
            {title}
          </h3>
          <p className={`text-xs leading-relaxed ${primary ? "text-indigo-100" : "text-slate-500"}`}>
            {desc}
          </p>
        </div>
        <div className={`mt-4 pt-3 flex items-center justify-between text-xs font-semibold ${
          primary ? "text-white border-t border-white/20" : "text-indigo-600 border-t border-slate-100"
        }`}>
          <span>Buka Halaman</span>
          <span className="transition-transform group-hover:translate-x-1">→</span>
        </div>
      </div>
    </Link>
  );
}
