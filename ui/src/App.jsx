import { Routes, Route } from 'react-router-dom'
import Layout from './components/Layout'
import RunReport from './pages/RunReport'
import RunHistory from './pages/RunHistory'
import Settings from './pages/Settings'
import PolicyBuilder from './pages/PolicyBuilder'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<RunReport />} />
        <Route path="/builder" element={<PolicyBuilder />} />
        <Route path="/history" element={<RunHistory />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
    </Routes>
  )
}
