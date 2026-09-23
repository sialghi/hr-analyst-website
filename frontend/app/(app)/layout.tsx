import AuthGuard from "@/components/AuthGuard";
import Sidebar from "@/components/Sidebar";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <div className="flex min-h-screen bg-slate-50">
        <Sidebar />
        <main className="flex-1 min-w-0 px-6 sm:px-8 py-8 overflow-x-hidden">
          <div className="max-w-[1600px] mx-auto">{children}</div>
        </main>
      </div>
    </AuthGuard>
  );
}
