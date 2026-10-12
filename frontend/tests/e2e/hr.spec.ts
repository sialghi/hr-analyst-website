import { expect, test, type Page, type Route } from "@playwright/test";

interface BrowserEmployee {
  id: number;
  employee_code: string;
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
    employee_code: "EMP-QA-001",
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
    employee_code: "EMP-QA-002",
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
    employee_code: "EMP-QA-003",
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

async function mockApi(page: Page, options: { loginFails?: boolean } = {}) {
  const leave = pendingLeave();
  const testEmployees = employees.map((employee) => ({
    ...employee,
    contracts: employee.contracts.map((contract) => ({ ...contract })),
    phl_to_pkwt_transitions: employee.phl_to_pkwt_transitions.map((transition) => ({ ...transition })),
  }));
  let leaveStatusUpdate: { status: string } | null = null;
  let employeeUpdatePayload: Record<string, unknown> | null = null;

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
    if (path === "/rules") {
      await fulfillJson(route, {});
      return;
    }
    if (path === "/employees/contracts/expiring") {
      await fulfillJson(route, { data: [], total: 0, reminder_days_config: 10 });
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

test("pencarian karyawan menemukan Kode Karyawan dan NIK", async ({ page }) => {
  await mockApi(page);
  await installHrMasterSession(page);
  await page.goto("/karyawan");

  const search = page.getByRole("textbox", {
    name: "Cari nama, Kode Karyawan, atau NIK",
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
