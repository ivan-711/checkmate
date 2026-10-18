import Link from "next/link";
import { CaseScreen } from "@/components/case/CaseScreen";

export default async function QueueCasePage({ params }: { params: Promise<{ pairId: string }> }) {
  const { pairId } = await params;
  return (
    <div className="space-y-3">
      <Link
        href="/queue"
        className="inline-flex h-11 items-center self-start font-semibold text-accent hover:underline"
      >
        ← Back to work queue
      </Link>
      <CaseScreen pairId={pairId} />
    </div>
  );
}
