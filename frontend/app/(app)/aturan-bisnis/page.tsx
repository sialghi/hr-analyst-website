"use client";
import { useEffect, useState } from "react";
import { api, isHrMaster, ApiError } from "@/lib/api";
import { PageHeader, Button, Card, Field, inputCls, inputStyle, Banner } from "@/components/ui";

const HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"];

type JamMap = Record<string, string> | null;

interface Profile {
  code: string;
  nama: string;
  cabang: string[];
  hari_kerja: string[];
  jam_masuk: JamMap;
  jam_keluar: JamMap;
  patokan_lembur: JamMap;
  ikut_telat: boolean;
  ikut_lembur: boolean;
  ikut_kuota_hari_kerja: boolean;
  hari_kandidat_kuota: string[];
  min_hari_kerja: number;
  ikut_bonus_tanggal_merah: boolean;
  lembur_khusus: { hanya_hari: string[]; threshold_jam: number; tarif_per_jam: number; bonus_flat: number } | null;
}

const BLANK: Profile = {
  code: "", nama: "", cabang: [], hari_kerja: [], jam_masuk: { default: "08:00" },
  jam_keluar: { default: "16:00" }, patokan_lembur: { default: "16:00" },
  ikut_telat: true, ikut_lembur: true, ikut_kuota_hari_kerja: true,
  hari_kandidat_kuota: [], min_hari_kerja: 4, ikut_bonus_tanggal_merah: true, lembur_khusus: null,
};

export default function AturanBisnisPage() {
  const master = isHrMaster();
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [form, setForm] = useState<Profile>(BLANK);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function load() {
    api.getProfiles().then(setProfiles).catch((e) => setError(e.message));
  }

  useEffect(load, []);

  function selectProfile(p: Profile) {
    setSelected(p.code);
    setCreating(false);
    setForm(JSON.parse(JSON.stringify(p)));
    setError(null);
    setSuccess(null);
  }

  function startCreate() {
    setSelected(null);
    setCreating(true);
    setForm(JSON.parse(JSON.stringify(BLANK)));
    setError(null);
    setSuccess(null);
  }

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    setSuccess(null);
    try {
      const payload = { ...form };
      if (creating) {
        await api.createProfile(payload);
        setSuccess(`Profil "${payload.nama}" berhasil dibuat.`);
      } else {
        await api.updateProfile(form.code, payload);
        setSuccess(`Aturan "${payload.nama}" berhasil disimpan.`);
      }
      load();
      setCreating(false);
    } catch (err: any) {
      setError(err.message || "Gagal menyimpan.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(code: string) {
    if (!confirm(`Hapus profil "${code}"? Aksi ini tidak bisa dibatalkan.`)) return;
    try {
      await api.deleteProfile(code);
      setSelected(null);
      load();
    } catch (err: any) {
      alert(err.message);
    }
  }

  return (
    <div>
      <PageHeader
        title="Aturan per Divisi"
        description="Jam kerja, lembur, kuota hari kerja, dan aturan lain untuk tiap profil/divisi karyawan."
        action={master && <Button onClick={startCreate}>+ Tambah Profil</Button>}
      />

      <div className="grid grid-cols-[280px_1fr] gap-6">
        <Card className="p-0 overflow-hidden">
          {profiles.map((p) => (
            <button
              key={p.code}
              onClick={() => selectProfile(p)}
              className="w-full text-left px-4 py-3 border-b text-sm transition"
              style={{
                borderColor: "var(--line)",
                background: selected === p.code ? "var(--paper-subtle)" : "white",
                borderLeft: selected === p.code ? "3px solid var(--accent-light)" : "3px solid transparent",
              }}
            >
              <div className="font-medium" style={{ color: "var(--ink)" }}>{p.nama}</div>
              <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>{p.code}</div>
            </button>
          ))}
          {profiles.length === 0 && (
            <div className="px-4 py-6 text-sm text-center" style={{ color: "var(--text-muted)" }}>
              Belum ada profil.
            </div>
          )}
        </Card>

        {(selected || creating) ? (
          <ProfileForm
            form={form}
            setForm={setForm}
            onSubmit={handleSave}
            onDelete={!creating ? () => handleDelete(form.code) : undefined}
            creating={creating}
            readOnly={!master}
            saving={saving}
            error={error}
            success={success}
          />
        ) : (
          <Card>
            <p className="text-sm" style={{ color: "var(--text-muted)" }}>
              Pilih profil di sebelah kiri untuk melihat atau mengubah aturannya.
            </p>
          </Card>
        )}
      </div>
    </div>
  );
}

function ProfileForm({
  form, setForm, onSubmit, onDelete, creating, readOnly, saving, error, success,
}: {
  form: Profile; setForm: (f: Profile) => void; onSubmit: (e: React.FormEvent) => void;
  onDelete?: () => void; creating: boolean; readOnly: boolean; saving: boolean;
  error: string | null; success: string | null;
}) {
  const punyaJamBaku = form.jam_masuk !== null;

  function toggleHari(list: string[], hari: string, setter: (v: string[]) => void) {
    if (list.includes(hari)) setter(list.filter((h) => h !== hari));
    else setter([...list, hari]);
  }

  function setJamDefault(field: "jam_masuk" | "jam_keluar" | "patokan_lembur", value: string) {
    setForm({ ...form, [field]: { ...(form[field] || {}), default: value } });
  }

  function toggleJamBaku(checked: boolean) {
    if (checked) {
      setForm({ ...form, jam_masuk: { default: "08:00" }, jam_keluar: { default: "16:00" }, patokan_lembur: { default: "16:00" } });
    } else {
      setForm({ ...form, jam_masuk: null, jam_keluar: null, patokan_lembur: null });
    }
  }

  return (
    <Card>
      <fieldset disabled={readOnly} className="space-y-6">
        {error && <Banner kind="error">{error}</Banner>}
        {success && <Banner kind="success">{success}</Banner>}
        {readOnly && <Banner kind="info">Anda login sebagai HR Staff — hanya bisa melihat, tidak bisa mengubah aturan.</Banner>}

        <div className="grid grid-cols-2 gap-4">
          <Field label="Kode Profil" hint={creating ? "Huruf besar, tanpa spasi, mis. SALES_LAPANGAN" : undefined}>
            <input
              className={inputCls} style={inputStyle} value={form.code} disabled={!creating || readOnly}
              onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase().replace(/\s+/g, "_") })}
              required
            />
          </Field>
          <Field label="Nama Tampilan">
            <input
              className={inputCls} style={inputStyle} value={form.nama}
              onChange={(e) => setForm({ ...form, nama: e.target.value })} required
            />
          </Field>
        </div>

        <Field label="Cabang (pisahkan dengan koma, kosongkan jika tidak terikat cabang tertentu)">
          <input
            className={inputCls} style={inputStyle}
            value={form.cabang.join(", ")}
            onChange={(e) => setForm({ ...form, cabang: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })}
          />
        </Field>

        <Field label="Hari Kerja">
          <DayCheckboxes selected={form.hari_kerja} onToggle={(h) => toggleHari(form.hari_kerja, h, (v) => setForm({ ...form, hari_kerja: v }))} />
        </Field>

        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={punyaJamBaku} onChange={(e) => toggleJamBaku(e.target.checked)} />
          Profil ini punya jam kerja baku (kalau tidak dicentang, dianggap fleksibel — tidak dihitung telat/lembur berdasarkan jam)
        </label>

        {punyaJamBaku && (
          <div className="grid grid-cols-3 gap-4 pl-1 border-l-2" style={{ borderColor: "var(--line)" }}>
            <div className="pl-4">
              <Field label="Jam Masuk (default)">
                <input type="time" className={inputCls} style={inputStyle}
                  value={form.jam_masuk?.default || "08:00"} onChange={(e) => setJamDefault("jam_masuk", e.target.value)} />
              </Field>
            </div>
            <div className="pl-4">
              <Field label="Jam Keluar (default)">
                <input type="time" className={inputCls} style={inputStyle}
                  value={form.jam_keluar?.default || "16:00"} onChange={(e) => setJamDefault("jam_keluar", e.target.value)} />
              </Field>
            </div>
            <div className="pl-4">
              <Field label="Patokan Lembur (default)">
                <input type="time" className={inputCls} style={inputStyle}
                  value={form.patokan_lembur?.default || "16:00"} onChange={(e) => setJamDefault("patokan_lembur", e.target.value)} />
              </Field>
            </div>
          </div>
        )}

        {punyaJamBaku && (
          <OverrideEditor form={form} setForm={setForm} />
        )}

        <div className="grid grid-cols-2 gap-4">
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.ikut_telat} onChange={(e) => setForm({ ...form, ikut_telat: e.target.checked })} />
            Ikut dihitung telat
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.ikut_lembur} onChange={(e) => setForm({ ...form, ikut_lembur: e.target.checked })} />
            Ikut dihitung lembur
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.ikut_kuota_hari_kerja} onChange={(e) => setForm({ ...form, ikut_kuota_hari_kerja: e.target.checked })} />
            Ikut kuota minimal hari kerja/minggu
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.ikut_bonus_tanggal_merah} onChange={(e) => setForm({ ...form, ikut_bonus_tanggal_merah: e.target.checked })} />
            Dapat bonus tanggal merah
          </label>
        </div>

        {form.ikut_kuota_hari_kerja && (
          <div className="grid grid-cols-2 gap-4">
            <Field label="Hari Kandidat Kuota">
              <DayCheckboxes selected={form.hari_kandidat_kuota} onToggle={(h) => toggleHari(form.hari_kandidat_kuota, h, (v) => setForm({ ...form, hari_kandidat_kuota: v }))} />
            </Field>
            <Field label="Minimal Hari Kerja per Minggu">
              <input type="number" min={0} max={7} className={inputCls} style={inputStyle}
                value={form.min_hari_kerja} onChange={(e) => setForm({ ...form, min_hari_kerja: parseInt(e.target.value) || 0 })} />
            </Field>
          </div>
        )}

        <LemburKhususEditor form={form} setForm={setForm} />

        {!readOnly && (
          <div className="flex items-center justify-between pt-4 border-t" style={{ borderColor: "var(--line)" }}>
            {onDelete ? (
              <Button variant="danger" onClick={onDelete}>Hapus Profil</Button>
            ) : <div />}
            <Button type="submit" onClick={onSubmit as any} disabled={saving}>
              {saving ? "Menyimpan..." : "Simpan Perubahan"}
            </Button>
          </div>
        )}
      </fieldset>
    </Card>
  );
}

function DayCheckboxes({ selected, onToggle }: { selected: string[]; onToggle: (h: string) => void }) {
  return (
    <div className="flex flex-wrap gap-2">
      {HARI.map((h) => (
        <label
          key={h}
          className="px-2.5 py-1.5 rounded-md text-xs border cursor-pointer select-none"
          style={{
            borderColor: "var(--line)",
            background: selected.includes(h) ? "var(--ink)" : "white",
            color: selected.includes(h) ? "white" : "var(--text)",
          }}
        >
          <input type="checkbox" className="hidden" checked={selected.includes(h)} onChange={() => onToggle(h)} />
          {h}
        </label>
      ))}
    </div>
  );
}

function OverrideEditor({ form, setForm }: { form: Profile; setForm: (f: Profile) => void }) {
  const overrideDays = HARI.filter((h) => h !== "default" && (form.jam_masuk?.[h] || form.jam_keluar?.[h] || form.patokan_lembur?.[h]));
  const [newDay, setNewDay] = useState(HARI[0]);

  function addOverride() {
    setForm({
      ...form,
      jam_masuk: { ...(form.jam_masuk || {}), [newDay]: form.jam_masuk?.default || "08:00" },
      jam_keluar: { ...(form.jam_keluar || {}), [newDay]: form.jam_keluar?.default || "16:00" },
      patokan_lembur: { ...(form.patokan_lembur || {}), [newDay]: form.patokan_lembur?.default || "16:00" },
    });
  }

  function removeOverride(day: string) {
    const jm = { ...(form.jam_masuk || {}) }; delete jm[day];
    const jk = { ...(form.jam_keluar || {}) }; delete jk[day];
    const pl = { ...(form.patokan_lembur || {}) }; delete pl[day];
    setForm({ ...form, jam_masuk: jm, jam_keluar: jk, patokan_lembur: pl });
  }

  function updateOverride(day: string, field: "jam_masuk" | "jam_keluar" | "patokan_lembur", value: string) {
    setForm({ ...form, [field]: { ...(form[field] || {}), [day]: value } });
  }

  return (
    <div>
      <Field label="Jam Khusus per Hari (opsional)" hint="Mis. Sabtu pulang lebih awal. Hari yang tidak diatur di sini otomatis pakai jam default di atas.">
        <div className="space-y-2">
          {overrideDays.map((day) => (
            <div key={day} className="flex items-center gap-2 text-sm">
              <span className="w-20" style={{ color: "var(--ink)" }}>{day}</span>
              <input type="time" className={inputCls} style={{ ...inputStyle, width: 110 }} value={form.jam_masuk?.[day] || ""} onChange={(e) => updateOverride(day, "jam_masuk", e.target.value)} />
              <input type="time" className={inputCls} style={{ ...inputStyle, width: 110 }} value={form.jam_keluar?.[day] || ""} onChange={(e) => updateOverride(day, "jam_keluar", e.target.value)} />
              <input type="time" className={inputCls} style={{ ...inputStyle, width: 110 }} value={form.patokan_lembur?.[day] || ""} onChange={(e) => updateOverride(day, "patokan_lembur", e.target.value)} />
              <button type="button" onClick={() => removeOverride(day)} className="text-xs underline" style={{ color: "var(--clay)" }}>Hapus</button>
            </div>
          ))}
          <div className="flex items-center gap-2 pt-1">
            <select className={inputCls} style={{ ...inputStyle, width: 140 }} value={newDay} onChange={(e) => setNewDay(e.target.value)}>
              {HARI.filter((h) => !overrideDays.includes(h)).map((h) => <option key={h} value={h}>{h}</option>)}
            </select>
            <button type="button" onClick={addOverride} className="text-xs underline" style={{ color: "var(--ink)" }}>+ Tambah jam khusus hari ini</button>
          </div>
        </div>
      </Field>
    </div>
  );
}

function LemburKhususEditor({ form, setForm }: { form: Profile; setForm: (f: Profile) => void }) {
  const aktif = form.lembur_khusus !== null;

  function toggle(checked: boolean) {
    setForm({
      ...form,
      lembur_khusus: checked ? { hanya_hari: ["Minggu"], threshold_jam: 4, tarif_per_jam: 20000, bonus_flat: 100000 } : null,
    });
  }

  return (
    <div className="pt-2 border-t" style={{ borderColor: "var(--line)" }}>
      <label className="flex items-center gap-2 text-sm mb-3 mt-4">
        <input type="checkbox" checked={aktif} onChange={(e) => toggle(e.target.checked)} />
        Pakai aturan lembur khusus (threshold, bukan per jam) untuk hari tertentu
      </label>
      {aktif && form.lembur_khusus && (
        <div className="grid grid-cols-2 gap-4 pl-1 border-l-2" style={{ borderColor: "var(--line)" }}>
          <div className="pl-4 col-span-2">
            <Field label="Berlaku hanya di hari">
              <DayCheckboxes
                selected={form.lembur_khusus.hanya_hari}
                onToggle={(h) => {
                  const list = form.lembur_khusus!.hanya_hari.includes(h)
                    ? form.lembur_khusus!.hanya_hari.filter((x) => x !== h)
                    : [...form.lembur_khusus!.hanya_hari, h];
                  setForm({ ...form, lembur_khusus: { ...form.lembur_khusus!, hanya_hari: list } });
                }}
              />
            </Field>
          </div>
          <div className="pl-4">
            <Field label="Threshold Jam" hint="≥ jam ini → dapat bonus flat">
              <input type="number" step="0.5" className={inputCls} style={inputStyle}
                value={form.lembur_khusus.threshold_jam}
                onChange={(e) => setForm({ ...form, lembur_khusus: { ...form.lembur_khusus!, threshold_jam: parseFloat(e.target.value) || 0 } })} />
            </Field>
          </div>
          <div className="pl-4">
            <Field label="Tarif per Jam (Rp)" hint="Kalau di bawah threshold">
              <input type="number" className={inputCls} style={inputStyle}
                value={form.lembur_khusus.tarif_per_jam}
                onChange={(e) => setForm({ ...form, lembur_khusus: { ...form.lembur_khusus!, tarif_per_jam: parseInt(e.target.value) || 0 } })} />
            </Field>
          </div>
          <div className="pl-4">
            <Field label="Bonus Flat (Rp)" hint="Kalau mencapai threshold">
              <input type="number" className={inputCls} style={inputStyle}
                value={form.lembur_khusus.bonus_flat}
                onChange={(e) => setForm({ ...form, lembur_khusus: { ...form.lembur_khusus!, bonus_flat: parseInt(e.target.value) || 0 } })} />
            </Field>
          </div>
        </div>
      )}
    </div>
  );
}
