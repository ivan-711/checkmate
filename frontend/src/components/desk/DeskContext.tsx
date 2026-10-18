"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import type { DecisionStatus, ReasonCode } from "@/api/types";
import { useIntakeSession } from "@/components/frontdesk/intake";
import {
  deriveDeskState,
  kioskStateFrom,
  type CiteContext,
  type CiteField,
  type DeskState,
  type KioskState,
  type Sheet,
} from "@/lib/desk";

/** What the Desk knows about the hero pair; the Desk's data hook sets it, the header reads it. */
export interface CaseFacts {
  decision: DecisionStatus | null;
  linked: boolean;
  flagRaised: boolean;
  /** The patient's given name from the records, for the stage title; null until known. */
  name: string | null;
  /** "Registrar A" once linked. */
  registrar: string | null;
  reason: ReasonCode | null;
  /** The link's decidedAt, for "Linked by … · 4 s ago". */
  linkedAt: string | null;
}

export const NO_FACTS: CaseFacts = {
  decision: null,
  linked: false,
  flagRaised: false,
  name: null,
  registrar: null,
  reason: null,
  linkedAt: null,
};

/** The actions the keyboard map and the command bar can dispatch. A lane registers the ones it
 * owns with useDeskAction; an unregistered action is not offered. */
export type DeskAction = "resolve" | "approve" | "reject" | "confirm" | "cancel" | "kiosk-en" | "kiosk-es";

export interface DeskContextValue extends CiteContext {
  desk: DeskState;
  kiosk: KioskState;
  /** The kiosk's own report; null hands back to the default derived from the check-in on record. */
  setKiosk(state: KioskState | null): void;
  sheet: Sheet;
  setSheet(sheet: Sheet): void;
  facts: CaseFacts;
  setFacts(facts: CaseFacts): void;
  actions: Partial<Record<DeskAction, () => void>>;
  registerAction(name: DeskAction, run: () => void): () => void;
  commandsOpen: boolean;
  setCommandsOpen(open: boolean): void;
}

const DeskContext = createContext<DeskContextValue | null>(null);

export function DeskProvider({ children }: { children: ReactNode }) {
  const [kioskOverride, setKiosk] = useState<KioskState | null>(null);
  const [sheet, setSheet] = useState<Sheet>(null);
  const [cite, setCite] = useState<CiteField | null>(null);
  const [facts, setFacts] = useState<CaseFacts>(NO_FACTS);
  const [actions, setActions] = useState<Partial<Record<DeskAction, () => void>>>({});
  const [commandsOpen, setCommandsOpen] = useState(false);
  const registration = useIntakeSession()?.registration.state;
  const kiosk = kioskOverride ?? kioskStateFrom(registration, false);
  const desk = deriveDeskState({ decision: facts.decision, linked: facts.linked, sheet, kiosk });

  const registerAction = useCallback((name: DeskAction, run: () => void) => {
    setActions((current) => ({ ...current, [name]: run }));
    return () =>
      setActions((current) => (current[name] === run ? { ...current, [name]: undefined } : current));
  }, []);

  const value = useMemo<DeskContextValue>(
    () => ({
      desk,
      kiosk,
      setKiosk,
      sheet,
      setSheet,
      cite,
      setCite,
      facts,
      setFacts,
      actions,
      registerAction,
      commandsOpen,
      setCommandsOpen,
    }),
    [desk, kiosk, sheet, cite, facts, actions, registerAction, commandsOpen],
  );
  return <DeskContext.Provider value={value}>{children}</DeskContext.Provider>;
}

export function useDesk(): DeskContextValue {
  const value = useContext(DeskContext);
  if (!value) throw new Error("useDesk needs a DeskProvider");
  return value;
}

/** Registers a Desk action for the keyboard map and the command bar while the component is
 * mounted; the newest `run` is always the one called. */
export function useDeskAction(name: DeskAction, run: (() => void) | null) {
  const { registerAction } = useDesk();
  const latest = useRef(run);
  latest.current = run;
  useEffect(() => {
    if (!run) return;
    return registerAction(name, () => latest.current?.());
    // Only presence matters for registration; the ref carries the latest callback.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [name, registerAction, run !== null]);
}
