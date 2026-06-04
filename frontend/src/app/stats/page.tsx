"use client";

import AuthGate from "@/components/auth-gate";
import { StatsDashboard } from "@/components/stats-dashboard";
import { useKnowledgeFilterStore } from "@/store/knowledge-store";

export default function StatsPage(): JSX.Element {
  const locale = useKnowledgeFilterStore((s) => s.locale);

  return (
    <AuthGate>
      <StatsDashboard locale={locale} />
    </AuthGate>
  );
}
