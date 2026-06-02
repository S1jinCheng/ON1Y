"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

import { fetchCurrentUser } from "@/lib/api";
import { getAuthToken } from "@/lib/auth";

type Props = {
  children: React.ReactNode;
};

export default function AuthGate({ children }: Props): JSX.Element {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const token = getAuthToken();
    if (!token) {
      router.replace("/login");
      return;
    }
    fetchCurrentUser()
      .then(() => setReady(true))
      .catch((err: unknown) => {
        console.warn("auth check failed", err);
        router.replace("/login");
      });
  }, [router]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-neutral-50 text-sm text-neutral-400">
        正在验证登录…
      </div>
    );
  }

  return <>{children}</>;
}
