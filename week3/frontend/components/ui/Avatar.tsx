/** Initials in a colour derived from the name, so the same person always gets the same colour. */
export function Avatar({ name, size }: { name: string; size?: "lg" }) {
  const initials = name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase() ?? "").join("") || "?";
  let hue = 0;
  for (const ch of name) hue = (hue * 31 + ch.charCodeAt(0)) % 360;
  return (
    <span className={`avatar ${size ?? ""}`} style={{ ["--h" as string]: hue }} aria-hidden="true">{initials}</span>
  );
}
