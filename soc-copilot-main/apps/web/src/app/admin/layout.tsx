"use client";

import { useRequireAuth } from "@/lib/auth";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

export default function AdminLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const auth = useRequireAuth();
  const router = useRouter();

  useEffect(() => {
    if (!auth.loading && auth.user && auth.user.role !== "admin") {
      router.replace("/");
    }
  }, [auth.loading, auth.user, router]);

  if (auth.loading || !auth.user || auth.user.role !== "admin") {
    return <div className="p-8 text-slate-400 text-sm">Verificando permisos...</div>;
  }

  return <>{children}</>;
}
