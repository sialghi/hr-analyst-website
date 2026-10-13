"use client";
import React, { useState, useMemo, useRef, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  api,
  getRole,
  triggerBlobDownload,
  type PayrollWhatsAppDelivery,
  type PayrollWhatsAppRecipient,
  type PayrollWhatsAppSendResult,
} from "@/lib/api";

interface PayrollRow {
  "Kode Karyawan": string;
  Nama: string;
  "No. Rekening": string;
  Departemen: string;
  "Gaji Pokok": number;
  "Potongan Hari": number;
  "Potongan Nominal": number;
  "Uang Makan": number;
  "Hari Kerja": number;
  Lembur: number;
  Tunjangan: number;
  "Potongan Denda/SO": number;
  "Potongan Telat": number;
  "Potongan BPJS": number;
  "Potongan Lain": number;
  "Kasbon Bulan Ini": number;
  "Sisa Kasbon": number;
  "Sub Total": number;
  "Total Potongan": number;
  THP: number;
  _employee_id?: number | null;
  _wa_number?: string;
  _wa_available?: boolean;
  _wa_status?: string;
  // Fallbacks
  Dept?: string;
  GP?: number;
  "Pot Hari"?: number;
  "Pot Nominal"?: number;
  "Pot Denda/SO"?: number;
  "Pot Telat"?: number;
  "Pot BPJS"?: number;
  "Pot Lain"?: number;
}

interface PayrollKPIs {
  total_thp: number;
  total_potongan: number;
  total_kasbon_aktif: number;
  total_karyawan: number;
}

interface PayrollBlastResult {
  row_index: number;
  nama: string;
  wa_number?: string | null;
  status: PayrollWhatsAppSendResult["status"] | "SKIP";
  reason?: string;
  detail?: string | null;
  delivery_id?: number;
  text_sent?: boolean;
  pdf_sent?: boolean;
}

interface PayrollBlastSummary {
  total: number;
  sent: number;
  skip: number;
  failed: number;
  partial: number;
  results: PayrollBlastResult[];
}

function whatsappStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    ACTIVE: "WhatsApp aktif",
    MISSING_EMPLOYEE_CODE: "Kode karyawan belum diisi",
    EMPLOYEE_NOT_FOUND: "Kode karyawan tidak ditemukan",
    AMBIGUOUS_EMPLOYEE_CODE: "Kode karyawan ganda",
    EMPLOYEE_MAPPING_CHANGED: "Relasi karyawan berubah",
    EMPLOYEE_INACTIVE: "Karyawan tidak aktif",
    WHATSAPP_NOT_LINKED: "WhatsApp belum tertaut",
    MULTIPLE_ACTIVE_LINKS: "Link WhatsApp ganda",
  };
  return labels[status] || status;
}

export default function ProsesSlipGajiPage() {
  const router = useRouter();

  // Role & auth
  const [role, setRole] = useState<string | null>(null);

  // Upload & Session state
  const [file, setFile] = useState<File | null>(null);
  const [periode, setPeriode] = useState<string>(() => {
    const d = new Date();
    const months = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Ags", "Sep", "Okt", "Nov", "Des"];
    return `${months[d.getMonth()]}-${String(d.getFullYear()).slice(-2)}`;
  });
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [rows, setRows] = useState<PayrollRow[]>([]);
  const [kpis, setKpis] = useState<PayrollKPIs | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number>(0);

  // UI state
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [isExporting, setIsExporting] = useState<boolean>(false);
  const [isArchiving, setIsArchiving] = useState<boolean>(false);
  const [isDownloadingPdf, setIsDownloadingPdf] = useState<boolean>(false);
  const [filterDept, setFilterDept] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [alertMsg, setAlertMsg] = useState<{ type: "success" | "error" | "info"; text: string } | null>(null);

  // WhatsApp blast modal
  const [waModalOpen, setWaModalOpen] = useState<boolean>(false);
  const [waSending, setWaSending] = useState<boolean>(false);
  const [waResults, setWaResults] = useState<PayrollBlastSummary | null>(null);
  const [waPreview, setWaPreview] = useState<PayrollWhatsAppRecipient[]>([]);
  const [waPreviewLoading, setWaPreviewLoading] = useState<boolean>(false);
  const [waHistory, setWaHistory] = useState<PayrollWhatsAppDelivery[]>([]);

  // Single WA send status
  const [singleWaSending, setSingleWaSending] = useState<boolean>(false);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const slipPreviewRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const userRole = getRole();
    if (!userRole) {
      router.push("/login");
      return;
    }
    setRole(userRole);
  }, [router]);

  // Dismiss alert helper
  const showAlert = useCallback((type: "success" | "error" | "info", text: string) => {
    setAlertMsg({ type, text });
    setTimeout(() => {
      setAlertMsg(null);
    }, 6000);
  }, []);

  // Format IDR Helper
  const formatRupiah = (val: number | string | undefined | null): string => {
    const num = Number(val) || 0;
    return new Intl.NumberFormat("id-ID").format(Math.round(num));
  };

  const createPreviewPdf = async (rowIndex: number): Promise<File> => {
    if (selectedIndex !== rowIndex) {
      setSelectedIndex(rowIndex);
      await new Promise<void>((resolve) => {
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      });
    }
    const preview = slipPreviewRef.current;
    if (!preview) throw new Error("Pratinjau slip tidak tersedia untuk dibuat menjadi PDF.");

    await document.fonts.ready;
    await Promise.all(
      Array.from(preview.querySelectorAll("img")).map((image) =>
        image.complete ? Promise.resolve() : image.decode()
      )
    );

    const [{ default: html2canvas }, { jsPDF }] = await Promise.all([
      import("html2canvas"),
      import("jspdf"),
    ]);
    const canvas = await html2canvas(preview, {
      backgroundColor: "#ffffff",
      scale: 2,
      useCORS: true,
      onclone: (clonedDocument) => {
        const styles = clonedDocument.createElement("style");
        styles.textContent = `
          #printable-slip {
            color: #000000 !important;
            border-color: #000000 !important;
            outline-color: #000000 !important;
            text-decoration-color: #000000 !important;
            box-shadow: none !important;
            text-shadow: none !important;
          }
          #printable-slip * {
            border-color: #000000 !important;
            outline-color: #000000 !important;
            text-decoration-color: #000000 !important;
            box-shadow: none !important;
            text-shadow: none !important;
          }
          #printable-slip { background-color: #ffffff !important; }
          #printable-slip .text-red-600 { color: #dc2626 !important; }
          #printable-slip .text-red-600 * { color: #dc2626 !important; }
          #printable-slip .border-emerald-700 { border-color: #047857 !important; }
          #printable-slip .bg-white { background-color: #ffffff !important; }
        `;
        clonedDocument.head.appendChild(styles);
      },
    });
    const pdf = new jsPDF({ orientation: "landscape", unit: "mm", format: "a4", compress: true });
    const pageWidth = pdf.internal.pageSize.getWidth();
    const pageHeight = pdf.internal.pageSize.getHeight();
    const margin = 8;
    const fitScale = Math.min(
      (pageWidth - margin * 2) / canvas.width,
      (pageHeight - margin * 2) / canvas.height
    );
    const imageWidth = canvas.width * fitScale;
    const imageHeight = canvas.height * fitScale;
    pdf.addImage(
      canvas.toDataURL("image/png"),
      "PNG",
      (pageWidth - imageWidth) / 2,
      (pageHeight - imageHeight) / 2,
      imageWidth,
      imageHeight,
      undefined,
      "FAST"
    );

    const row = rows[rowIndex];
    const safeName = (row?.Nama || `karyawan_${rowIndex}`).replace(/[^\w\-]/g, "_");
    return new File([pdf.output("blob")], `SlipGaji_${safeName}_${periode}.pdf`, {
      type: "application/pdf",
    });
  };

  // 1. Download Template
  const handleDownloadTemplate = async (format: "xlsx" | "csv") => {
    try {
      const blob = await api.downloadPayrollTemplate(format);
      triggerBlobDownload(blob, `template_slip_gaji.${format}`);
      showAlert("success", `Template slip gaji (.${format}) berhasil diunduh.`);
    } catch (err: any) {
      showAlert("error", err.message || "Gagal mengunduh template.");
    }
  };

  // 2. Upload Payroll File
  const handleFileUpload = async (selectedFile?: File) => {
    const fileToUpload = selectedFile || file;
    if (!fileToUpload) {
      showAlert("error", "Pilih file Excel atau CSV terlebih dahulu.");
      return;
    }

    setIsUploading(true);
    setAlertMsg(null);

    try {
      const res = await api.uploadPayroll(fileToUpload, periode);
      setSessionId(res.session_id);
      setRows(res.rows || []);
      setKpis(res.kpis || null);
      setSelectedIndex(0);
      setWaPreview([]);
      setWaHistory([]);
      setWaResults(null);
      showAlert("success", `Data payroll berhasil diproses (${res.rows.length} karyawan).`);
    } catch (err: any) {
      showAlert("error", err.message || "Gagal memproses file payroll.");
    } finally {
      setIsUploading(false);
    }
  };

  // 3. Live Edit Field Handler
  const handleCellChange = async (originalRowIndex: number, field: string, value: string) => {
    const numVal = parseFloat(value) || 0;

    // Optimistic local update
    const updatedRows = [...rows];
    const currentRow = { ...updatedRows[originalRowIndex], [field]: numVal };
    if (field === "Gaji Pokok") delete currentRow.GP;
    if (field === "Potongan Hari") delete currentRow["Pot Hari"];
    if (field === "Potongan Nominal") delete currentRow["Pot Nominal"];
    if (field === "Potongan Denda/SO") delete currentRow["Pot Denda/SO"];
    if (field === "Potongan Telat") delete currentRow["Pot Telat"];
    if (field === "Potongan BPJS") delete currentRow["Pot BPJS"];
    if (field === "Potongan Lain") delete currentRow["Pot Lain"];

    // Calculate sub total & thp
    const gp = Number(currentRow["Gaji Pokok"] ?? currentRow.GP) || 0;
    const um = Number(currentRow["Uang Makan"]) || 0;
    const tunjangan = Number(currentRow["Tunjangan"]) || 0;
    const lembur = Number(currentRow["Lembur"]) || 0;
    const potNominal = Number(currentRow["Potongan Nominal"] ?? currentRow["Pot Nominal"]) || 0;
    const potDenda = Number(currentRow["Potongan Denda/SO"] ?? currentRow["Pot Denda/SO"]) || 0;
    const potTelat = Number(currentRow["Potongan Telat"] ?? currentRow["Pot Telat"]) || 0;
    const potBpjs = Number(currentRow["Potongan BPJS"] ?? currentRow["Pot BPJS"]) || 0;
    const potLain = Number(currentRow["Potongan Lain"] ?? currentRow["Pot Lain"]) || 0;
    const kasbon = Number(currentRow["Kasbon Bulan Ini"]) || 0;

    const subTotal = gp + um + tunjangan + lembur;
    const totalPotongan = potNominal + potDenda + potTelat + potBpjs + potLain + kasbon;
    const thp = subTotal - totalPotongan;

    currentRow["Sub Total"] = subTotal;
    currentRow["Total Potongan"] = totalPotongan;
    currentRow["THP"] = thp;
    updatedRows[originalRowIndex] = currentRow;
    setRows(updatedRows);

    // Update KPIs locally
    if (kpis) {
      setKpis({
        ...kpis,
        total_thp: updatedRows.reduce((acc, r) => acc + (r["THP"] || 0), 0),
        total_potongan: updatedRows.reduce((acc, r) => acc + (r["Total Potongan"] || 0), 0),
        total_kasbon_aktif: updatedRows.reduce((acc, r) => acc + (Number(r["Sisa Kasbon"]) || 0), 0),
      });
    }

    // Persist to session backend
    if (sessionId) {
      try {
        const patchRes = await api.patchPayrollRow(sessionId, originalRowIndex, { [field]: numVal });
        if (patchRes.kpis) {
          setKpis(patchRes.kpis);
        }
      } catch (err: any) {
        console.error("Gagal update live edit ke backend:", err);
      }
    }
  };

  // 4. Export Excel Rekap
  const handleExportExcel = async () => {
    if (!sessionId) return;
    setIsExporting(true);
    try {
      await api.exportPayrollExcel(sessionId, periode);
      showAlert("success", "File Excel Rekap Slip Gaji berhasil diunduh.");
    } catch (err: any) {
      showAlert("error", err.message || "Gagal mengunduh file Excel rekap.");
    } finally {
      setIsExporting(false);
    }
  };

  const handleArchiveAllSlips = async () => {
    if (!sessionId) return;
    const previousSelectedIndex = selectedIndex;
    setIsArchiving(true);
    try {
      const pdfs: File[] = [];
      for (let rowIndex = 0; rowIndex < rows.length; rowIndex += 1) {
        pdfs.push(await createPreviewPdf(rowIndex));
      }
      const result = await api.archivePayrollSlips(sessionId, pdfs);
      const replacedText = result.replaced_count
        ? ` ${result.replaced_count} slip periode ini diperbarui dan masa simpannya dimulai ulang.`
        : "";
      showAlert(
        "success",
        `${result.saved_count} slip gaji periode ${result.periode} tersimpan di database. Masa simpan 1 tahun dimulai saat ini.${replacedText}`,
      );
    } catch (err) {
      showAlert(
        "error",
        err instanceof Error ? err.message : "Gagal menyimpan semua slip gaji.",
      );
    } finally {
      setSelectedIndex(previousSelectedIndex);
      setIsArchiving(false);
    }
  };

  // 5. Download Single Slip PDF
  const handleDownloadSinglePdf = async () => {
    if (!sessionId || !selectedEmployee) return;
    setIsDownloadingPdf(true);
    try {
      const pdf = await createPreviewPdf(selectedIndex);
      triggerBlobDownload(pdf, pdf.name);
      showAlert("success", `PDF Slip Gaji ${selectedEmployee.Nama} berhasil diunduh.`);
    } catch (err: any) {
      showAlert("error", err.message || "Gagal mengunduh PDF slip gaji.");
    } finally {
      setIsDownloadingPdf(false);
    }
  };

  // 6. Send Single WhatsApp
  const handleSendSingleWhatsApp = async () => {
    if (!sessionId || !selectedEmployee) return;
    try {
      const preview = await api.getPayrollWhatsAppRecipients(sessionId);
      const recipient = preview.recipients.find((item) => item.row_index === selectedIndex);
      if (!recipient || recipient.status !== "ACTIVE" || !recipient.wa_number) {
        showAlert("error", `Slip tidak dapat dikirim: ${recipient?.status || "Link WhatsApp tidak ditemukan"}.`);
        return;
      }
      const confirmed = window.confirm(
        `Kirim slip gaji periode ${periode} kepada ${recipient.nama} (${recipient.employee_code})?\n` +
        `Nomor WhatsApp: ${recipient.wa_number}\n` +
        `Total diterima: Rp ${formatRupiah(selectedEmployee.THP)}`
      );
      if (!confirmed) return;

      setSingleWaSending(true);
      const pdf = await createPreviewPdf(selectedIndex);
      const res = await api.sendSlipWhatsApp(sessionId, selectedIndex, pdf);
      if (res.status === "SENT") {
        showAlert("success", `Rincian dan PDF slip berhasil dikirim ke ${res.nama} (${res.wa_number}).`);
      } else if (res.status === "PARTIAL") {
        showAlert("info", `Pengiriman ke ${res.nama} hanya sebagian berhasil: ${res.detail || "periksa status teks/PDF"}`);
      } else {
        showAlert("error", `Pengiriman slip gagal: ${res.detail || "pengiriman teks dan PDF gagal."}`);
      }
      setWaHistory(await api.getPayrollWhatsAppHistory(sessionId));
    } catch (err: any) {
      showAlert("error", err.message || "Gagal mengirim WhatsApp ke karyawan.");
    } finally {
      setSingleWaSending(false);
    }
  };

  const handleOpenWhatsAppModal = async () => {
    if (!sessionId) return;
    setWaModalOpen(true);
    setWaPreviewLoading(true);
    setWaResults(null);
    try {
      const [preview, history] = await Promise.all([
        api.getPayrollWhatsAppRecipients(sessionId),
        api.getPayrollWhatsAppHistory(sessionId),
      ]);
      setWaPreview(preview.recipients);
      setWaHistory(history);
    } catch (err: any) {
      showAlert("error", err.message || "Gagal memeriksa linking WhatsApp dan riwayat pengiriman.");
    } finally {
      setWaPreviewLoading(false);
    }
  };

  // 7. Blast WhatsApp All
  const handleSendAllWhatsApp = async () => {
    if (!sessionId) return;
    const readyRecipients = waPreview.filter((recipient) => recipient.status === "ACTIVE");
    if (readyRecipients.length === 0) {
      showAlert("error", "Tidak ada linking WhatsApp aktif yang bisa dikirimi.");
      return;
    }
    const totalNet = readyRecipients.reduce(
      (total, recipient) => total + (Number(rows[recipient.row_index]?.THP) || 0),
      0
    );
    const confirmed = window.confirm(
      `Kirim slip periode ${periode} kepada ${readyRecipients.length} karyawan dengan WhatsApp aktif?\n` +
      `Total nilai slip: Rp ${formatRupiah(totalNet)}.\n` +
      "Daftar nama, kode, dan nomor penerima sudah ditampilkan pada dialog."
    );
    if (!confirmed) return;

    setWaSending(true);
    setWaResults(null);
    const previousIndex = selectedIndex;
    try {
      const results: PayrollBlastResult[] = waPreview
        .filter((recipient) => recipient.status !== "ACTIVE")
        .map((recipient) => ({
          row_index: recipient.row_index,
          nama: recipient.nama,
          wa_number: recipient.wa_number,
          status: "SKIP",
          reason: recipient.status,
        }));

      for (const recipient of readyRecipients) {
        try {
          const pdf = await createPreviewPdf(recipient.row_index);
          const result = await api.sendSlipWhatsApp(sessionId, recipient.row_index, pdf);
          results.push({ row_index: recipient.row_index, ...result });
        } catch (err: unknown) {
          const errorMessage = err instanceof Error
            ? err.message
            : "PDF gagal dibuat atau pengiriman tidak berhasil.";
          const errorStatus = err instanceof Error && "status" in err
            && typeof err.status === "number"
            ? err.status
            : undefined;
          results.push({
            row_index: recipient.row_index,
            nama: recipient.nama,
            wa_number: recipient.wa_number,
            status: errorStatus === 409 ? "SKIP" : "FAILED",
            detail: errorMessage,
          });
        }
      }

      const res = {
        total: waPreview.length,
        sent: results.filter((result) => result.status === "SENT").length,
        skip: results.filter((result) => result.status === "SKIP").length,
        failed: results.filter((result) => result.status === "FAILED").length,
        partial: results.filter((result) => result.status === "PARTIAL").length,
        results,
      };
      setWaResults(res);
      setWaHistory(await api.getPayrollWhatsAppHistory(sessionId));
      const resultSummary =
        `Pengiriman selesai: ${res.sent} lengkap, ${res.partial || 0} sebagian, ` +
        `${res.skip} dilewati, ${res.failed} gagal.`;
      showAlert(res.failed || res.partial ? "info" : "success", resultSummary);
    } catch (err: any) {
      showAlert("error", err.message || "Gagal mengirim pesan WhatsApp blast.");
    } finally {
      setSelectedIndex(previousIndex);
      setWaSending(false);
    }
  };

  // Filtered rows for table
  const departments = useMemo(() => {
    const set = new Set<string>();
    rows.forEach((r) => {
      const d = r.Departemen || r.Dept;
      if (d) set.add(d);
    });
    return Array.from(set);
  }, [rows]);

  const filteredRows = useMemo(() => {
    return rows
      .map((row, originalIndex) => ({ row, originalIndex }))
      .filter(({ row }) => {
        const d = row.Departemen || row.Dept || "";
        if (filterDept !== "ALL" && d !== filterDept) return false;
        if (searchQuery.trim()) {
          const q = searchQuery.toLowerCase();
          const matchKode = (row["Kode Karyawan"] || "").toLowerCase().includes(q);
          const matchNama = (row.Nama || "").toLowerCase().includes(q);
          const matchNorek = (row["No. Rekening"] || "").toLowerCase().includes(q);
          const matchDept = d.toLowerCase().includes(q);
          if (!matchKode && !matchNama && !matchNorek && !matchDept) return false;
        }
        return true;
      });
  }, [rows, filterDept, searchQuery]);

  const selectedEmployee = rows[selectedIndex] || null;

  const handlePrintSlip = () => {
    const originalTitle = typeof document !== "undefined" ? document.title : "";
    if (typeof document !== "undefined") document.title = "";
    window.print();
    setTimeout(() => {
      if (typeof document !== "undefined") document.title = originalTitle;
    }, 1000);
  };

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800 pb-16">
      {/* Print Specific CSS - Clean output without browser headers, footers, or URLs */}
      <style jsx global>{`
        @page {
          size: A4 portrait;
          margin: 0;
        }
        @media print {
          html, body {
            margin: 0 !important;
            padding: 0 !important;
            background: #ffffff !important;
            -webkit-print-color-adjust: exact !important;
            print-color-adjust: exact !important;
          }
          body * {
            visibility: hidden !important;
          }
          #printable-slip,
          #printable-slip * {
            visibility: visible !important;
          }
          #printable-slip {
            position: absolute !important;
            left: 0 !important;
            top: 0 !important;
            width: 100% !important;
            max-width: 100% !important;
            margin: 0 !important;
            padding: 15mm 20mm !important;
            border: none !important;
            box-shadow: none !important;
            background: #ffffff !important;
          }
        }
      `}</style>

      {/* Top Header & Breadcrumb */}
      <header className="bg-white border-b border-slate-200 px-6 py-4 sticky top-0 z-20 shadow-xs">
        <div className="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 text-xs text-slate-500 mb-1">
              <span>Proses Slip Gaji</span>
              <span>›</span>
              <span className="text-indigo-600 font-medium">Hasil Pemrosesan</span>
              {sessionId ? (
                <span className="bg-emerald-100 text-emerald-700 text-[10px] px-2 py-0.5 rounded-full font-semibold ml-2">
                  Selesai Dihitung
                </span>
              ) : (
                <span className="bg-slate-100 text-slate-600 text-[10px] px-2 py-0.5 rounded-full font-medium ml-2">
                  Siap Unggah
                </span>
              )}
            </div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold text-slate-900 tracking-tight">
                Pemrosesan Payroll & Slip Gaji Interaktif
              </h1>
              {sessionId && (
                <>
                  <span className="bg-slate-100 text-slate-700 text-xs px-2.5 py-1 rounded-md border border-slate-200 font-semibold">
                    Periode: {periode}
                  </span>
                  <span className="text-xs text-slate-500 font-medium">
                    {rows.length} Karyawan Diproses
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Action Buttons in Header */}
          {sessionId && (
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleArchiveAllSlips}
                disabled={isArchiving}
                className="px-3.5 py-2 text-xs font-medium bg-white text-blue-700 border border-blue-300 rounded-lg hover:bg-blue-50 flex items-center gap-1.5 shadow-xs transition-colors cursor-pointer disabled:opacity-50"
                title="Simpan seluruh PDF slip periode ini ke arsip database"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M5 5h11l3 3v11H5zM8 5v5h8V5M8 19v-5h8v5" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
                {isArchiving ? "Menyimpan..." : "Simpan Semua Slip"}
              </button>

              <button
                type="button"
                onClick={handlePrintSlip}
                className="px-3.5 py-2 text-xs font-medium bg-white text-slate-700 border border-slate-300 rounded-lg hover:bg-slate-50 flex items-center gap-1.5 shadow-xs transition-colors cursor-pointer"
                title="Cetak slip karyawan yang dipilih"
              >
                <svg className="w-3.5 h-3.5 text-slate-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4H7v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
                Cetak Slip
              </button>

              <button
                type="button"
                onClick={handleExportExcel}
                disabled={isExporting}
                className="px-3.5 py-2 text-xs font-medium bg-white text-emerald-700 border border-emerald-300 rounded-lg hover:bg-emerald-50 flex items-center gap-1.5 shadow-xs transition-colors cursor-pointer disabled:opacity-50"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
                {isExporting ? "Mengunduh..." : "Export Excel (.xlsx)"}
              </button>

              <button
                type="button"
                onClick={handleOpenWhatsAppModal}
                className="px-3.5 py-2 text-xs font-medium bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 flex items-center gap-1.5 shadow-xs transition-colors cursor-pointer"
              >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
                Kirim No WA Karyawan
              </button>

              <button
                type="button"
                onClick={() => {
                  setSessionId(null);
                  setRows([]);
                  setKpis(null);
                  setFile(null);
                  setWaPreview([]);
                  setWaHistory([]);
                  setWaResults(null);
                  setWaModalOpen(false);
                }}
                className="px-3 py-2 text-xs font-medium text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
                title="Ganti atau Unggah File Baru"
              >
                Upload Ulang
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Alert Banner */}
      {alertMsg && (
        <div className="max-w-7xl mx-auto px-6 pt-4">
          <div
            className={`p-3.5 rounded-xl border flex items-center justify-between text-xs font-medium shadow-xs ${alertMsg.type === "success"
                ? "bg-emerald-50 border-emerald-200 text-emerald-800"
                : alertMsg.type === "error"
                  ? "bg-rose-50 border-rose-200 text-rose-800"
                  : "bg-blue-50 border-blue-200 text-blue-800"
              }`}
          >
            <div className="flex items-center gap-2">
              {alertMsg.type === "success" ? (
                <svg className="w-4 h-4 text-emerald-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
              ) : alertMsg.type === "error" ? (
                <svg className="w-4 h-4 text-rose-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" strokeWidth="2" />
                  <line x1="12" y1="8" x2="12" y2="12" strokeWidth="2" strokeLinecap="round" />
                  <line x1="12" y1="16" x2="12.01" y2="16" strokeWidth="2" strokeLinecap="round" />
                </svg>
              ) : (
                <svg className="w-4 h-4 text-blue-600 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <circle cx="12" cy="12" r="10" strokeWidth="2" />
                  <line x1="12" y1="16" x2="12" y2="12" strokeWidth="2" strokeLinecap="round" />
                  <line x1="12" y1="8" x2="12.01" y2="8" strokeWidth="2" strokeLinecap="round" />
                </svg>
              )}
              <span>{alertMsg.text}</span>
            </div>
            <button
              onClick={() => setAlertMsg(null)}
              className="text-slate-400 hover:text-slate-600 cursor-pointer text-sm font-bold ml-4"
            >
              ×
            </button>
          </div>
        </div>
      )}

      {/* Main Container */}
      <main className="max-w-7xl mx-auto px-6 pt-6 space-y-6">
        {/* ─────────────────────────────────────────────────────────────
            STATE 1: UPLOAD & TEMPLATE DOWNLOAD CARD (when no session)
        ───────────────────────────────────────────────────────────── */}
        {!sessionId && (
          <div className="bg-white rounded-2xl border border-slate-200/90 shadow-sm p-8 max-w-3xl mx-auto space-y-6">
            <div className="text-center space-y-2">
              <div className="mx-auto mb-2.5 text-slate-500">
              </div>
              <h2 className="text-xl font-bold text-slate-900">Unggah Data Penggajian Karyawan</h2>
              <p className="text-xs text-slate-500 max-w-lg mx-auto leading-relaxed">
                Unggah file Excel (.xlsx) atau CSV yang berisi rincian Gaji Pokok, Tunjangan, Lembur, dan Potongan. Sertakan Kode Karyawan untuk mencocokkan slip dengan linking WhatsApp yang aktif.
              </p>
            </div>

            {/* Periode Input */}
            <div className="flex items-center justify-center gap-3 bg-slate-50 p-3 rounded-xl border border-slate-200">
              <label htmlFor="periode-input" className="text-xs font-semibold text-slate-700">Periode Penggajian:</label>
              <input
                id="periode-input"
                type="text"
                value={periode}
                onChange={(e) => setPeriode(e.target.value)}
                placeholder="Contoh: Okt-26"
                className="text-xs font-semibold px-3 py-1.5 bg-white border border-slate-300 rounded-lg text-slate-800 focus:outline-none focus:ring-2 focus:ring-indigo-500 w-36 text-center shadow-xs"
              />
              <span className="text-[11px] text-slate-400 italic">(Akan dicantumkan pada slip gaji)</span>
            </div>

            {/* Drag & Drop File Zone */}
            <div
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                if (e.dataTransfer.files?.[0]) {
                  setFile(e.dataTransfer.files[0]);
                }
              }}
              className="border-2 border-dashed border-slate-300 hover:border-indigo-400 bg-slate-50/50 hover:bg-indigo-50/20 rounded-xl p-8 text-center cursor-pointer transition-colors"
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".xlsx,.xls,.csv"
                className="hidden"
                onChange={(e) => {
                  if (e.target.files?.[0]) setFile(e.target.files[0]);
                }}
              />
              <svg className="w-10 h-10 text-slate-400 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
              </svg>
              {file ? (
                <div className="space-y-1">
                  <p className="text-sm font-semibold text-indigo-600">{file.name}</p>
                  <p className="text-xs text-slate-400">{(file.size / 1024).toFixed(1)} KB — Klik untuk ganti file</p>
                </div>
              ) : (
                <div className="space-y-1">
                  <p className="text-xs font-medium text-slate-700">
                    <span className="text-indigo-600 font-semibold underline">Klik untuk memilih file</span> atau seret file ke area ini
                  </p>
                  <p className="text-[11px] text-slate-400">Mendukung file Excel (.xlsx, .xls) dan CSV (.csv)</p>
                </div>
              )}
            </div>

            {/* Process Button */}
            <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-2 border-t border-slate-100">
              <div className="flex items-center gap-2">
                <span className="text-xs font-medium text-slate-500">Belum punya format?</span>
                <button
                  type="button"
                  onClick={() => handleDownloadTemplate("xlsx")}
                  className="text-xs text-indigo-600 hover:text-indigo-700 font-semibold underline cursor-pointer"
                >
                  Unduh Template Excel
                </button>
                <span className="text-slate-300">|</span>
                <button
                  type="button"
                  onClick={() => handleDownloadTemplate("csv")}
                  className="text-xs text-slate-600 hover:text-slate-800 font-medium underline cursor-pointer"
                >
                  CSV
                </button>
              </div>

              <button
                type="button"
                onClick={() => handleFileUpload()}
                disabled={!file || isUploading}
                className="w-full sm:w-auto px-6 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-semibold rounded-xl shadow-xs transition-colors flex items-center justify-center gap-2 cursor-pointer disabled:opacity-50"
              >
                {isUploading ? (
                  <>
                    <svg className="animate-spin h-4 w-4 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    <span>Memproses Data...</span>
                  </>
                ) : (
                  <>
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path d="M14 5l7 7m0 0l-7 7m7-7H3" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                    </svg>
                    <span>Proses Slip Gaji Sekarang</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}

        {/* ─────────────────────────────────────────────────────────────
            STATE 2: PROCESSED RESULTS, KPIS, SPREADSHEET & SLIP PREVIEW
        ───────────────────────────────────────────────────────────── */}
        {sessionId && kpis && (
          <>
            {/* 1. Summary Metrics Cards (Matching Stitch exactly) */}
            <section className="grid grid-cols-1 md:grid-cols-3 gap-4" data-purpose="summary-cards">
              {/* Card 1: Total THP */}
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Total THP Disalurkan</p>
                  <h3 className="text-2xl font-bold text-slate-900 mt-1">Rp {formatRupiah(kpis.total_thp)}</h3>
                  <span className="inline-flex items-center gap-1 text-[11px] text-emerald-600 font-medium mt-1">
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                    </svg>
                    Siap ditransfer payroll
                  </span>
                </div>
                <svg className="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M12 8c-1.657 0-3 .895-3 2s1.343 2 3 2 3 .895 3 2-1.343 2-3 2m0-8c1.11 0 2.08.402 2.599 1M12 8V7m0 1v8m0 0v1m0-1c-1.11 0-2.08-.402-2.599-1M21 12a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
              </div>

              {/* Card 2: Total Potongan */}
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Total Potongan</p>
                  <h3 className="text-2xl font-bold text-slate-900 mt-1">Rp {formatRupiah(kpis.total_potongan)}</h3>
                  <span className="text-[11px] text-slate-500 mt-1 block">BPJS, Pinjaman & Lainnya</span>
                </div>
                <svg className="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M15 12H9m12 0a9 9 0 11-18 0 9 9 0 0118 0z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
              </div>

              {/* Card 3: Total Kasbon Aktif */}
              <div className="bg-white p-4 rounded-xl border border-slate-200 shadow-xs flex items-center justify-between">
                <div>
                  <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">Total Kasbon Aktif</p>
                  <h3 className="text-2xl font-bold text-rose-600 mt-1">Rp {formatRupiah(kpis.total_kasbon_aktif)}</h3>
                  <span className="text-[11px] text-slate-500 mt-1 block">Saldo piutang karyawan</span>
                </div>
                <svg className="w-6 h-6 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path d="M9 14l6-6m-5.5.5h.01m4.99 5h.01M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16l3.5-2 3.5 2 3.5-2 3.5 2 3.5-2 3.5 2z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                </svg>
              </div>
            </section>

            {/* 2. Interactive Spreadsheet Section (Live Edit) */}
            <section className="bg-white rounded-xl border border-slate-200 shadow-xs overflow-hidden" data-purpose="payroll-spreadsheet-table">
              {/* Table Toolbar */}
              <div className="p-4 border-b border-slate-200 flex flex-wrap items-center justify-between gap-3 bg-slate-50/60">
                <div>
                  <h2 className="text-sm font-bold text-slate-800">Tabel Master Penggajian (Live Edit)</h2>
                  <p className="text-xs text-slate-500">
                    Klik baris mana saja untuk melihat slip gaji resmi di panel pratinjau. Anda dapat langsung mengedit nilai di kolom tabel di bawah ini.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <div className="relative">
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      placeholder="Cari karyawan / no rek..."
                      className="text-xs pl-8 pr-3 py-1.5 border border-slate-300 rounded-lg focus:ring-1 focus:ring-indigo-500 focus:border-indigo-500 bg-white"
                    />
                    <svg className="w-3.5 h-3.5 text-slate-400 absolute left-2.5 top-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                    </svg>
                  </div>
                  <select
                    value={filterDept}
                    onChange={(e) => setFilterDept(e.target.value)}
                    className="text-xs border border-slate-300 rounded-lg py-1.5 px-2 bg-white text-slate-700"
                  >
                    <option value="ALL">Semua Dept</option>
                    {departments.map((d) => (
                      <option key={d} value={d}>
                        {d}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              {/* Scrollable Table matching ID 10295597429383292308 */}
              <div className="overflow-x-auto max-h-[420px] divide-y divide-slate-200">
                <table className="w-full text-left text-xs whitespace-nowrap border-collapse" id="payroll-table">
                  <thead className="bg-slate-100 text-slate-700 border-b border-slate-300 sticky top-0 z-10 font-semibold shadow-xs">
                    <tr>
                      <th className="p-2.5 text-center border-r border-slate-200 w-8">#</th>
                      <th className="p-2.5 border-r border-slate-200 min-w-[105px]">Kode Karyawan</th>
                      <th className="p-2.5 border-r border-slate-200 min-w-[140px]">Nama</th>
                      <th className="p-2.5 border-r border-slate-200 min-w-[120px]">No. Rekening</th>
                      <th className="p-2.5 border-r border-slate-200 min-w-[110px]">Departemen</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[110px]">Gaji Pokok</th>
                      <th className="p-2.5 border-r border-slate-200 text-center min-w-[80px]">Potongan Hari</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[100px]">Potongan Nominal</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[110px]">Uang Makan</th>
                      <th className="p-2.5 border-r border-slate-200 text-center min-w-[70px]">Hari Kerja</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[90px]">Lembur</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[110px]">Tunjangan</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[105px]">Potongan Denda/SO</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[95px]">Potongan Telat</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[100px]">Potongan BPJS</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[110px] bg-slate-200/60 font-bold">Sub Total</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[95px]">Potongan Lain</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[110px]">Kasbon Bulan Ini</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[120px] text-rose-700">Sisa Kasbon</th>
                      <th className="p-2.5 border-r border-slate-200 text-right min-w-[120px] bg-indigo-50 text-indigo-900 font-bold">THP</th>
                      <th className="p-2.5 text-center min-w-[70px]">Aksi</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-200">
                    {filteredRows.map(({ row, originalIndex }) => {
                      const isSelected = selectedIndex === originalIndex;
                      return (
                        <tr
                          key={originalIndex}
                          onClick={() => setSelectedIndex(originalIndex)}
                          className={`cursor-pointer transition-colors ${isSelected
                              ? "bg-indigo-50/70 border-l-4 border-indigo-600 font-medium"
                              : "hover:bg-slate-50"
                            }`}
                        >
                          <td className="p-2.5 text-center border-r border-slate-200">
                            <input
                              type="radio"
                              name="selected_emp"
                              checked={isSelected}
                              onChange={() => setSelectedIndex(originalIndex)}
                              className="text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                            />
                          </td>
                          <td className="p-2.5 border-r border-slate-200 text-slate-600 font-mono text-[11px]">
                            {row["Kode Karyawan"] || "-"}
                          </td>
                          <td className="p-2.5 border-r border-slate-200 font-semibold text-slate-900">
                            {row.Nama}
                            <span
                              className={`ml-1.5 inline-block text-[10px] font-normal ${row._wa_available ? "text-emerald-600" : "text-amber-700"
                                }`}
                              title={whatsappStatusLabel(row._wa_status || "MISSING_EMPLOYEE_CODE")}
                            >
                              {row._wa_available ? "WA aktif" : whatsappStatusLabel(row._wa_status || "MISSING_EMPLOYEE_CODE")}
                            </span>
                          </td>
                          <td className="p-2.5 border-r border-slate-200 text-slate-600 font-mono text-[11px]">
                            {row["No. Rekening"] || "-"}
                          </td>
                          <td className="p-2.5 border-r border-slate-200 text-slate-700">
                            {row.Departemen || row.Dept || "-"}
                          </td>

                          {/* Editable Gaji Pokok */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              value={row["Gaji Pokok"] ?? row.GP ?? 0}
                              onChange={(e) => handleCellChange(originalIndex, "Gaji Pokok", e.target.value)}
                              className="w-24 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Potongan Hari */}
                          <td className="p-1 border-r border-slate-200 text-center">
                            <input
                              type="number"
                              min="0"
                              value={row["Potongan Hari"] ?? row["Pot Hari"] ?? 0}
                              onChange={(e) => handleCellChange(originalIndex, "Potongan Hari", e.target.value)}
                              className="w-16 text-center py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Potongan Nominal */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              min="0"
                              value={row["Potongan Nominal"] ?? row["Pot Nominal"] ?? 0}
                              onChange={(e) => handleCellChange(originalIndex, "Potongan Nominal", e.target.value)}
                              className="w-24 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Uang Makan */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              value={row["Uang Makan"] || 0}
                              onChange={(e) => handleCellChange(originalIndex, "Uang Makan", e.target.value)}
                              className="w-24 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Hari Kerja */}
                          <td className="p-1 border-r border-slate-200 text-center">
                            <input
                              type="number"
                              min="0"
                              value={row["Hari Kerja"] ?? 0}
                              onChange={(e) => handleCellChange(originalIndex, "Hari Kerja", e.target.value)}
                              className="w-16 text-center py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Lembur */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              value={row.Lembur || 0}
                              onChange={(e) => handleCellChange(originalIndex, "Lembur", e.target.value)}
                              className="w-20 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Tunjangan */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              value={row.Tunjangan || 0}
                              onChange={(e) => handleCellChange(originalIndex, "Tunjangan", e.target.value)}
                              className="w-24 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Potongan Denda/SO */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              min="0"
                              value={row["Potongan Denda/SO"] ?? row["Pot Denda/SO"] ?? 0}
                              onChange={(e) => handleCellChange(originalIndex, "Potongan Denda/SO", e.target.value)}
                              className="w-24 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Potongan Telat */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              min="0"
                              value={row["Potongan Telat"] ?? row["Pot Telat"] ?? 0}
                              onChange={(e) => handleCellChange(originalIndex, "Potongan Telat", e.target.value)}
                              className="w-24 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Potongan BPJS */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              value={row["Potongan BPJS"] ?? row["Pot BPJS"] ?? 0}
                              onChange={(e) => handleCellChange(originalIndex, "Potongan BPJS", e.target.value)}
                              className="w-20 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Sub Total Calculated */}
                          <td className="p-2.5 border-r border-slate-200 text-right font-semibold text-slate-800 bg-slate-100/50">
                            {formatRupiah(row["Sub Total"])}
                          </td>

                          {/* Editable Potongan Lain */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              min="0"
                              value={row["Potongan Lain"] ?? row["Pot Lain"] ?? 0}
                              onChange={(e) => handleCellChange(originalIndex, "Potongan Lain", e.target.value)}
                              className="w-24 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Kasbon Bulan Ini */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              value={row["Kasbon Bulan Ini"] || 0}
                              onChange={(e) => handleCellChange(originalIndex, "Kasbon Bulan Ini", e.target.value)}
                              className="w-24 text-right py-1 px-1.5 text-xs rounded border border-slate-200 focus:border-indigo-500 focus:bg-white bg-slate-50/40"
                            />
                          </td>

                          {/* Editable Sisa Kasbon */}
                          <td className="p-1 border-r border-slate-200 text-right">
                            <input
                              type="number"
                              min="0"
                              value={row["Sisa Kasbon"] ?? 0}
                              onChange={(e) => handleCellChange(originalIndex, "Sisa Kasbon", e.target.value)}
                              className="w-24 text-right py-1 px-1.5 text-xs rounded border border-rose-200 focus:border-rose-500 focus:bg-white bg-rose-50/30 text-rose-700 font-medium"
                            />
                          </td>

                          {/* THP Calculated */}
                          <td className="p-2.5 border-r border-slate-200 text-right font-bold text-indigo-700 bg-indigo-50/60">
                            {formatRupiah(row.THP)}
                          </td>

                          <td className="p-2.5 text-center">
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                setSelectedIndex(originalIndex);
                              }}
                              className="px-2 py-1 text-[11px] bg-slate-200 hover:bg-indigo-600 hover:text-white rounded transition-colors cursor-pointer"
                            >
                              Pilih
                            </button>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>

              <div className="px-4 py-3 bg-slate-50 border-t border-slate-200 text-[11px] text-slate-500 flex justify-between items-center">
                <span>Menampilkan {filteredRows.length} dari {rows.length} entri data penggajian</span>
                <span className="italic text-slate-400">
                  Nilai input di kolom tabel langsung tersinkronisasi otomatis ke slip gaji dan ringkasan.
                </span>
              </div>
            </section>

            {/* 3. Official Slip Gaji Preview (Document Sheet Replica from Stitch ID 10295597429383292308) */}
            {selectedEmployee && (
              <section className="space-y-4 pt-4" data-purpose="slip-gaji-preview">
                {/* Header of Preview */}
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <h2 className="text-base font-bold text-slate-900 flex items-center gap-2">
                      <svg className="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                      </svg>
                      Pratinjau Resmi Slip Gaji Karyawan
                    </h2>
                    <p className="text-xs text-slate-500">
                      Tata letak dan tipografi persis standar cetak dokumen PT. Javareef Indonesia Perkasa (Sesuai Rekap)
                    </p>
                  </div>

                  {/* Actions for this individual slip */}
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handlePrintSlip}
                      className="px-3 py-1.5 text-xs font-medium bg-slate-800 text-white hover:bg-slate-900 rounded shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path d="M17 17h2a2 2 0 002-2v-4a2 2 0 00-2-2H5a2 2 0 00-2 2v4a2 2 0 002 2h2m2 4h6a2 2 0 002-2v-4H7v4a2 2 0 002 2zm8-12V5a2 2 0 00-2-2H9a2 2 0 00-2 2v4h10z" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                      </svg>
                      Cetak / Print Slip
                    </button>

                    <button
                      type="button"
                      onClick={handleDownloadSinglePdf}
                      disabled={isDownloadingPdf}
                      className="px-3 py-1.5 text-xs font-medium bg-emerald-600 text-white hover:bg-emerald-700 rounded shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
                    >
                      <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                      </svg>
                      {isDownloadingPdf ? "Membuat PDF..." : "Unduh PDF"}
                    </button>

                    <button
                      type="button"
                      onClick={handleSendSingleWhatsApp}
                      disabled={singleWaSending || !selectedEmployee["Kode Karyawan"]}
                      title={
                        selectedEmployee["Kode Karyawan"]
                          ? `Status saat upload: ${whatsappStatusLabel(selectedEmployee._wa_status || "")}. Link aktif akan diperiksa lagi sebelum kirim.`
                          : "Isi Kode Karyawan pada file payroll untuk mengirim slip."
                      }
                      className={`px-3 py-1.5 text-xs font-medium text-white rounded shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer ${selectedEmployee["Kode Karyawan"]
                          ? "bg-[#25D366] hover:bg-[#1ebd5a]"
                          : "bg-slate-400 cursor-not-allowed opacity-60"
                        }`}
                    >
                      <svg className="w-3.5 h-3.5 fill-current" viewBox="0 0 24 24">
                        <path d="M.057 24l1.687-6.163c-1.041-1.804-1.588-3.849-1.587-5.946.003-6.556 5.338-11.891 11.893-11.891 3.181.001 6.167 1.24 8.413 3.488 2.245 2.248 3.481 5.236 3.48 8.414-.003 6.557-5.338 11.892-11.893 11.892-1.99-.001-3.951-.5-5.688-1.448l-6.305 1.654zm6.597-3.807c1.676.995 3.276 1.591 5.392 1.592 5.448 0 9.886-4.434 9.889-9.885.002-5.462-4.415-9.89-9.881-9.892-5.452 0-9.887 4.434-9.889 9.884-.001 2.225.651 3.891 1.746 5.634l-.999 3.648 3.742-.981z" />
                      </svg>
                      {singleWaSending ? "Mengirim..." : "Kirim WhatsApp"}
                    </button>
                  </div>
                </div>

                {/* Official Document Sheet (EXACT REPLICA OF STITCH) */}
                <div
                  className="bg-white border-2 border-slate-800 rounded-none shadow-md max-w-4xl mx-auto p-8 font-sans text-black"
                  id="printable-slip"
                  ref={slipPreviewRef}
                >
                  {/* Document Header (Kop Surat) */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between gap-4 mb-2">
                      <div className="flex-shrink-0 w-32 flex items-center">
                        <img
                          src="/logo.png"
                          alt="Logo PT. Javareef Indonesia Perkasa"
                          className="h-12 w-auto object-contain"
                        />
                      </div>
                      <div className="flex-1 text-center pr-32">
                        <h2 className="text-xl font-black font-serif tracking-tight text-black uppercase">
                          PT. Javareef Indonesia Perkasa
                        </h2>
                        <p className="text-[11px] text-black font-medium mt-0.5">
                          Jl. Kav. DPR Blk. A No.306, RT.003/RW.001, Kenanga, Kec. Cipondoh, Kota Tangerang, Banten 15146
                        </p>
                      </div>
                    </div>
                    {/* Double Line Kop Surat */}
                    <div className="mt-2 border-b-[2px] border-black" />
                    <div className="mt-[2px] border-b-[1px] border-black" />
                  </div>

                  {/* Document Subtitle */}
                  <div className="text-right text-xs font-semibold mb-2">
                    Slip Gaji Karyawan
                  </div>

                  {/* Employee & Period Metadata Grid */}
                  <div className="grid grid-cols-2 text-xs font-normal mb-3 leading-relaxed">
                    <div className="space-y-0.5">
                      <div className="grid grid-cols-12">
                        <span className="col-span-3">Nama</span>
                        <span className="col-span-1">:</span>
                        <span className="col-span-8 font-semibold">{selectedEmployee.Nama}</span>
                      </div>
                      <div className="grid grid-cols-12">
                        <span className="col-span-3">Dept.</span>
                        <span className="col-span-1">:</span>
                        <span className="col-span-8">{selectedEmployee.Departemen || selectedEmployee.Dept || "-"}</span>
                      </div>
                      <div className="grid grid-cols-12">
                        <span className="col-span-3">No. Rek.</span>
                        <span className="col-span-1">:</span>
                        <span className="col-span-8 font-mono">{selectedEmployee["No. Rekening"] || "-"}</span>
                      </div>
                    </div>
                    <div className="space-y-0.5 pl-6">
                      <div className="grid grid-cols-12">
                        <span className="col-span-4">Kode Karyawan</span>
                        <span className="col-span-1">:</span>
                        <span className="col-span-7 font-mono">{selectedEmployee["Kode Karyawan"] || "-"}</span>
                      </div>
                      <div className="grid grid-cols-12">
                        <span className="col-span-4">Periode</span>
                        <span className="col-span-1">:</span>
                        <span className="col-span-7">{periode}</span>
                      </div>
                      <div className="grid grid-cols-12">
                        <span className="col-span-4">Hari Kerja</span>
                        <span className="col-span-1">:</span>
                        <span className="col-span-7">{selectedEmployee["Hari Kerja"] || 0} hari</span>
                      </div>
                      <div className="grid grid-cols-12">
                        <span className="col-span-4">WhatsApp</span>
                        <span className="col-span-1">:</span>
                        <span className="col-span-7 font-mono">
                          {selectedEmployee._wa_number || whatsappStatusLabel(selectedEmployee._wa_status || "MISSING_EMPLOYEE_CODE")}
                        </span>
                      </div>
                    </div>
                  </div>

                  {/* Financial Breakdown Table / 2 Columns Side by Side */}
                  <div className="grid grid-cols-2 gap-8 text-xs">
                    {/* LEFT COLUMN: PENDAPATAN */}
                    <div className="flex flex-col justify-between">
                      <div>
                        <div className="font-bold border-b border-black pb-1 mb-2 tracking-wide uppercase">
                          PENDAPATAN
                        </div>
                        <div className="space-y-1">
                          <div className="flex justify-between items-center">
                            <span className="w-36">Gaji Pokok</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">{formatRupiah(selectedEmployee["Gaji Pokok"] ?? selectedEmployee.GP)}</span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-36">Uang Makan</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">{formatRupiah(selectedEmployee["Uang Makan"])}</span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-36">Tunjangan Jabatan</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">{formatRupiah(selectedEmployee.Tunjangan)}</span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-36">Lembur</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">
                              {selectedEmployee.Lembur ? formatRupiah(selectedEmployee.Lembur) : "-"}
                            </span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-36">THR</span>
                            <span className="w-8">:</span>
                            <span className="flex-1 text-right">-</span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-36">Lain - Lain</span>
                            <span className="w-8">:</span>
                            <span className="flex-1 text-right">-</span>
                          </div>
                        </div>
                      </div>

                      {/* Subtotal Pendapatan with Double Border Bottom */}
                      <div className="mt-4 pt-2 border-t border-black">
                        <div className="flex justify-between items-center font-bold leading-5 pb-2">
                          <span data-testid="income-subtotal-text" className="w-36">Total Pendapatan</span>
                          <span className="w-8">: Rp</span>
                          <span className="flex-1 text-right">{formatRupiah(selectedEmployee["Sub Total"])}</span>
                        </div>
                        <div data-testid="income-subtotal-rule" className="border-b-[2px] border-black" />
                        <div className="border-b border-black mt-1" />
                      </div>
                    </div>

                    {/* RIGHT COLUMN: POTONGAN */}
                    <div className="flex flex-col justify-between">
                      <div>
                        <div className="font-bold border-b border-black pb-1 mb-2 tracking-wide uppercase">
                          POTONGAN
                        </div>
                        <div className="space-y-1">
                          <div className="flex justify-between items-center">
                            <span className="w-56 whitespace-normal leading-4">Denda Keterlambatan / Keluar awal</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">
                              {(selectedEmployee["Potongan Denda/SO"] || selectedEmployee["Pot Denda/SO"]) ? formatRupiah(selectedEmployee["Potongan Denda/SO"] ?? selectedEmployee["Pot Denda/SO"]) : "-"}
                            </span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-56 whitespace-normal leading-4">BPJS Kesehatan & Ketenagakerjaan</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">
                              {(selectedEmployee["Potongan BPJS"] || selectedEmployee["Pot BPJS"]) ? formatRupiah(selectedEmployee["Potongan BPJS"] ?? selectedEmployee["Pot BPJS"]) : "-"}
                            </span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-56 whitespace-normal leading-4">Pinjaman / Kasbon</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">
                              {selectedEmployee["Kasbon Bulan Ini"] ? formatRupiah(selectedEmployee["Kasbon Bulan Ini"]) : "-"}
                            </span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-56 whitespace-normal leading-4">Tidak Hadir / Prorata</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">
                              {(selectedEmployee["Potongan Nominal"] || selectedEmployee["Pot Nominal"]) ? formatRupiah(selectedEmployee["Potongan Nominal"] ?? selectedEmployee["Pot Nominal"]) : "-"}
                            </span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-56 whitespace-normal leading-4">Potongan Telat</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">
                              {(selectedEmployee["Potongan Telat"] || selectedEmployee["Pot Telat"]) ? formatRupiah(selectedEmployee["Potongan Telat"] ?? selectedEmployee["Pot Telat"]) : "-"}
                            </span>
                          </div>
                          <div className="flex justify-between items-center">
                            <span className="w-56 whitespace-normal leading-4">Potongan Lain - Lain</span>
                            <span className="w-8">: Rp</span>
                            <span className="flex-1 text-right">
                              {(selectedEmployee["Potongan Lain"] || selectedEmployee["Pot Lain"]) ? formatRupiah(selectedEmployee["Potongan Lain"] ?? selectedEmployee["Pot Lain"]) : "-"}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Subtotal Potongan with Double Border Bottom */}
                      <div className="mt-4 pt-2 border-t border-black">
                        <div className="flex justify-between items-center font-bold leading-5 pb-2">
                          <span data-testid="deduction-subtotal-text" className="w-36">Total Potongan</span>
                          <span className="w-8">: Rp</span>
                          <span className="flex-1 text-right">{formatRupiah(selectedEmployee["Total Potongan"])}</span>
                        </div>
                        <div data-testid="deduction-subtotal-rule" className="border-b-[2px] border-black" />
                        <div className="border-b border-black mt-1" />
                      </div>
                    </div>
                  </div>

                  {/* Bottom Footer Section: TOTAL JUMLAH DITERIMA & SISA PINJAMAN */}
                  <div className="mt-8 pt-2 flex justify-between items-start text-xs">
                    <div className="space-y-1">
                      {/* TOTAL JUMLAH DITERIMA with Exact Excel Border Box Style */}
                      <div className="flex items-center">
                        <span className="font-bold italic mr-4 tracking-wide w-44">TOTAL JUMLAH DITERIMA</span>
                        <div data-testid="net-pay-box" className="border border-black px-4 py-2 font-bold flex items-center justify-between min-h-10 min-w-[210px] leading-5 bg-white">
                          <span className="italic font-bold">Rp</span>
                          <span data-testid="net-pay-value" className="font-bold tracking-tight text-sm">{formatRupiah(selectedEmployee.THP)}</span>
                        </div>
                      </div>
                      {/* Sisa Pinjaman (Red, Italic exact styling) */}
                      <div className="flex items-center text-red-600 italic font-medium">
                        <span className="mr-4 w-44">Sisa Pinjaman</span>
                        <div className="px-4 py-0.5 flex items-center justify-between min-w-[210px]">
                          <span>Rp</span>
                          <span className="font-semibold tracking-tight">{formatRupiah(selectedEmployee["Sisa Kasbon"])}</span>
                        </div>
                      </div>
                    </div>

                    {/* Signature Section Right Side */}
                    <div className="text-center w-52 pt-1">
                      <p className="text-xs mb-14 text-black">Penerima</p>
                      <div data-testid="recipient-name-box" className="border border-emerald-700 px-3 py-2 min-h-10 text-xs text-black font-semibold bg-white flex items-center justify-center leading-5">
                        <span data-testid="recipient-name">{selectedEmployee.Nama}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </section>
            )}
          </>
        )}
      </main>

      {/* ─────────────────────────────────────────────────────────────
          MODAL: WHATSAPP BLAST TO ALL EMPLOYEES
      ───────────────────────────────────────────────────────────── */}
      {waModalOpen && (
        <div className="fixed inset-0 bg-slate-900/60 backdrop-blur-xs flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-2xl max-w-2xl max-h-[90vh] w-full p-6 shadow-xl border border-slate-200 space-y-4 overflow-y-auto">
            <div className="flex items-center justify-between border-b border-slate-100 pb-3">
              <div className="flex items-center gap-2">
                <div>
                  <h3 className="text-sm font-bold text-slate-900">Kirim Slip Gaji via WhatsApp</h3>
                  <p className="text-xs text-slate-500">Periode: {periode}</p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setWaModalOpen(false)}
                className="text-slate-400 hover:text-slate-600 font-bold text-lg p-1 cursor-pointer"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-slate-600 leading-relaxed">
              Periksa penerima yang dipasangkan dengan Kode Karyawan. Sistem mengirim rincian penghasilan sebagai teks
              dan melampirkan PDF slip resmi. Status linking divalidasi ulang oleh server saat pengiriman.
            </p>

            <div className="bg-slate-50 p-3 rounded-xl border border-slate-200 text-xs space-y-1">
              <div className="flex justify-between">
                <span className="text-slate-500">Total Karyawan dalam Berkas:</span>
                <span className="font-bold text-slate-800">{rows.length}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Link WhatsApp aktif sekarang:</span>
                <span className="font-bold text-emerald-600">
                  {waPreviewLoading ? "Memeriksa..." : waPreview.filter((r) => r.status === "ACTIVE").length}
                </span>
              </div>
              <div className="flex justify-between">
                <span className="text-slate-500">Belum tertaut/tidak valid:</span>
                <span className="font-bold text-amber-600">
                  {waPreviewLoading ? "Memeriksa..." : waPreview.filter((r) => r.status !== "ACTIVE").length}
                </span>
              </div>
            </div>

            <div className="max-h-52 overflow-y-auto border border-slate-200 rounded-lg">
              <table className="w-full text-left text-xs">
                <thead className="sticky top-0 bg-slate-100 text-slate-600">
                  <tr>
                    <th className="p-2">Karyawan</th>
                    <th className="p-2">Nomor WhatsApp</th>
                    <th className="p-2">Status linking</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {waPreview.map((recipient) => (
                    <tr key={`${recipient.row_index}-${recipient.employee_code}`}>
                      <td className="p-2">
                        <div className="font-medium text-slate-800">{recipient.nama || "-"}</div>
                        <div className="font-mono text-[10px] text-slate-500">{recipient.employee_code || "-"}</div>
                      </td>
                      <td className="p-2 font-mono">{recipient.wa_number || "-"}</td>
                      <td className={`p-2 ${recipient.status === "ACTIVE" ? "text-emerald-700" : "text-amber-700"}`}>
                        {whatsappStatusLabel(recipient.status)}
                      </td>
                    </tr>
                  ))}
                  {!waPreviewLoading && waPreview.length === 0 && (
                    <tr>
                      <td colSpan={3} className="p-3 text-center text-slate-500">
                        Belum ada data penerima untuk ditinjau.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Result report if already sent */}
            {waResults && (
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-xl text-xs space-y-2">
                <div className="font-semibold text-emerald-800 flex items-center gap-1.5">
                  <svg className="w-4 h-4 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path d="M5 13l4 4L19 7" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" />
                  </svg>
                  <span>Hasil Pengiriman Blast:</span>
                </div>
                <div className="grid grid-cols-4 gap-2 text-center pt-1">
                  <div className="bg-white p-2 rounded-lg border border-emerald-100">
                    <span className="text-[10px] text-slate-400 block uppercase">Terkirim</span>
                    <span className="text-base font-bold text-emerald-600">{waResults.sent}</span>
                  </div>
                  <div className="bg-white p-2 rounded-lg border border-emerald-100">
                    <span className="text-[10px] text-slate-400 block uppercase">Dilewati</span>
                    <span className="text-base font-bold text-amber-600">{waResults.skip}</span>
                  </div>
                  <div className="bg-white p-2 rounded-lg border border-emerald-100">
                    <span className="text-[10px] text-slate-400 block uppercase">Sebagian</span>
                    <span className="text-base font-bold text-orange-600">{waResults.partial || 0}</span>
                  </div>
                  <div className="bg-white p-2 rounded-lg border border-emerald-100">
                    <span className="text-[10px] text-slate-400 block uppercase">Gagal</span>
                    <span className="text-base font-bold text-rose-600">{waResults.failed}</span>
                  </div>
                </div>
                <div className="max-h-32 overflow-y-auto divide-y divide-slate-200">
                  {waResults.results?.map((result: any) => (
                    <div key={`${result.row_index}-${result.delivery_id}`} className="flex justify-between gap-3 py-1.5">
                      <span>
                        {result.nama} ({result.wa_number || result.reason || "tanpa nomor"})
                        {result.detail && <span className="block text-slate-500">{result.detail}</span>}
                      </span>
                      <span className="font-semibold">{result.status}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {waHistory.length > 0 && (
              <details className="border border-slate-200 rounded-lg text-xs">
                <summary className="p-2.5 font-semibold text-slate-700 cursor-pointer">
                  Riwayat percobaan pengiriman ({waHistory.length})
                </summary>
                <div className="max-h-36 overflow-y-auto divide-y divide-slate-100 px-2.5">
                  {waHistory.slice(0, 10).map((delivery) => (
                    <div key={delivery.id} className="flex justify-between gap-3 py-2">
                      <span>
                        {delivery.nama} · {delivery.employee_code || "-"} · {delivery.wa_number || "tanpa nomor"}
                      </span>
                      <span className="shrink-0 font-semibold">
                        {delivery.status} (teks {delivery.text_status || "-"}, PDF {delivery.pdf_status || "-"})
                      </span>
                    </div>
                  ))}
                </div>
              </details>
            )}

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-slate-100">
              <button
                type="button"
                onClick={() => setWaModalOpen(false)}
                className="px-4 py-2 text-xs font-medium text-slate-600 hover:bg-slate-100 rounded-lg transition-colors cursor-pointer"
              >
                Tutup
              </button>
              <button
                type="button"
                onClick={handleSendAllWhatsApp}
                disabled={
                  waSending ||
                  waPreviewLoading ||
                  waPreview.filter((r) => r.status === "ACTIVE").length === 0
                }
                className="px-4 py-2 text-xs font-semibold bg-[#25D366] hover:bg-[#1ebd5a] text-white rounded-lg shadow-xs transition-colors flex items-center gap-1.5 cursor-pointer disabled:opacity-50"
              >
                {waSending ? (
                  <>
                    <svg className="animate-spin h-3.5 w-3.5 text-white" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                    </svg>
                    <span>Mengirim Blast...</span>
                  </>
                ) : (
                  <>
                    <span>Mulai Kirim Sekarang</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
