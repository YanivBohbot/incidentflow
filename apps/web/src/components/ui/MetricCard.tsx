/** One headline number with its label, used in the metrics row. */
type MetricCardProps = {
  label: string
  value: number
  description: string
}

export function MetricCard({ label, value, description }: MetricCardProps) {
  return <article className="metric-card"><p>{label}</p><strong>{value}</strong><span>{description}</span></article>
}
