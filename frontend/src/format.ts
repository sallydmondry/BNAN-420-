export const usd = (x: number | null | undefined, opts: { sign?: boolean } = {}) => {
  if (x === null || x === undefined || isNaN(x)) return "—";
  const s = Math.abs(x).toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
  if (x < 0) return `−${s}`;
  return opts.sign ? `+${s}` : s;
};
export const pct = (x: number | null | undefined, digits = 0) => (x === null || x === undefined ? "—" : `${x.toFixed(digits)}%`);
export const ordinal = (n: number) => {
  const r = Math.round(n), s = ["th", "st", "nd", "rd"], v = r % 100;
  return r + (s[(v - 20) % 10] || s[v] || s[0]);
};
export const NOT_STATED = "not stated in offer";
