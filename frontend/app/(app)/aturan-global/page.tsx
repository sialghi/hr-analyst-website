"use client";
import { useEffect, useState } from "react";
import { api, isHrMaster } from "@/lib/api";
import { PageHeader, Card, Field, Button, Banner, inputCls, inputStyle } from "@/components/ui";

export default function AturanGlobalPage() {
  const master = isHrMaster();
  const [rules, setRules] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    api.getRules().then(setRules).catch((e) => setError(e.message));
  }, []);

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const updated = await api.updateRules(rules);
      setRules(updated);
      setSuccess("Aturan umum berhasil disimpan.");
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  }

  if (!rules) return <div className="text-sm" style={{ color: "var(--text-muted)" }}>Memuat...</div>;

  function num(key: string) {
    return {
      value: rules[key],
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => setRules({ ...rules, [key]: parseFloat(e.target.value) || 0 }),
    };
  }
  function time(key: string) {
    return {
      value: rules[key],
      onChange: (e: React.ChangeEvent<HTMLInputElement>) => setRules({ ...rules, [key]: e.target.value }),
    };
  }

  return (
    <div>
      <PageHeader
        title="Aturan Umum"
        description="Aturan uang makan, potongan, dan lembur yang berlaku lintas divisi."
      />

      <form onSubmit={handleSave} className="max-w-3xl">
        <fieldset disabled={!master} className="space-y-8">
          {error && <Banner kind="error">{error}</Banner>}
          {success && <Banner kind="success">{success}</Banner>}
          {!master && <Banner kind="info">Anda login sebagai HR Staff — hanya bisa melihat, tidak bisa mengubah aturan.</Banner>}

          <Card>
            <h3 className="text-sm font-semibold mb-4" style={{ color: "var(--ink)" }}>Uang Makan &amp; Potongan Telat</h3>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Uang Makan Default (Rp/hari)"><input type="number" className={inputCls} style={inputStyle} {...num("uang_makan_default")} /></Field>
              <Field label="Toleransi Telat (menit)" hint="Telat pertama di bawah ini bebas denda"><input type="number" className={inputCls} style={inputStyle} {...num("toleransi_telat_max_menit")} /></Field>
              <Field label="Batas Telat Ringan (jam masuk ≤)"><input type="time" className={inputCls} style={inputStyle} {...time("batas_telat_ringan")} /></Field>
              <Field label="Potongan Telat Ringan (Rp)"><input type="number" className={inputCls} style={inputStyle} {...num("potongan_telat_sedikit")} /></Field>
              <Field label="Batas Telat Berat (jam masuk ≤)"><input type="time" className={inputCls} style={inputStyle} {...time("batas_telat_berat")} /></Field>
              <Field label="Potongan Telat Berat (% uang makan)"><input type="number" step="0.1" className={inputCls} style={inputStyle} {...num("potongan_telat_banyak_persen")} /></Field>
            </div>
          </Card>

          <Card>
            <h3 className="text-sm font-semibold mb-4" style={{ color: "var(--ink)" }}>Potongan Pulang Duluan</h3>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Batas Ringan (jam keluar ≥)"><input type="time" className={inputCls} style={inputStyle} {...time("batas_pulang_duluan_ringan")} /></Field>
              <Field label="Potongan Ringan (Rp)"><input type="number" className={inputCls} style={inputStyle} {...num("potongan_pulang_duluan_sedikit")} /></Field>
              <Field label="Batas Berat (jam keluar <)"><input type="time" className={inputCls} style={inputStyle} {...time("batas_pulang_duluan_berat")} /></Field>
              <Field label="Potongan Berat (% uang makan)"><input type="number" step="0.1" className={inputCls} style={inputStyle} {...num("potongan_pulang_duluan_banyak_persen")} /></Field>
            </div>
          </Card>

          <Card>
            <h3 className="text-sm font-semibold mb-4" style={{ color: "var(--ink)" }}>Lembur</h3>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Bonus Lembur per Jam (Rp)"><input type="number" className={inputCls} style={inputStyle} {...num("bonus_lembur_per_jam")} /></Field>
              <Field label="Pembulatan Lembur (menit)" hint="Sisa menit ≥ ini dibulatkan ke 1 jam"><input type="number" className={inputCls} style={inputStyle} {...num("menit_pembulatan_lembur")} /></Field>
            </div>
          </Card>

          <Card>
            <h3 className="text-sm font-semibold mb-4" style={{ color: "var(--ink)" }}>Lain-lain</h3>
            <div className="grid grid-cols-2 gap-4">
              <Field label="Profil Default" hint="Dipakai kalau karyawan tidak ditemukan di master"><input className={inputCls} style={inputStyle} value={rules.profil_default} onChange={(e) => setRules({ ...rules, profil_default: e.target.value })} /></Field>
              <Field label="Minggu Bermasalah Berturut untuk 'Alpa Berulang'"><input type="number" className={inputCls} style={inputStyle} {...num("min_minggu_berturut_alpa")} /></Field>
              <Field label="Ambang Dedup Scan Ganda (menit)"><input type="number" className={inputCls} style={inputStyle} {...num("dedup_threshold_menit")} /></Field>
            </div>
          </Card>

          {master && (
            <div className="flex justify-end">
              <Button type="submit" disabled={saving}>{saving ? "Menyimpan..." : "Simpan Perubahan"}</Button>
            </div>
          )}
        </fieldset>
      </form>
    </div>
  );
}
