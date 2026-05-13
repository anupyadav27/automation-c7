import { Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Dashboard from './pages/Dashboard'
import ScanRemediate from './pages/RunReport'
import PolicyLibrary from './pages/PolicyLibrary'
import PolicyBuilder from './pages/PolicyBuilder'
import RunHistory from './pages/RunHistory'
import Settings from './pages/Settings'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<Navigate to="/dashboard" replace />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/scan"      element={<ScanRemediate />} />
        <Route path="/library"   element={<PolicyLibrary />} />
        <Route path="/build"     element={<PolicyBuilder />} />
        <Route path="/history"   element={<RunHistory />} />
        <Route path="/settings"  element={<Settings />} />
        <Route path="/policies"  element={<Navigate to="/library" replace />} />
        <Route path="/builder"   element={<Navigate to="/build" replace />} />
        <Route path="/"          element={<Navigate to="/dashboard" replace />} />
      </Route>
    </Routes>
  )
}
