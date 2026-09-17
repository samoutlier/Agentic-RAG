"use client"; // Error boundaries must be Client Components

import { useEffect } from "react";
import { Button } from "@/components/ui/button";

// Next.js shows this instead of the page if rendering throws an unexpected
// error. API failures are already handled inside the components; this is the
// last line of defence, so one bug can't leave the user with a blank screen.
export default function ErrorPage({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <main className="mx-auto flex w-full max-w-md flex-1 flex-col items-center justify-center gap-4 px-4 py-16 text-center">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="text-muted-foreground">
        The page hit an unexpected error. Your uploaded documents are still saved on the
        server.
      </p>
      <Button onClick={() => retry()}>Try again</Button>
    </main>
  );
}
