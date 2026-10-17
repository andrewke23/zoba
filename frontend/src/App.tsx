import { Navigate, Route, Routes, useLocation } from 'react-router-dom'
import type { ReactNode } from 'react'
import { useAuth } from './auth/AuthContext'
import { Loading } from './components/ui'
import AppShell from './layouts/AppShell'
import TripLayout from './layouts/TripLayout'
import LoginPage from './pages/LoginPage'
import RegisterPage from './pages/RegisterPage'
import JoinPage from './pages/JoinPage'
import TripsPage from './pages/TripsPage'
import NewTripPage from './pages/NewTripPage'
import OverviewPage from './pages/trip/OverviewPage'
import PreferencesPage from './pages/trip/PreferencesPage'
import ComparePage from './pages/trip/ComparePage'
import ResultsPage from './pages/trip/ResultsPage'
import ItineraryPage from './pages/trip/ItineraryPage'
import TasksPage from './pages/trip/TasksPage'
import BudgetPage from './pages/trip/BudgetPage'
import PackingPage from './pages/trip/PackingPage'
import SettingsPage from './pages/trip/SettingsPage'
import SolversPage from './pages/trip/SolversPage'
import NotFoundPage from './pages/NotFoundPage'

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <Loading />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route element={<AppShell />}>
        <Route path="/join/:token" element={<JoinPage />} />
        <Route
          path="/"
          element={
            <RequireAuth>
              <TripsPage />
            </RequireAuth>
          }
        />
        <Route
          path="/trips/new"
          element={
            <RequireAuth>
              <NewTripPage />
            </RequireAuth>
          }
        />
        <Route
          path="/trips/:tripId"
          element={
            <RequireAuth>
              <TripLayout />
            </RequireAuth>
          }
        >
          <Route index element={<OverviewPage />} />
          <Route path="preferences" element={<PreferencesPage />} />
          <Route path="compare" element={<ComparePage />} />
          <Route path="results" element={<ResultsPage />} />
          <Route path="itinerary" element={<ItineraryPage />} />
          <Route path="tasks" element={<TasksPage />} />
          <Route path="budget" element={<BudgetPage />} />
          <Route path="packing" element={<PackingPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="solvers" element={<SolversPage />} />
        </Route>
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  )
}
