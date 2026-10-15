import { expect, test, type Page, type Route } from "@playwright/test";
import { writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

interface BrowserEmployee {
  id: number;
  new_employee_id: string;
  nik: string;
  nama: string;
  profile_code: string;
  cabang: string;
  active: boolean;
  employment_status: string;
  join_date: string | null;
  contract_reminder_status: {
    is_expired: boolean;
    is_expiring: boolean;
    days_left: number;
  } | null;
  has_custom_rules: boolean;
  jam_masuk_override: string | null;
  jam_keluar_override: string | null;
  toleransi_telat_menit_override: number | null;
  bonus_lembur_per_jam_override: number | null;
  uang_makan_override: number | null;
  bpjs_kesehatan: number | null;
  bpjs_tk: number | null;
  id_mesin: string | null;
  contracts: {
    id: number;
    contract_number: number;
    start_date: string;
    end_date: string;
    status: string;
    keterangan: string;
  }[];
  phl_to_pkwt_transitions: {
    id: number;
    employment_contract_id: number;
    phl_start_date: string;
    phl_end_date: string;
    transition_date: string;
    created_at: string;
  }[];
}

const employees: BrowserEmployee[] = [
  {
    id: 1,
    new_employee_id: "EMP-QA-001",
    nik: "3200000000000001",
    nama: "Andi Contoh",
    profile_code: "OFFICE",
    cabang: "Bandung",
    active: true,
    employment_status: "PKWTT",
    join_date: "2023-01-01",
    contracts: [],
    phl_to_pkwt_transitions: [],
    contract_reminder_status: null,
    has_custom_rules: false,
    jam_masuk_override: null,
    jam_keluar_override: null,
    toleransi_telat_menit_override: null,
    bonus_lembur_per_jam_override: null,
    uang_makan_override: null,
    bpjs_kesehatan: null,
    bpjs_tk: null,
    id_mesin: null,
  },
  {
    id: 2,
    new_employee_id: "EMP-QA-002",
    nik: "3200000000000002",
    nama: "Siti Contoh",
    profile_code: "OFFICE",
    cabang: "Cabang Lama",
    active: true,
    employment_status: "PKWT",
    join_date: "2024-02-01",
    contracts: [],
    phl_to_pkwt_transitions: [],
    contract_reminder_status: null,
    has_custom_rules: false,
    jam_masuk_override: null,
    jam_keluar_override: null,
    toleransi_telat_menit_override: null,
    bonus_lembur_per_jam_override: null,
    uang_makan_override: null,
    bpjs_kesehatan: null,
    bpjs_tk: null,
    id_mesin: null,
  },
  {
    id: 3,
    new_employee_id: "EMP-QA-003",
    nik: "3200000000000003",
    nama: "Budi PHL",
    profile_code: "OFFICE",
    cabang: "Bandung",
    active: true,
    employment_status: "PHL",
    join_date: "2025-04-01",
    contracts: [],
    phl_to_pkwt_transitions: [],
    contract_reminder_status: null,
    has_custom_rules: false,
    jam_masuk_override: null,
    jam_keluar_override: null,
    toleransi_telat_menit_override: null,
    bonus_lembur_per_jam_override: null,
    uang_makan_override: null,
    bpjs_kesehatan: null,
    bpjs_tk: null,
    id_mesin: null,
  },
];

const profile = {
  code: "OFFICE",
  nama: "Office",
  cabang: ["Bandung", "Jakarta"],
  hari_kerja: ["Senin", "Selasa", "Rabu", "Kamis", "Jumat"],
  jam_masuk: { default: "08:00" },
  jam_keluar: { default: "17:00" },
};

function pendingLeave() {
  return {
    id: 41,
    nama: "Karyawan QA",
    kategori: "CUTI_TAHUNAN",
    tanggal_mulai: "2026-11-02",
    tanggal_selesai: "2026-11-02",
    jumlah_hari: 1,
    jam_izin: null,
    alasan: "Tes browser",
    foto_bukti: null,
    catatan_hr: null,
    status: "PENDING" as "PENDING" | "APPROVED",
    approved_by: null,
    approved_at: null,
    created_at: "2026-10-08T08:00:00",
    tipe_absensi: null,
    location_cabang: null,
  };
}

async function fulfillJson(route: Route, data: unknown, status = 200) {
  const origin = route.request().headers().origin;
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: {
      "access-control-allow-origin": origin || "*",
    },
    body: JSON.stringify(data),
  });
}

async function mockApi(
  page: Page,
  options: {
    loginFails?: boolean;
    historyForPhl?: boolean;
    expiringContract?: boolean;
    processResult?: boolean;
    payroll?: boolean;
  } = {},
) {
  const leave = pendingLeave();
  const testEmployees = employees.map((employee) => ({
    ...employee,
    contracts: employee.contracts.map((contract) => ({ ...contract })),
    phl_to_pkwt_transitions: employee.phl_to_pkwt_transitions.map((transition) => ({ ...transition })),
  }));
  if (options.historyForPhl) {
    const phlEmployee = testEmployees.find((employee) => employee.id === 3);
    if (phlEmployee) {
      phlEmployee.employment_status = "PKWT";
      phlEmployee.contracts.push({
        id: 101,
        contract_number: 1,
        start_date: "2026-10-01",
        end_date: "2027-09-30",
        status: "ACTIVE",
        keterangan: "Transisi PHL ke PKWT",
      });
      phlEmployee.phl_to_pkwt_transitions.push({
        id: 51,
        employment_contract_id: 101,
        phl_start_date: "2025-04-01",
        phl_end_date: "2026-09-30",
        transition_date: "2026-10-01",
        created_at: "2026-10-12T08:00:00",
      });
    }
  }
  let leaveStatusUpdate: { status: string } | null = null;
  let employeeUpdatePayload: Record<string, unknown> | null = null;
  let processResult: {
    file_id: string;
    filename: string;
    kpis: Record<string, number>;
    sheets: {
      key: string;
      title: string;
      data: { headers: string[]; types: Record<string, string>; rows: Record<string, unknown>[] };
    }[];
    cabang_list: string[];
    profil_list: string[];
    periode: null;
    upload_batch_id: number;
  } | null = null;
  let payrollHistory: Record<string, unknown>[] = [];
  let payrollPdfUploaded = false;

  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const isLocalBackend = url.port === "8000";
    const isMockApi = url.pathname.startsWith("/__mock_api/");
    if (!isLocalBackend && !isMockApi) {
      await route.continue();
      return;
    }
    if (request.method() === "OPTIONS") {
      await route.fulfill({
        status: 204,
        headers: {
          "access-control-allow-origin": request.headers().origin || "*",
          "access-control-allow-methods": "GET, POST, PUT, PATCH, DELETE, OPTIONS",
          "access-control-allow-headers": "Authorization, Content-Type",
        },
      });
      return;
    }

    const path = url.pathname.replace(/^\/__mock_api/, "");
    const method = request.method();

    if (path === "/auth/login" && method === "POST") {
      if (options.loginFails) {
        await fulfillJson(route, { detail: "Email atau password salah." }, 401);
        return;
      }
      await fulfillJson(route, {
        access_token: "synthetic-browser-test-token",
        role: "hr_master",
        nama: "Pengguna QA",
      });
      return;
    }
    if (path === "/profiles") {
      await fulfillJson(route, [profile]);
      return;
    }
    if (path === "/payroll/upload" && method === "POST" && options.payroll) {
      await fulfillJson(route, {
        session_id: "synthetic-payroll-session",
        periode: "Okt-26",
        rows: [
          {
            "ID Karyawan": "EMP-QA-101",
            Nama: "Karyawan Tertaut",
            "No. Rekening": "000111",
            Departemen: "Operasional",
            "Gaji Pokok": 4000000,
            "Potongan Hari": 0,
            "Potongan Nominal": 0,
            "Uang Makan": 0,
            "Hari Kerja": 20,
            Lembur: 0,
            Tunjangan: 0,
            "Potongan Denda/SO": 0,
            "Potongan Telat": 0,
            "Potongan BPJS": 0,
            "Sub Total": 4000000,
            "Potongan Lain": 0,
            "Kasbon Bulan Ini": 0,
            "Sisa Kasbon": 0,
            THP: 4000000,
            _wa_available: true,
            _wa_status: "ACTIVE",
          },
          {
            "ID Karyawan": "EMP-QA-102",
            Nama: "Karyawan Belum Tertaut",
            "No. Rekening": "000222",
            Departemen: "Operasional",
            "Gaji Pokok": 3500000,
            "Potongan Hari": 0,
            "Potongan Nominal": 0,
            "Uang Makan": 0,
            "Hari Kerja": 20,
            Lembur: 0,
            Tunjangan: 0,
            "Potongan Denda/SO": 0,
            "Potongan Telat": 0,
            "Potongan BPJS": 0,
            "Sub Total": 3500000,
            "Potongan Lain": 0,
            "Kasbon Bulan Ini": 0,
            "Sisa Kasbon": 0,
            THP: 3500000,
            _wa_available: false,
            _wa_status: "WHATSAPP_NOT_LINKED",
          },
        ],
        kpis: { total_thp: 7500000, total_potongan: 0, total_kasbon_aktif: 0 },
      });
      return;
    }
    if (options.payroll && path === "/payroll/synthetic-payroll-session/whatsapp-recipients") {
      await fulfillJson(route, {
        periode: "Okt-26",
        recipients: [
          {
            row_index: 0,
            employee_id: 101,
            new_employee_id: "EMP-QA-101",
            nama: "Karyawan Tertaut",
            wa_number: "628100000101",
            status: "ACTIVE",
          },
          {
            row_index: 1,
            employee_id: 102,
            new_employee_id: "EMP-QA-102",
            nama: "Karyawan Belum Tertaut",
            wa_number: null,
            status: "WHATSAPP_NOT_LINKED",
          },
        ],
      });
      return;
    }
    if (options.payroll && path === "/payroll/synthetic-payroll-session/send-history") {
      await fulfillJson(route, payrollHistory);
      return;
    }
    if (
      options.payroll &&
      path === "/payroll/synthetic-payroll-session/send-whatsapp/0" &&
      method === "POST"
    ) {
      const requestBody = request.postDataBuffer();
      const pdfStart = requestBody?.indexOf("%PDF-") ?? -1;
      const pdfEnd = requestBody?.indexOf("%%EOF", pdfStart) ?? -1;
      payrollPdfUploaded = pdfStart >= 0 && pdfEnd >= pdfStart;
      if (payrollPdfUploaded && requestBody) {
        writeFileSync(
          join(tmpdir(), "preview-rendered-payroll-test.pdf"),
          requestBody.subarray(pdfStart, pdfEnd + 5),
        );
      }
      payrollHistory = [{
        id: 501,
        row_index: 0,
        employee_id: 101,
        new_employee_id: "EMP-QA-101",
        nama: "Karyawan Tertaut",
        periode: "Okt-26",
        wa_number: "628100000101",
        status: "SENT",
        text_status: "SENT",
        pdf_status: "SENT",
        created_at: "2026-10-13T08:00:00",
        completed_at: "2026-10-13T08:00:01",
      }];
      await fulfillJson(route, {
        status: "SENT",
        nama: "Karyawan Tertaut",
        wa_number: "628100000101",
        text_sent: true,
        pdf_sent: true,
        delivery_id: 501,
      });
      return;
    }
    if (path === "/rules") {
      await fulfillJson(route, {});
      return;
    }
    if (path === "/employees/contracts/expiring") {
      const data = options.expiringContract ? [{
        employee_id: 3,
        nama: "Budi PHL",
        cabang: "Bandung",
        profile_code: "OFFICE",
        join_date: "2025-04-01",
        tenure_display: "1 tahun",
        contract_id: 101,
        contract_number: 1,
        start_date: "2026-10-01",
        end_date: "2026-10-20",
        days_left: 8,
        status_label: "Segera Berakhir",
        is_expired: false,
        message: "Kontrak segera berakhir",
      }] : [];
      await fulfillJson(route, { data, total: data.length, reminder_days_config: 10 });
      return;
    }
    if (path === "/employees/whatsapp-identities" || path === "/employees/whatsapp-audit") {
      await fulfillJson(route, []);
      return;
    }
    if (path === "/employees") {
      await fulfillJson(route, testEmployees);
      return;
    }
    if (path === "/proses-absensi-manual" && method === "POST" && options.processResult) {
      processResult = {
        file_id: "synthetic-process-file",
        filename: "Synthetic HR report.xlsx",
        kpis: {
          total_karyawan: 1,
          total_telat: 0,
          total_lembur: 0,
          total_bonus_lembur: 0,
          total_uang_makan: 1000,
          total_bersih: 1050,
          total_pulang_duluan: 0,
          total_baris_scan: 2,
        },
        sheets: [{
          key: "summary",
          title: "Summary Overview",
          data: {
            headers: [
              "Cabang",
              "Nama",
              "Profil",
              "Total Bonus Lain-lain (Rp)",
              "Total Potongan Lain-lain (Rp)",
              "Total Bersih (Rp)",
            ],
            types: {
              "Total Bonus Lain-lain (Rp)": "currency",
              "Total Potongan Lain-lain (Rp)": "currency",
              "Total Bersih (Rp)": "currency",
            },
            rows: [{
              Cabang: "Bandung",
              Nama: "Karyawan QA",
              Profil: "OFFICE",
              "Total Bonus Lain-lain (Rp)": 100,
              "Total Potongan Lain-lain (Rp)": 50,
              "Total Bersih (Rp)": 1050,
            }],
          },
        }],
        cabang_list: ["Bandung"],
        profil_list: ["OFFICE"],
        periode: null,
        upload_batch_id: 77,
      };
      await fulfillJson(route, processResult);
      return;
    }
    if (/^\/proses\/[^/]+\/adjustments$/.test(path) && method === "PATCH" && processResult) {
      const payload = request.postDataJSON() as {
        nama: string;
        bonus_lain: number;
        potongan_lain: number;
      };
      const row = processResult.sheets[0].data.rows.find(
        (item) => item.Nama === payload.nama,
      );
      if (!row) {
        await fulfillJson(route, { detail: "Karyawan tidak ditemukan pada ringkasan file proses ini." }, 404);
        return;
      }
      const oldBonus = Number(row["Total Bonus Lain-lain (Rp)"] || 0);
      const oldDeduction = Number(row["Total Potongan Lain-lain (Rp)"] || 0);
      row["Total Bonus Lain-lain (Rp)"] = payload.bonus_lain;
      row["Total Potongan Lain-lain (Rp)"] = payload.potongan_lain;
      row["Total Bersih (Rp)"] = Number(row["Total Bersih (Rp)"] || 0)
        + payload.bonus_lain - oldBonus - payload.potongan_lain + oldDeduction;
      processResult.kpis.total_bersih = row["Total Bersih (Rp)"] as number;
      await fulfillJson(route, {
        status: "sukses",
        ...payload,
        updated_rows: 1,
        total_bersih: processResult.kpis.total_bersih,
      });
      return;
    }
    if (path === "/attendance/reviews" && method === "GET") {
      await fulfillJson(route, []);
      return;
    }
    if (/^\/employees\/\d+$/.test(path) && method === "PUT") {
      const employeeId = Number(path.split("/").pop());
      const employee = testEmployees.find((item) => item.id === employeeId);
      const payload = request.postDataJSON() as Record<string, unknown>;
      employeeUpdatePayload = payload;
      if (!employee) {
        await fulfillJson(route, { detail: "Karyawan tidak ditemukan." }, 404);
        return;
      }
      Object.assign(employee, payload);
      if (employee.employment_status === "PKWT" && employee.contracts.length === 0) {
        employee.contracts.push({
          id: 101,
          contract_number: 1,
          start_date: String(payload.contract_start_date),
          end_date: String(payload.contract_end_date),
          status: "ACTIVE",
          keterangan: "Perubahan status PHL ke PKWT.",
        });
        employee.phl_to_pkwt_transitions = [{
          id: 51,
          employment_contract_id: 101,
          phl_start_date: String(payload.phl_period_start_date),
          phl_end_date: "2026-09-30",
          transition_date: String(payload.contract_start_date),
          created_at: "2026-10-12T08:00:00",
        }];
      }
      await fulfillJson(route, employee);
      return;
    }
    const contractPath = path.match(/^\/employees\/(\d+)\/contracts\/(\d+)$/);
    if (contractPath) {
      const employeeId = Number(contractPath[1]);
      const contractId = Number(contractPath[2]);
      const employee = testEmployees.find((item) => item.id === employeeId);
      const contract = employee?.contracts.find((item) => item.id === contractId);
      if (!employee || !contract) {
        await fulfillJson(route, { detail: "Histori kontrak tidak ditemukan." }, 404);
        return;
      }
      if (method === "PUT") {
        const payload = request.postDataJSON() as {
          start_date: string;
          end_date: string;
          status: string;
          keterangan: string | null;
        };
        Object.assign(contract, payload);
        const transition = employee.phl_to_pkwt_transitions.find(
          (item) => item.employment_contract_id === contractId,
        );
        if (transition) {
          transition.transition_date = contract.start_date;
          const phlEnd = new Date(`${contract.start_date}T00:00:00Z`);
          phlEnd.setUTCDate(phlEnd.getUTCDate() - 1);
          transition.phl_end_date = phlEnd.toISOString().slice(0, 10);
        }
        if (contract.status === "ACTIVE") employee.employment_status = "PKWT";
        await fulfillJson(route, contract);
        return;
      }
      if (method === "DELETE") {
        const hadTransition = employee.phl_to_pkwt_transitions.some(
          (item) => item.employment_contract_id === contractId,
        );
        employee.phl_to_pkwt_transitions = employee.phl_to_pkwt_transitions.filter(
          (item) => item.employment_contract_id !== contractId,
        );
        employee.contracts = employee.contracts.filter((item) => item.id !== contractId);
        if (contract.status === "ACTIVE" && hadTransition) employee.employment_status = "PHL";
        await fulfillJson(route, { status: "sukses" });
        return;
      }
    }
    const transitionPath = path.match(/^\/employees\/(\d+)\/phl-transitions\/(\d+)$/);
    if (transitionPath) {
      const employeeId = Number(transitionPath[1]);
      const transitionId = Number(transitionPath[2]);
      const employee = testEmployees.find((item) => item.id === employeeId);
      const transition = employee?.phl_to_pkwt_transitions.find((item) => item.id === transitionId);
      if (!employee || !transition) {
        await fulfillJson(route, { detail: "Rekapan periode PHL tidak ditemukan." }, 404);
        return;
      }
      if (method === "PUT") {
        const payload = request.postDataJSON() as { phl_start_date: string };
        const contract = employee.contracts.find((item) => item.id === transition.employment_contract_id);
        if (!contract) {
          await fulfillJson(route, { detail: "Kontrak terkait tidak ditemukan." }, 404);
          return;
        }
        transition.phl_start_date = payload.phl_start_date;
        transition.transition_date = contract.start_date;
        const phlEnd = new Date(`${contract.start_date}T00:00:00Z`);
        phlEnd.setUTCDate(phlEnd.getUTCDate() - 1);
        transition.phl_end_date = phlEnd.toISOString().slice(0, 10);
        await fulfillJson(route, transition);
        return;
      }
      if (method === "DELETE") {
        employee.phl_to_pkwt_transitions = employee.phl_to_pkwt_transitions.filter(
          (item) => item.id !== transitionId,
        );
        await fulfillJson(route, { status: "sukses" });
        return;
      }
    }
    if (path === "/holidays") {
      await fulfillJson(route, []);
      return;
    }
    if (path === "/leaves/annual-balance") {
      await fulfillJson(route, { data: [] });
      return;
    }
    if (path === "/leaves" && method === "GET") {
      await fulfillJson(route, [leave]);
      return;
    }
    if (path === `/leaves/${leave.id}/status` && method === "PATCH") {
      leaveStatusUpdate = request.postDataJSON();
      leave.status = "APPROVED";
      await fulfillJson(route, leave);
      return;
    }

    await fulfillJson(route, { detail: `Unmocked test API request: ${method} ${path}` }, 404);
  });

  return {
    leaveStatusUpdate: () => leaveStatusUpdate,
    employeeUpdatePayload: () => employeeUpdatePayload,
    employeeSnapshot: (id: number) => testEmployees.find((employee) => employee.id === id),
    payrollPdfUploaded: () => payrollPdfUploaded,
  };
}

async function installHrMasterSession(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("hr_token", "synthetic-browser-test-token");
    localStorage.setItem("hr_role", "hr_master");
    localStorage.setItem("hr_nama", "Pengguna QA");
  });
}

test("HR dapat login dan membuka dashboard", async ({ page }) => {
  await mockApi(page);
  await page.goto("/login");

  await expect(page.getByRole("heading", { name: "Kelola absensi dan data karyawan." })).toBeVisible();
  await expect(page.getByText("Laporan 14 sheet · Aturan kerja per divisi")).toBeVisible();
  await page.getByPlaceholder("nama@perusahaan.com").fill("qa@example.com");
  await page.locator('input[type="password"]').fill("synthetic-password");
  await page.getByRole("button", { name: "Masuk ke Dashboard" }).click();

  await expect(page).toHaveURL(/\/dashboard$/);
  await expect(page.getByRole("heading", { name: "Ringkasan Sistem" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Karyawan", exact: true }),
  ).toBeVisible();
});

test("HR melihat pesan saat login ditolak", async ({ page }) => {
  await mockApi(page, { loginFails: true });
  await page.goto("/login");

  await page.getByPlaceholder("nama@perusahaan.com").fill("qa@example.com");
  await page.locator('input[type="password"]').fill("wrong-synthetic-password");
  await page.getByRole("button", { name: "Masuk ke Dashboard" }).click();

  await expect(page.getByText("Email atau password salah.")).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("pencarian karyawan menemukan ID Karyawan dan NIK", async ({ page }) => {
  await mockApi(page);
  await installHrMasterSession(page);
  await page.goto("/karyawan");

  const search = page.getByRole("textbox", {
    name: "Cari nama, ID Karyawan, atau NIK",
  });
  await expect(
    page.getByRole("heading", { name: "Karyawan", exact: true }),
  ).toBeVisible();
  await search.fill("EMP-QA-002");
  await expect(page.getByText("Siti Contoh")).toBeVisible();
  await expect(page.getByText("Andi Contoh")).toHaveCount(0);

  await search.fill("3200000000000001");
  await expect(page.getByText("Andi Contoh")).toBeVisible();
  await expect(page.getByText("Siti Contoh")).toHaveCount(0);
});

test("form karyawan menawarkan cabang Profil dan cabang lama karyawan", async ({ page }) => {
  await mockApi(page);
  await installHrMasterSession(page);
  await page.goto("/karyawan");

  const row = page.getByRole("row").filter({ hasText: "Siti Contoh" });
  await row.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByRole("heading", { name: "Edit Karyawan" })).toBeVisible();

  const branchSelect = page.getByText("Cabang (opsional)").locator("..").locator("select");
  await expect(branchSelect.locator('option[value="Bandung"]')).toHaveCount(1);
  await expect(branchSelect.locator('option[value="Cabang Lama"]')).toHaveCount(1);
  const mealAllowanceInput = page.getByText("Uang Makan (Rp/hari)").locator("..").locator("input");
  await expect(mealAllowanceInput).toHaveValue("");
});

test("halaman Karyawan memisahkan tab master dan linking WhatsApp", async ({ page }) => {
  await mockApi(page);
  await installHrMasterSession(page);
  await page.goto("/karyawan");

  await expect(page.getByRole("tab", { name: "Informasi Karyawan" })).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("row").filter({ hasText: "Andi Contoh" })).toBeVisible();
  await page.getByRole("tab", { name: "Informasi Linking WhatsApp Karyawan" }).click();
  await expect(page.getByRole("heading", { name: "Linking WhatsApp Karyawan" })).toBeVisible();
  await expect(page.getByRole("row").filter({ hasText: "Andi Contoh" })).toBeHidden();

  await page.getByRole("tab", { name: "Informasi Karyawan" }).click();
  await expect(page.getByRole("row").filter({ hasText: "Andi Contoh" })).toBeVisible();
});

test("Kelola Kontrak membuka edit karyawan dan tab Kepegawaian dari widget dashboard", async ({ page }) => {
  await mockApi(page, { historyForPhl: true, expiringContract: true });
  await installHrMasterSession(page);
  await page.goto("/dashboard");

  await page.getByRole("link", { name: "Kelola Kontrak →" }).click();

  await expect(page).toHaveURL(/\/karyawan$/);
  await expect(page.getByRole("heading", { name: "Edit Karyawan" })).toBeVisible();
  await expect(page.getByText("Rekapan Histori Kontrak PKWT")).toBeVisible();
  await expect(page.getByText("Rekapan Perubahan PHL ke PKWT")).toBeVisible();
});

test("transisi PHL ke PKWT menyimpan dan menampilkan periode PHL", async ({ page }) => {
  const api = await mockApi(page);
  await installHrMasterSession(page);
  await page.goto("/karyawan");

  const row = page.getByRole("row").filter({ hasText: "Budi PHL" });
  await row.getByRole("button", { name: "Edit" }).click();
  await page.locator("#tab-kontrak").click();

  const statusSelect = page.getByText("Status Kepegawaian").locator("..").locator("select");
  await statusSelect.selectOption("PKWT");
  const phlStart = page.getByText("Tanggal Mulai Periode PHL").locator("..").locator('input[type="date"]');
  await expect(phlStart).toHaveValue("2025-04-01");
  await phlStart.fill("2025-03-15");
  const contractDates = page.locator(".grid.grid-cols-2 input[type='date']");
  await contractDates.nth(0).fill("2026-10-01");
  await contractDates.nth(1).fill("2027-09-30");
  await page.getByRole("button", { name: "Simpan", exact: true }).click();

  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(api.employeeUpdatePayload()).toMatchObject({
    employment_status: "PKWT",
    join_date: "2025-04-01",
    phl_period_start_date: "2025-03-15",
    contract_start_date: "2026-10-01",
  });

  const updatedRow = page.getByRole("row").filter({ hasText: "Budi PHL" });
  await updatedRow.getByRole("button", { name: "Edit" }).click();
  await page.locator("#tab-kontrak").click();
  await expect(page.getByText("Rekapan Perubahan PHL ke PKWT")).toBeVisible();
  await expect(page.getByText(/Periode PHL:.*15 Mar 2025 s\/d 30 Sep 2026/)).toBeVisible();
});

test("HR Master dapat mengedit dan menghapus histori kontrak serta periode PHL", async ({ page }) => {
  const api = await mockApi(page, { historyForPhl: true });
  await installHrMasterSession(page);
  await page.goto("/karyawan");

  const row = page.getByRole("row").filter({ hasText: "Budi PHL" });
  await row.getByRole("button", { name: "Edit" }).click();
  await page.locator("#tab-kontrak").click();

  const contract = page.getByTestId("contract-history-101");
  await contract.getByRole("button", { name: "Edit Kontrak" }).click();
  const contractDates = contract.locator('input[type="date"]');
  await contractDates.nth(0).fill("2026-11-01");
  await contractDates.nth(1).fill("2027-10-31");
  await contract.getByRole("button", { name: "Simpan", exact: true }).click();
  await expect(contract).toContainText("01 Nov 2026 s/d 31 Okt 2027");
  await expect(page.getByTestId("phl-history-51")).toContainText(
    "Periode PHL: 01 Apr 2025 s/d 31 Okt 2026",
  );

  const transition = page.getByTestId("phl-history-51");
  await transition.getByRole("button", { name: "Edit Periode PHL" }).click();
  await transition.locator('input[type="date"]').fill("2025-05-01");
  await transition.getByRole("button", { name: "Simpan Periode PHL" }).click();
  await expect(transition).toContainText("Periode PHL: 01 Mei 2025 s/d 31 Okt 2026");

  page.once("dialog", (dialog) => dialog.accept());
  await transition.getByRole("button", { name: "Hapus Rekap PHL" }).click();
  await expect(page.getByTestId("phl-history-51")).toHaveCount(0);
  await expect(page.getByTestId("contract-history-101")).toBeVisible();
  expect(api.employeeSnapshot(3)?.employment_status).toBe("PKWT");

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("contract-history-101").getByRole("button", { name: "Hapus Kontrak" }).click();
  await expect(page.getByTestId("contract-history-101")).toHaveCount(0);
  expect(api.employeeSnapshot(3)?.employment_status).toBe("PKWT");
});

test("menghapus kontrak aktif menghapus transisi terkait dan mengembalikan status PHL", async ({ page }) => {
  const api = await mockApi(page, { historyForPhl: true });
  await installHrMasterSession(page);
  await page.goto("/karyawan");

  const row = page.getByRole("row").filter({ hasText: "Budi PHL" });
  await row.getByRole("button", { name: "Edit" }).click();
  await page.locator("#tab-kontrak").click();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByTestId("contract-history-101").getByRole("button", { name: "Hapus Kontrak" }).click();

  await expect(page.getByTestId("contract-history-101")).toHaveCount(0);
  await expect(page.getByTestId("phl-history-51")).toHaveCount(0);
  await expect(page.getByText("Status Kepegawaian").locator("..").locator("select")).toHaveValue("PHL");
  expect(api.employeeSnapshot(3)?.employment_status).toBe("PHL");
});

test("HR Master dapat menyetujui permohonan cuti dari daftar", async ({ page }) => {
  const api = await mockApi(page);
  await installHrMasterSession(page);
  await page.goto("/cuti-izin");

  const leaveRow = page.getByRole("row").filter({ hasText: "Karyawan QA" });
  await expect(leaveRow.getByText("Pending")).toBeVisible();
  page.once("dialog", (dialog) => dialog.accept());
  await leaveRow.getByRole("button", { name: "Setujui" }).click();

  await expect(leaveRow.getByText("Disetujui")).toBeVisible();
  expect(api.leaveStatusUpdate()).toEqual({ status: "APPROVED" });
});

test("form HR membatasi pengajuan PHL pada Absensi Jarak Jauh", async ({ page }) => {
  await mockApi(page);
  await installHrMasterSession(page);
  await page.goto("/cuti-izin");

  await page.getByRole("button", { name: "Input Pengajuan Baru" }).click();
  const form = page.locator("form");
  await form.getByRole("combobox").nth(1).selectOption({ label: "Budi PHL (Bandung)" });

  const categorySelect = form.getByRole("combobox").nth(2);
  await expect(categorySelect.locator("option")).toHaveCount(1);
  await expect(categorySelect).toHaveValue("WORK_FROM_LOCATION");
  await expect(
    form.getByRole("alert").filter({ hasText: "Karyawan PHL tidak dapat mengajukan cuti atau izin" }),
  ).toBeVisible();
});

test("rekap saldo menampilkan tahun berjalan tanpa filter tahun", async ({ page }) => {
  await mockApi(page);
  await installHrMasterSession(page);
  await page.goto("/cuti-izin");

  await page.getByRole("button", { name: /Rekap Saldo Cuti Tahunan/ }).click();
  await expect(page.getByText(`Tahun ${new Date().getFullYear()}`, { exact: true }).first()).toBeVisible();
  await expect(page.locator('select option[value="2025"]')).toHaveCount(0);
  await expect(page.locator('select option[value="2026"]')).toHaveCount(0);
  await expect(page.locator('select option[value="2027"]')).toHaveCount(0);
});

test("bonus dan potongan lain memperbarui Total Bersih pada baris dan KPI", async ({ page }) => {
  await mockApi(page, { processResult: true });
  await installHrMasterSession(page);
  await page.goto("/proses");

  await page.locator('input[type="file"]').setInputFiles({
    name: "absensi-sintetis.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Nama,Timestamp\nKaryawan QA,2026-10-01 08:00:00"),
  });
  await page.getByRole("button", { name: "Proses Absensi Sekarang" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard Hasil Absensi" })).toBeVisible();

  const employeeRow = page.getByRole("row").filter({ hasText: "Karyawan QA" });
  const adjustmentInputs = employeeRow.locator('input[type="number"]');
  await expect(adjustmentInputs).toHaveCount(2);

  await adjustmentInputs.nth(0).fill("250");
  await adjustmentInputs.nth(0).press("Enter");
  await expect(page.getByText("Rp 1.200", { exact: true })).toHaveCount(2);

  await employeeRow.locator('input[type="number"]').nth(1).fill("125");
  await employeeRow.locator('input[type="number"]').nth(1).press("Enter");
  await expect(page.getByText("Rp 1.125", { exact: true })).toHaveCount(2);
  await expect(employeeRow.locator('input[type="number"]').nth(0)).toHaveValue("250");
  await expect(employeeRow.locator('input[type="number"]').nth(1)).toHaveValue("125");
});

test("payroll meninjau penerima WhatsApp dan melaporkan hasil parsial pengiriman", async ({ page }) => {
  const mock = await mockApi(page, { payroll: true });
  await installHrMasterSession(page);
  await page.goto("/proses-slip-gaji");

  await page.locator('input[type="file"]').setInputFiles({
    name: "payroll-sintetis.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("ID Karyawan,Nama,Gaji Pokok\nEMP-QA-101,Karyawan Tertaut,4000000"),
  });
  await page.getByRole("button", { name: "Proses Slip Gaji Sekarang" }).click();
  await expect(page.getByRole("heading", { name: "Pemrosesan Payroll & Slip Gaji Interaktif" })).toBeVisible();

  for (const [textTestId, ruleTestId] of [
    ["income-subtotal-text", "income-subtotal-rule"],
    ["deduction-subtotal-text", "deduction-subtotal-rule"],
  ]) {
    const text = await page.getByTestId(textTestId).boundingBox();
    const rule = await page.getByTestId(ruleTestId).boundingBox();
    expect(text).not.toBeNull();
    expect(rule).not.toBeNull();
    expect(rule!.y).toBeGreaterThan(text!.y + text!.height + 3);
  }

  for (const [boxTestId, textTestId] of [
    ["net-pay-box", "net-pay-value"],
    ["recipient-name-box", "recipient-name"],
  ]) {
    const box = await page.getByTestId(boxTestId).boundingBox();
    const text = await page.getByTestId(textTestId).boundingBox();
    expect(box).not.toBeNull();
    expect(text).not.toBeNull();
    expect(Math.abs((box!.y + box!.height / 2) - (text!.y + text!.height / 2))).toBeLessThan(2);
  }

  await page.getByRole("button", { name: "Kirim No WA Karyawan" }).click();
  await expect(page.getByText("628100000101")).toBeVisible();
  await expect(page.getByRole("cell", { name: "WhatsApp belum tertaut", exact: true })).toBeVisible();
  await expect(page.locator(".fixed.inset-0").getByText("EMP-QA-101", { exact: true })).toBeVisible();
  await expect(page.locator(".fixed.inset-0").getByText("EMP-QA-102", { exact: true })).toBeVisible();

  page.once("dialog", (dialog) => dialog.accept());
  await page.getByRole("button", { name: "Mulai Kirim Sekarang" }).click();
  await expect.poll(mock.payrollPdfUploaded).toBe(true);
  await expect(page.getByText("Hasil Pengiriman Blast:")).toBeVisible();
  await expect(page.getByText("Pengiriman selesai: 1 lengkap, 0 sebagian, 1 dilewati, 0 gagal.")).toBeVisible();
  await page.getByText("Riwayat percobaan pengiriman (1)").click();
  await expect(page.getByText(/Karyawan Tertaut · EMP-QA-101 · 628100000101/)).toBeVisible();
});
