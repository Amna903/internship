"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { AdminTabs, useAdminNav } from "@/components/AdminTabs";
import { Shell } from "@/components/Shell";
import { PageHeader } from "@/components/ui/PageHeader";
import { ClusterView, clustersApi } from "@/lib/api";
import { errorView } from "@/lib/prediction";

// Okabe-Ito colours: distinguishable with the common colour-vision deficiencies, readable in both themes.
const COLOURS = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9"];
const W = 480, H = 320, PAD = 36;
const pct = (v: number) => `${Math.round(v * 100)}%`;

function PcaPlot({ control }: { control: ClusterView["control"] }) {
  const xs = control.points.map((p) => p.x), ys = control.points.map((p) => p.y);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const sx = (x: number) => PAD + ((x - x0) / (x1 - x0 || 1)) * (W - 2 * PAD);
  const sy = (y: number) => H - PAD - ((y - y0) / (y1 - y0 || 1)) * (H - 2 * PAD);
  const [v1, v2] = control.pca_variance;
  const summary = `${control.points.length} points in ${control.clusters.length} clusters. The two components keep `
    + `${pct(v1 + v2)} of the variance (${pct(v1)} and ${pct(v2)}). Positive-control data with planted habits.`;
  return (
    <figure className="pca-figure" aria-labelledby="pca-caption">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`PCA scatter plot. ${summary}`} data-testid="pca-plot">
        <line className="axis" x1={PAD} y1={H - PAD} x2={W - PAD} y2={H - PAD} />
        <line className="axis" x1={PAD} y1={PAD} x2={PAD} y2={H - PAD} />
        {control.points.map((p, i) => (
          <circle key={i} cx={sx(p.x)} cy={sy(p.y)} r={2.6} fill={COLOURS[p.cluster % COLOURS.length]} fillOpacity={0.7} />
        ))}
        <text x={W / 2} y={H - 8} textAnchor="middle">Component 1 ({pct(v1)} of variance)</text>
        <text x={12} y={H / 2} textAnchor="middle" transform={`rotate(-90 12 ${H / 2})`}>Component 2 ({pct(v2)})</text>
      </svg>
      <ul className="legend" aria-label="Clusters">
        {control.clusters.map((c) => (
          <li key={c.cluster}><span className="swatch" style={{ background: COLOURS[c.cluster % COLOURS.length] }} aria-hidden="true" />
            Cluster {c.cluster + 1} ({c.size})</li>
        ))}
      </ul>
      <figcaption id="pca-caption" className="muted small" data-testid="pca-summary">{summary}</figcaption>
    </figure>
  );
}

export default function ClustersPage() {
  const router = useRouter();
  const nav = useAdminNav();
  const [view, setView] = useState<ClusterView | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  useEffect(() => {
    clustersApi.view().then(setView).catch((err) => {
      const e = errorView(err);
      if (e.kind === "signed_out") router.replace("/admin/login");
      else setFailure(e.kind === "unavailable" ? "Cluster results are unavailable right now. Try again later." : e.message);
    });
  }, [router]);

  return (
    <Shell nav={nav}>
      <PageHeader eyebrow="Admin console · educational prototype" title="Booking-pattern clusters"
                  lead="Exploratory clustering of synthetic, fictional data. Clusters describe booking patterns, not categories of people." />
      <AdminTabs />
      {failure && <div className="alert warn" role="alert">{failure}</div>}
      {!view && !failure && <p className="muted">Loading…</p>}
      {view && (
        <>
          <div className="two-col">
            <section className="card" aria-labelledby="pca-title">
              <h2 id="pca-title">PCA picture</h2>
              <p><span className="label-pill" data-testid="control-label">{view.control.label}</span></p>
              <PcaPlot control={view.control} />
              <p className="small">
                The clustering {view.control.recovery} the planted habits (agreement score ARI {view.control.ari.toFixed(2)}, where 1 is perfect).
              </p>
            </section>
            <section className="card" aria-labelledby="real-title">
              <h2 id="real-title">Real synthetic patients</h2>
              <p className="suggestion" data-testid="real-verdict">No reliable structure found.</p>
              <p className="small">
                On {view.real.patients.toLocaleString()} patients the best separation score ({view.real.silhouette.toFixed(3)}) did not beat
                the score reached on shuffled data ({view.real.baseline_bar.toFixed(3)}), and {pct(view.real.appointments_share_of_split)} of the
                split comes from how many appointments a patient has.
              </p>
              <h3 className="form-section">Misleading example: the clusters K-Means formed anyway</h3>
              <ul className="small">
                {view.real.misleading_clusters.map((c) => (
                  <li key={c.cluster}>{pct(c.share)}: {c.description}</li>
                ))}
              </ul>
              <p className="muted small">K-Means always returns clusters, even when there is no structure. These are shown as a warning, not a finding.</p>
            </section>
          </div>

          <section className="card" aria-labelledby="methods-title" style={{ marginTop: "var(--space-5)" }}>
            <h2 id="methods-title">Method comparison</h2>
            <div className="table-wrap">
              <table className="data-table" data-testid="methods-table">
                <thead>
                  <tr><th scope="col">Method</th><th scope="col">Real data: structure?</th><th scope="col">Real data: score vs shuffled bar</th>
                    <th scope="col">Real data: chosen k</th><th scope="col">Control: chosen k</th><th scope="col">Control: ARI</th></tr>
                </thead>
                <tbody>
                  {view.methods.map((m) => (
                    <tr key={m.method}>
                      <th scope="row">{m.method === "k-means" ? "K-Means" : "Ward (agglomerative)"}</th>
                      <td>{m.real_structure_found ? "Yes" : "No"}</td>
                      <td>{m.real_silhouette.toFixed(3)} vs {m.real_baseline_bar.toFixed(3)}</td>
                      <td>{m.real_chosen_k}</td>
                      <td>{m.control_chosen_k}</td>
                      <td>{m.control_ari.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted small">Score: silhouette (higher means better separated). ARI: agreement with the planted habits on the control data.</p>
          </section>

          <p className="disclaimer small" data-testid="disclaimer">{view.disclaimer}</p>
          <p className="muted small mono">Results version {view.results_version}</p>
        </>
      )}
    </Shell>
  );
}
