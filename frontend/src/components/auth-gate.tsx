"use client";

import { useEffect, useState } from "react";

import { fetchAuthStatus, fetchCurrentUser } from "@/lib/api";
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
      正在加载…
    </div>
  );
}

function BackendUnavailable(): JSX.Element {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-2 bg-neutral-50 px-6 text-center text-sm text-neutral-500">
      <p>无法连接 On1y 后端（127.0.0.1:8765）。</p>
      <p>请双击桌面 On1y 图标，或运行 scripts\start-on1y.cmd。</p>
    </div>
  );
}

export default function AuthGate({ children }: Props): JSX.Element {
  const [ready, setReady] = useState(false);
  const [backendDown, setBackendDown] = useState(false);

  useEffect(() => {
    let cancelled = false;

    void fetchAuthStatus()
      .then((status) => {
        if (cancelled) {
          return;
        }
        if (!status.auth_required) {
          setReady(true);
          return;
        }

        const token = getAuthToken();
        if (!token) {
          redirectToLogin();
          return;
        }

        setReady(true);
        void fetchCurrentUser().catch((err: unknown) => {
          if (cancelled) {
            return;
          }
          console.warn("auth check failed", err);
          clearAuth();
          redirectToLogin();
        });
      })
      .catch((err: unknown) => {
        if (cancelled) {
          return;
        }
        console.warn("auth status failed", err);
        setBackendDown(true);
      });

    return () => {
      cancelled = true;
    };
  }, []);

  if (backendDown) {
    return <BackendUnavailable />;
  }

  if (!ready) {
    return <AuthLoading />;
  }

  return <>{children}</>;
}
