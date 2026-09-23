const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export type Role = "hr_master" | "hr_staff";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("hr_token");
}

export function setSession(token: string, role: Role, nama: string) {
  localStorage.setItem("hr_token", token);
  localStorage.setItem("hr_role", role);
  localStorage.setItem("hr_nama", nama);
}

export function clearSession() {
  localStorage.removeItem("hr_token");
  localStorage.removeItem("hr_role");
  localStorage.removeItem("hr_nama");
}

export function getRole(): Role | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("hr_role") as Role | null;
}

export function getNama(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem("hr_nama");
}

export function isHrMaster(): boolean {
  return getRole() === "hr_master";
}

class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request(path: string, options: RequestInit = {}) {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (!(options.body instanceof FormData) && options.body) {
    headers["Content-Type"] = "application/json";
  }

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      // ignore
    }
    if (res.status === 401 && path !== "/auth/login" && typeof window !== "undefined") {
      clearSession();
      if (window.location.pathname !== "/login") {
        window.location.href = "/login";
      }
    }
    throw new ApiError(detail, res.status);
  }
  return res;
}

export const api = {
  async login(email: string, password: string) {
    const res = await request("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    });
    return res.json();
  },

  async me() {
    const res = await request("/auth/me");
    return res.json();
  },

  async getProfiles() {
    const res = await request("/profiles");
    return res.json();
  },

  async getProfile(code: string) {
    const res = await request(`/profiles/${code}`);
    return res.json();
  },

  async createProfile(payload: any) {
    const res = await request("/profiles", { method: "POST", body: JSON.stringify(payload) });
    return res.json();
  },

  async updateProfile(code: string, payload: any) {
    const res = await request(`/profiles/${code}`, { method: "PUT", body: JSON.stringify(payload) });
    return res.json();
  },

  async deleteProfile(code: string) {
    await request(`/profiles/${code}`, { method: "DELETE" });
  },

  async getRules() {
    const res = await request("/rules");
    return res.json();
  },

  async updateRules(payload: any) {
    const res = await request("/rules", { method: "PUT", body: JSON.stringify(payload) });
    return res.json();
  },

  async getEmployees(profileCode?: string) {
    const qs = profileCode ? `?profile_code=${encodeURIComponent(profileCode)}` : "";
    const res = await request(`/employees${qs}`);
    return res.json();
  },

  async createEmployee(payload: any) {
    const res = await request("/employees", { method: "POST", body: JSON.stringify(payload) });
    return res.json();
  },

  async updateEmployee(id: number, payload: any) {
    const res = await request(`/employees/${id}`, { method: "PUT", body: JSON.stringify(payload) });
    return res.json();
  },

  async deleteEmployee(id: number) {
    await request(`/employees/${id}`, { method: "DELETE" });
  },

  async importEmployees(file: File) {
    const form = new FormData();
    form.append("file", file);
    const res = await request("/employees/import", { method: "POST", body: form });
    return res.json();
  },

  async downloadEmployeesTemplate(): Promise<Blob> {
    const res = await request("/employees/template");
    return res.blob();
  },

  async getHolidays() {
    const res = await request("/holidays");
    return res.json();
  },

  async addHoliday(payload: any) {
    const res = await request("/holidays", { method: "POST", body: JSON.stringify(payload) });
    return res.json();
  },

  async deleteHoliday(id: number) {
    await request(`/holidays/${id}`, { method: "DELETE" });
  },

  async importHolidays(file: File) {
    const form = new FormData();
    form.append("file", file);
    const res = await request("/holidays/import", { method: "POST", body: form });
    return res.json();
  },

  async downloadHolidaysTemplate(): Promise<Blob> {
    const res = await request("/holidays/template");
    return res.blob();
  },

  async getUsers() {
    const res = await request("/auth/users");
    return res.json();
  },

  async createUser(payload: any) {
    const res = await request("/auth/users", { method: "POST", body: JSON.stringify(payload) });
    return res.json();
  },

  async deleteUser(id: number) {
    await request(`/auth/users/${id}`, { method: "DELETE" });
  },

  async prosesAbsensi(files: File[]): Promise<any> {
    const form = new FormData();
    for (const f of files) form.append("files", f);
    const res = await request("/proses-absensi-manual", { method: "POST", body: form });
    return res.json();
  },

  async downloadProcessedExcel(fileId: string, filename: string) {
    const res = await request(`/proses/download/${fileId}`);
    const blob = await res.blob();
    triggerBlobDownload(blob, filename);
  },

  async downloadAttendanceTemplate(format: "xlsx" | "csv" = "xlsx"): Promise<Blob> {
    const res = await request(`/proses/template?format=${format}`);
    return res.blob();
  },
};

export function triggerBlobDownload(blob: Blob, filename: string) {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  window.URL.revokeObjectURL(url);
  document.body.removeChild(a);
}

export { ApiError };
