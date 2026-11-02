import type { Metadata } from "next";
import Link from "next/link";
import { Suspense } from "react";
import { ProfessionalCard } from "@/components/professionals/ProfessionalCard";
import { ProfessionalFilters } from "@/components/professionals/ProfessionalFilters";
import { Card } from "@/components/ui/Card";
import { Layout } from "@/components/ui/Layout";
import { PageHeader } from "@/components/ui/PageHeader";
import { activeFilterCount, applyFilters, parseFilters } from "@/lib/filters";
import { professionals } from "@/lib/professionals";

export const metadata: Metadata = { title: "Find a professional · HealthProfile" };

type Props = { searchParams: Promise<Record<string, string | string[] | undefined>> };

/**
 * Server component: filters and sorts on the server from the query string, so a shared or
 * refreshed URL renders the same results with no client-side flash.
 */
export default async function ProfessionalsPage({ searchParams }: Props) {
  const filters = parseFilters(await searchParams);
  const results = applyFilters(professionals, filters);

  return (
    <Layout>
      <PageHeader
        eyebrow="Directory"
        title="Find a wellness professional"
        lead="Browse fictional professionals by specialty, location, availability and fee."
      />

      <Suspense>
        <ProfessionalFilters />
      </Suspense>

      <p className="result-count" role="status">
        Showing <strong>{results.length}</strong> of {professionals.length} professionals
      </p>

      {results.length > 0 ? (
        <ul className="pro-grid" aria-label="Results">
          {results.map((p) => <li key={p.id}><ProfessionalCard professional={p} /></li>)}
        </ul>
      ) : (
        <Card className="empty" title="No professionals match these filters">
          <p className="muted">
            {activeFilterCount(filters) > 1 ? "Try removing one of the filters" : "Try a different search"}, or start again.
          </p>
          <Link className="btn ghost" href="/professionals">Clear all filters</Link>
        </Card>
      )}
    </Layout>
  );
}
