"use client";

import { createContext, useCallback, useContext, useState, type ReactNode } from "react";

// Screen readers announce a change of text; clearing first lets an identical message repeat.
const REANNOUNCE_DELAY_MS = 100;

// One polite status region per page: every announcement goes through it, never role="alert".
const AnnounceContext = createContext<(message: string) => void>(() => {});

export function LiveRegionProvider({ children }: { children: ReactNode }) {
  const [message, setMessage] = useState("");
  const announce = useCallback((next: string) => {
    setMessage("");
    setTimeout(() => setMessage(next), REANNOUNCE_DELAY_MS);
  }, []);
  return (
    <AnnounceContext.Provider value={announce}>
      {children}
      <div role="status" aria-live="polite" className="sr-only">
        {message}
      </div>
    </AnnounceContext.Provider>
  );
}

export function useAnnounce() {
  return useContext(AnnounceContext);
}
