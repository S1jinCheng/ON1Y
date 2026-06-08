"use client";

import { useEffect } from "react";

import AuthGate from "@/components/auth-gate";
import { StatsDashboard } from "@/components/stats-dashboard";
import { getUserProfile } from "@/lib/api";
import { useKnowledgeFilterStore } from "@/store/knowledge-store";

export default function StatsPage(): JSX.Element {
  const locale = useKnowledgeFilterStore((s) => s.locale);
  const setLocale = useKnowledgeFilterStore((s) => s.setLocale);

  useEffect(() => {
    void getUserProfile()
      .then((profile) => {
        const next = profile.app?.locale === "en" ? "en" : "zh";
        setLocale(next);
      })
      .catch(() => undefined);
  }, [setLocale]);

  return (
    <AuthGate>
      <StatsDashboard locale={locale} />
    </AuthGate>
  );
}
