"use client";

import { Command } from "cmdk";
import { usePathname, useRouter } from "next/navigation";
import { useResetDemo } from "@/components/ui/ResetButton";
import { useDesk, type DeskAction } from "./DeskContext";

interface Item {
  id: string;
  label: string;
  hint?: string;
  run: () => void;
}

const ACTION_ITEMS: { action: DeskAction; label: string; hint?: string }[] = [
  { action: "resolve", label: "Resolve identity", hint: "R" },
  { action: "approve", label: "Approve link", hint: "A" },
  { action: "reject", label: "Reject", hint: "X" },
  { action: "kiosk-es", label: "Kiosk in Español" },
  { action: "kiosk-en", label: "Kiosk in English" },
];

/** The ⌘K command bar (CONCEPT.md §5, touch 11): the same actions as the keycaps, plus the kiosk
 * language and the work queue, which has no tab. Styled from the tokens in globals.css. */
export function CommandBar() {
  const { actions, commandsOpen, setCommandsOpen } = useDesk();
  const { reset } = useResetDemo();
  const router = useRouter();
  const pathname = usePathname();

  const items: Item[] = [
    ...ACTION_ITEMS.flatMap(({ action, label, hint }) => {
      const run = actions[action];
      return run ? [{ id: action, label, hint, run }] : [];
    }),
    pathname.startsWith("/queue")
      ? { id: "desk", label: "Open the Desk", run: () => router.push("/") }
      : { id: "queue", label: "Open work queue", run: () => router.push("/queue") },
    { id: "reset", label: "Reset demo", hint: "⇧R", run: reset },
  ];

  function pick(item: Item) {
    setCommandsOpen(false);
    item.run();
  }

  return (
    <Command.Dialog
      open={commandsOpen}
      onOpenChange={setCommandsOpen}
      label="Command bar"
      overlayClassName="cmd-overlay"
      contentClassName="cmd-box"
      loop
    >
      <Command.Input placeholder="Type a command" />
      <Command.List>
        <Command.Empty>No matching command.</Command.Empty>
        {items.map((item) => (
          <Command.Item key={item.id} value={item.label} onSelect={() => pick(item)}>
            {item.label}
            {item.hint && <kbd aria-hidden="true">{item.hint}</kbd>}
          </Command.Item>
        ))}
      </Command.List>
    </Command.Dialog>
  );
}
