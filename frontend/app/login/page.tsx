"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { api, setSession } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const data = await api.login(email, password);
      setSession(data.access_token, data.role, data.nama);
      router.push("/dashboard");
    } catch (err: any) {
      setError(err.message || "Gagal login. Periksa email/password Anda.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex bg-slate-900">
      {/* Left Branding Showcase */}
      <div className="hidden lg:flex lg:w-1/2 flex-col justify-between p-14 border-r border-slate-800 text-white relative">
        <div className="flex items-center gap-3">
          <div className="w-12 h-12 rounded-lg overflow-hidden bg-white flex items-center justify-center shrink-0 border border-slate-700/60 p-1">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src="/logo.png"
              alt="Logo PT. Javareef Indonesia Perkasa"
              className="w-full h-full object-contain"
            />
          </div>
          <div>
            <div className="text-base font-bold tracking-tight text-white">
              HR Analyst
            </div>
            <div className="text-xs text-slate-400 font-medium">
              PT. Javareef Indonesia Perkasa
            </div>
          </div>
        </div>

        <div className="max-w-lg">
          <h1 className="text-4xl font-extrabold leading-tight tracking-tight text-white mb-4">
            Satu tempat untuk aturan jam kerja, lembur, dan uang makan seluruh divisi.
          </h1>
          <p className="text-sm text-slate-400 leading-relaxed">
            Atur aturan jam baku per divisi, master karyawan, dan hari libur nasional. Laporan 14 sheet interaktif dan ekspor Excel akurat siap digunakan setiap bulan.
          </p>

          <div className="mt-8 grid grid-cols-2 gap-3 text-xs text-slate-300">
            <div className="p-3 rounded-lg bg-slate-800/80 border border-slate-700/80">
              <span className="font-semibold text-white block mb-0.5">14 Sheet Interaktif</span>
              <span className="text-slate-400">Kalkulasi presisi sesuai aturan</span>
            </div>
            <div className="p-3 rounded-lg bg-slate-800/80 border border-slate-700/80">
              <span className="font-semibold text-white block mb-0.5">Aturan Dinamis</span>
              <span className="text-slate-400">Konfigurasi baku per divisi</span>
            </div>
          </div>
        </div>

        <div className="text-xs text-slate-500">
          © {new Date().getFullYear()} HR Analyst Platform. All rights reserved.
        </div>
      </div>

      {/* Right Login Form */}
      <div className="flex-1 flex items-center justify-center p-6 sm:p-10 bg-slate-50">
        <div className="w-full max-w-md bg-white p-8 sm:p-10 rounded-2xl border border-slate-200/90 shadow-sm shadow-slate-900/5">
          <div className="mb-6">
            <h2 className="text-2xl font-bold tracking-tight text-slate-900">
              Masuk ke Akun
            </h2>
            <p className="text-xs text-slate-500 mt-1 font-medium">
              Gunakan email &amp; kata sandi yang telah didaftarkan oleh HR Master.
            </p>
          </div>

          {error && (
            <div className="mb-5 flex items-start gap-2.5 text-xs p-3 rounded-lg bg-rose-50 border border-rose-200 text-rose-700 font-medium">
              <svg className="w-4 h-4 shrink-0 text-rose-600 mt-0.5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.28 7.22a.75.75 0 00-1.06 1.06L8.94 10l-1.72 1.72a.75.75 0 101.06 1.06L10 11.06l1.72 1.72a.75.75 0 101.06-1.06L11.06 10l1.72-1.72a.75.75 0 00-1.06-1.06L10 8.94 8.28 7.22z" clipRule="evenodd" />
              </svg>
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                Alamat Email
              </label>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="nama@perusahaan.com"
                className="w-full px-3.5 py-2.5 rounded-lg border border-slate-200 bg-white text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/10 transition-colors shadow-xs"
              />
            </div>

            <div>
              <label className="block text-xs font-semibold text-slate-700 mb-1.5">
                Kata Sandi
              </label>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="••••••••"
                className="w-full px-3.5 py-2.5 rounded-lg border border-slate-200 bg-white text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/10 transition-colors shadow-xs"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full mt-2 py-2.5 px-4 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold shadow-xs transition-colors duration-150 disabled:opacity-50 cursor-pointer flex items-center justify-center gap-2"
            >
              {loading ? (
                <>
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  <span>Memeriksa kredensial...</span>
                </>
              ) : (
                "Masuk ke Dashboard"
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
