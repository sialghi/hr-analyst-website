"use client";
import { useEffect, useState } from "react";
import { api, isHrMaster, getRole } from "@/lib/api";
import { PageHeader, Card, Field, Button, Banner, inputCls, inputStyle } from "@/components/ui";
import { useRouter } from "next/navigation";

interface UserRow { id: number; nama: string; email: string; role: "hr_master" | "hr_staff"; }

export default function PenggunaPage() {
  const router = useRouter();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ nama: "", email: "", password: "", role: "hr_staff" });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (getRole() !== "hr_master") {
      router.replace("/dashboard");
      return;
    }
    load();
  }, []);

  function load() {
    api.getUsers().then(setUsers).catch((e) => setError(e.message));
  }

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      await api.createUser(form);
      setShowForm(false);
      setForm({ nama: "", email: "", password: "", role: "hr_staff" });
      load();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: number, nama: string) {
    if (!confirm(`Hapus akun "${nama}"?`)) return;
    try {
      await api.deleteUser(id);
      load();
    } catch (err: any) {
      alert(err.message);
    }
  }

  if (!isHrMaster()) return null;

  return (
    <div>
      <PageHeader
        title="Pengguna"
        description="Kelola akun HR Master dan HR Staff yang bisa mengakses sistem ini."
        action={<Button onClick={() => setShowForm(true)}>+ Tambah Pengguna</Button>}
      />

      {error && <Banner kind="error">{error}</Banner>}

      <Card className="p-0 overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b text-left" style={{ borderColor: "var(--line)", color: "var(--text-muted)" }}>
              <th className="px-4 py-3 font-medium">Nama</th>
              <th className="px-4 py-3 font-medium">Email</th>
              <th className="px-4 py-3 font-medium">Peran</th>
              <th className="px-4 py-3 font-medium text-right">Aksi</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => (
              <tr key={u.id} className="border-b last:border-0" style={{ borderColor: "var(--line)" }}>
                <td className="px-4 py-3" style={{ color: "var(--ink)" }}>{u.nama}</td>
                <td className="px-4 py-3">{u.email}</td>
                <td className="px-4 py-3">{u.role === "hr_master" ? "HR Master" : "HR Staff"}</td>
                <td className="px-4 py-3 text-right">
                  <button onClick={() => handleDelete(u.id, u.nama)} className="text-xs underline" style={{ color: "var(--clay)" }}>Hapus</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {showForm && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50" style={{ background: "rgba(21,34,48,0.5)" }}>
          <form onSubmit={handleCreate} className="bg-white rounded-lg p-6 w-full max-w-sm space-y-4">
            <h3 className="text-base font-semibold" style={{ color: "var(--ink)" }}>Tambah Pengguna</h3>
            {error && <Banner kind="error">{error}</Banner>}
            <Field label="Nama"><input required className={inputCls} style={inputStyle} value={form.nama} onChange={(e) => setForm({ ...form, nama: e.target.value })} /></Field>
            <Field label="Email"><input type="email" required className={inputCls} style={inputStyle} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></Field>
            <Field label="Password Awal"><input type="password" required className={inputCls} style={inputStyle} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></Field>
            <Field label="Peran">
              <select className={inputCls} style={inputStyle} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
                <option value="hr_staff">HR Staff (hanya lihat & proses absensi)</option>
                <option value="hr_master">HR Master (bisa ubah aturan bisnis)</option>
              </select>
            </Field>
            <div className="flex justify-end gap-3 pt-2">
              <Button variant="secondary" onClick={() => setShowForm(false)}>Batal</Button>
              <Button type="submit" disabled={saving}>{saving ? "Menyimpan..." : "Simpan"}</Button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}
