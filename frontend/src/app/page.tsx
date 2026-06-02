import AuthGate from "@/components/auth-gate";
import KnowledgeWorkbench from "@/components/knowledge-workbench";

export default function Home(): JSX.Element {
  return (
    <AuthGate>
      <KnowledgeWorkbench />
    </AuthGate>
  );
}
