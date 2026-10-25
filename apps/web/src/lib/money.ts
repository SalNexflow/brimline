/** Format an amount in minor units (cents) for display. Arithmetic never happens here: the
 * engine computes every price; the web only shows it. */
export function formatMoney(cents: number, currency: string): string {
  return new Intl.NumberFormat("en-IE", { style: "currency", currency }).format(cents / 100);
}
