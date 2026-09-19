import { AnalysisView } from "@/components/ipo/AnalysisView";

// /analysis/<document id>             the finished report
// /analysis/<document id>?job=<id>    progress of a running analysis, then its report
export default async function AnalysisPage(props: PageProps<"/analysis/[documentId]">) {
  // In this version of Next.js, params and searchParams are promises
  const { documentId } = await props.params;
  const { job } = await props.searchParams;
  return (
    <main className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-6 px-4 py-8 sm:px-6">
      <AnalysisView documentId={documentId} jobId={typeof job === "string" ? job : null} />
    </main>
  );
}
