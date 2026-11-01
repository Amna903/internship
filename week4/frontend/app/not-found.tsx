import Link from "next/link";
import { Card } from "@/components/ui/Card";
import { Layout } from "@/components/ui/Layout";

export default function NotFound() {
  return (
    <Layout>
      <Card className="narrow" title="Page not found">
        <p className="muted">There&apos;s nothing at this address.</p>
        <Link className="btn" href="/">Go home</Link>
      </Card>
    </Layout>
  );
}
