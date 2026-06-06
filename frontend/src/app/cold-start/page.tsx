"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect } from "react";

import AuthGate from "@/components/auth-gate";

function ColdStartRedirect(): null {
  const router = useRouter();
  const searchParams = useSearchParams();

  useEffect(() => {
    if (searchParams.get("start") === "1") {
      try {
        sessionStorage.setItem("on1y-auto-cold-start", "1");
        sessionStorage.removeItem("on1y-cold-start-panel-dismissed");
      } catch {
        /* ignore */
      }
    }
    router.replace("/");
  }, [router, searchParams]);

  return null;
}

export default function ColdStartPage(): JSX.Element {
  return (
    <AuthGate>
      <Suspense fallback={null}>
        <ColdStartRedirect />
      </Suspense>
    </AuthGate>
  );
}
