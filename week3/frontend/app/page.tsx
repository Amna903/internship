import Link from "next/link";
import { Shell } from "@/components/Shell";
import { Icon, type IconName } from "@/components/ui/Icon";

const FEATURES: { icon: IconName; title: string; body: string; href: string; cta: string }[] = [
  { icon: "user", title: "Your wellness profile", body: "Goals, contact preferences and an emergency contact, with a completion score that shows what's left.", href: "/signup", cta: "Create a profile" },
  { icon: "search", title: "Find a professional", body: "Filter fictional nutritionists, physiotherapists and coaches by specialty, city, day and fee.", href: "/professionals", cta: "Browse the directory" },
  { icon: "chart", title: "No-show estimate", body: "An educational model trained on synthetic data helps staff decide who gets an extra reminder.", href: "/admin/predictions", cta: "Open (admins)" },
  { icon: "list", title: "Audit trail", body: "Every profile edit and admin action is recorded with field names only, never the values.", href: "/admin", cta: "Admin console" },
];

export default function Home() {
  return (
    <Shell>
      <section className="hero">
        <div>
          <span className="pill"><b>DEMO</b> Synthetic data only · not medical advice</span>
          <h1>Your wellness profile, <em>beautifully</em> simple.</h1>
          <p className="lead">
            Keep your goals, preferences and emergency contact in one place. Clinic staff get a calm console to
            review profiles, with every action on the record.
          </p>
          <div className="cta-row">
            <Link className="btn lg" href="/signup">Create your profile <Icon name="arrow" /></Link>
            <Link className="btn ghost lg" href="/professionals">Find a professional</Link>
          </div>
          <div className="trust">
            <span><Icon name="lock" /> HttpOnly, short-lived tokens</span>
            <span><Icon name="shield" /> Separate admin sessions</span>
            <span><Icon name="check" /> 220+ automated tests</span>
          </div>
        </div>

        <div className="preview" aria-hidden="true">
          <div className="card">
            <div className="person" style={{ marginBottom: 14 }}>
              <span className="avatar lg" style={{ ["--h" as string]: 168 }}>AR</span>
              <div><strong>Amina Rahman</strong><span className="muted">Member · 25–34</span></div>
            </div>
            <div className="completion">
              <div className="ring" style={{ ["--p" as string]: 67 }}><span>67%</span></div>
              <div>
                <strong>Profile completion</strong>
                <div className="muted small">Emergency contact still missing</div>
              </div>
            </div>
            <div style={{ marginTop: 14 }}>
              <div className="mini-row"><span className="muted">Wellness goals</span><span>Walk 8k steps · Sleep 7h</span></div>
              <div className="mini-row"><span className="muted">Contact</span><span>Email</span></div>
              <div className="mini-row"><span className="muted">Status</span><span className="badge">active</span></div>
            </div>
          </div>
          <div className="float">
            <div className="muted small">Next appointment</div>
            <div style={{ fontWeight: 750, fontSize: "1.4rem", letterSpacing: "-.02em" }}>8.3%</div>
            <div className="small">no-show estimate · <span className="badge">low risk</span></div>
          </div>
        </div>
      </section>

      <h2 className="section-title">What&apos;s inside</h2>
      <div className="features">
        {FEATURES.map((f) => (
          <div className="card feature" key={f.title}>
            <span className="icon-chip"><Icon name={f.icon} /></span>
            <h3>{f.title}</h3>
            <p className="muted small">{f.body}</p>
            <Link className="more small" href={f.href}>{f.cta} <Icon name="arrow" /></Link>
          </div>
        ))}
      </div>

      <h2 className="section-title">Two ways in</h2>
      <div className="choices">
        <div className="card">
          <span className="icon-chip"><Icon name="user" /></span>
          <h2 style={{ marginTop: 12 }}>Member</h2>
          <ul className="checklist">
            <li><Icon name="check" /> Sign up yourself and manage only your own profile</li>
            <li><Icon name="check" /> 10-minute access token, refreshed silently</li>
          </ul>
          <div className="row">
            <Link className="btn" href="/signup">Create account</Link>
            <Link className="btn ghost" href="/login">Sign in</Link>
          </div>
        </div>
        <div className="card">
          <span className="icon-chip"><Icon name="shield" /></span>
          <h2 style={{ marginTop: 12 }}>Administrator</h2>
          <ul className="checklist">
            <li><Icon name="check" /> Accounts are provisioned by the team, never self-registered</li>
            <li><Icon name="check" /> Server-side session that can be revoked instantly</li>
          </ul>
          <Link className="btn ghost" href="/admin/login">Admin sign in</Link>
        </div>
      </div>
    </Shell>
  );
}
