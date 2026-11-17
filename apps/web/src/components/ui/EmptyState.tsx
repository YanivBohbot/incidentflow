/** Placeholder shown when a list or panel has nothing to display. */
import type { ReactNode } from 'react'

type EmptyStateProps = {
  title: string
  description: string
  action?: ReactNode
}

export function EmptyState({ title, description, action }: EmptyStateProps) {
  return <div className="empty-state"><h2>{title}</h2><p>{description}</p>{action}</div>
}
