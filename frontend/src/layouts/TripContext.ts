import { createContext, useContext } from 'react'
import type { City, Member, Role, Trip, UUID } from '../api'

export interface TripCtx {
  trip: Trip
  city: City | undefined
  members: Member[]
  myRole: Role
  isOrganizer: boolean
  memberName: (id: UUID) => string
  reload: () => Promise<void>
}

export const TripContext = createContext<TripCtx | null>(null)

export function useTrip(): TripCtx {
  const ctx = useContext(TripContext)
  if (!ctx) throw new Error('useTrip must be used inside a trip route')
  return ctx
}
