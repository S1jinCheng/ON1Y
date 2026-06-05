"use client";

import { useEffect, useState } from "react";

import { fetchCurrentUser } from "@/lib/api";
import { clearAuth, getAuthToken } from "@/lib/auth";

type Props = {
  children: React.ReactNode;
};

function redirectToLogin(): void {
  if (typeof window === "undefined") {
    return;
  }
  if (!window.location.pathname.startsWith("/login")) {
    window.location.replace("/login");
  }
}

function AuthLoading(): JSX.Element {
  return (
    <div className="flex min-h-screen items-center justify-center bg-neutral-50 text-sm text-neutral-400">
      正在验证登录…
    </div>
  );
}

export default function AuthGate({ children }: Props): JSX.Element {
  // Always false on server + first client paint to avoid hydration mismatch.
  const [authed, setAuthed] = useState(false);

  useEffect(() => {
    const token = getAuthToken();
    if (!token) {
      redirectToLogin();
      return;
    }

    setAuthed(true);

    let cancelled = false;
    void fetchCurrentUser().catch((err: unknown) => {
      if (cancelled) {
        return;
      }
      console.warn("auth check failed", err);
      clearAuth();
      redirectToLogin();
    });

    return () => {
      cancelled = true;
    };
  }, []);

  if (!authed) {
    return <AuthLoading />;
  }

  return <>{children}</>;
}
