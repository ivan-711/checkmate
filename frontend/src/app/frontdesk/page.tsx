import { redirect } from "next/navigation";

// The kiosk lives on the Desk at "/" (CONCEPT.md §3). Links and tests that open /frontdesk still
// land on it.
export default function FrontDeskPage() {
  redirect("/");
}
