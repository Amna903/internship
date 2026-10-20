import type { Metadata } from "next";
import { SavedList } from "@/components/professionals/SavedList";
import { Layout } from "@/components/ui/Layout";

export const metadata: Metadata = { title: "Saved professionals · HealthProfile" };

export default function SavedPage() {
  return (
    <Layout>
      <h1>Saved professionals</h1>
      <p className="muted">Saved on this device only (browser storage), not to your account.</p>
      <SavedList />
    </Layout>
  );
}
