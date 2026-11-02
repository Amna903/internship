import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { Layout } from "@/components/ui/Layout";

export default function ProfessionalNotFound() {
  return (
    <Layout>
      <Card className="narrow" title={<>We couldn&apos;t find that professional</>}>
        <p className="muted">The link may be mistyped, or the profile is no longer listed.</p>
        <Link className="btn" href="/professionals">
          Browse all professionals
        </Link>
      </Card>
    </Layout>
  );
}
