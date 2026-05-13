import { useState, useEffect } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { getUserGroups } from '../lib/userRules'

export default function Layout() {
  const location  = useLocation()
  const navigate  = useNavigate()
  const onLibrary = location.pathname === '/library'

  // Keep Policy Library section open when on that page
  const [libOpen,    setLibOpen]    = useState(onLibrary)
  const [customOpen, setCustomOpen] = useState(false)
  const [userGroups, setUserGroups] = useState([])

  useEffect(() => {
    setUserGroups(getUserGroups())
  }, [location]) // refresh group list on every nav

  useEffect(() => {
    if (onLibrary) setLibOpen(true)
  }, [onLibrary])

  // Active group from URL query param
  const activeGroup = new URLSearchParams(location.search).get('group') || 'security'

  function goGroup(gid) {
    navigate(`/library?group=${gid}`)
  }

  const groupLinkClass = (gid) =>
    `w-full text-left flex items-center gap-2 pl-8 pr-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${
      onLibrary && activeGroup === gid
        ? 'bg-blue-50 text-blue-700'
        : 'text-gray-500 hover:bg-gray-100 hover:text-gray-800'
    }`

  return (
    <div className="flex h-screen bg-gray-50">
      <aside className="w-56 bg-white border-r border-gray-200 flex flex-col shrink-0">
        {/* Logo */}
        <div className="px-5 py-4 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 rounded-lg bg-blue-600 flex items-center justify-center shrink-0">
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z"/>
              </svg>
            </div>
            <div>
              <h1 className="text-sm font-bold text-gray-900 leading-tight">automation-c7</h1>
              <p className="text-[10px] text-gray-400">AWS Governance</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 p-3 space-y-0.5 overflow-y-auto">
          <NavItem to="/dashboard" label="Dashboard"       icon={<DashboardIcon />} />
          <NavItem to="/scan"      label="Scan & Remediate" icon={<ScanIcon />} />

          {/* ── Policy Library (expandable) ── */}
          <div>
            <button
              onClick={() => setLibOpen(o => !o)}
              className={`w-full flex items-center justify-between px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                onLibrary
                  ? 'bg-blue-50 text-blue-700'
                  : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
              }`}
            >
              <span className="flex items-center gap-3">
                <LibraryIcon />
                Policy Library
              </span>
              <svg
                className={`w-3 h-3 transition-transform shrink-0 ${libOpen ? 'rotate-90' : ''}`}
                fill="none" stroke="currentColor" viewBox="0 0 24 24"
              >
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
              </svg>
            </button>

            {libOpen && (
              <div className="mt-0.5 space-y-0.5">
                {/* Security */}
                <button onClick={() => goGroup('security')} className={groupLinkClass('security')}>
                  <span className="text-[11px]">🔐</span>
                  <span>Security</span>
                </button>

                {/* Cost */}
                <button onClick={() => goGroup('cost')} className={groupLinkClass('cost')}>
                  <span className="text-[11px]">💰</span>
                  <span>Cost Optimization</span>
                </button>

                {/* Custom (expandable) */}
                <div>
                  <button
                    onClick={() => setCustomOpen(o => !o)}
                    className="w-full flex items-center justify-between pl-8 pr-3 py-1.5 rounded-lg text-xs font-medium text-gray-500 hover:bg-gray-100 hover:text-gray-800 transition-colors"
                  >
                    <span className="flex items-center gap-2">
                      <span className="text-[11px]">⭐</span>
                      <span>Custom</span>
                      {userGroups.length > 0 && (
                        <span className="px-1 py-0.5 text-[9px] font-bold rounded-full bg-gray-100 text-gray-500">
                          {userGroups.length}
                        </span>
                      )}
                    </span>
                    <svg
                      className={`w-2.5 h-2.5 transition-transform shrink-0 ${customOpen ? 'rotate-90' : ''}`}
                      fill="none" stroke="currentColor" viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7"/>
                    </svg>
                  </button>

                  {customOpen && (
                    <div className="ml-4 mt-0.5 space-y-0.5">
                      {userGroups.length === 0 ? (
                        <p className="pl-6 py-1 text-[11px] text-gray-400 italic">No custom groups yet</p>
                      ) : (
                        userGroups.map(g => (
                          <button key={g} onClick={() => goGroup(g)} className={groupLinkClass(g)}>
                            <span className="text-[11px]">·</span>
                            <span className="truncate">{g}</span>
                          </button>
                        ))
                      )}
                      <button
                        onClick={() => navigate('/build')}
                        className="w-full text-left pl-8 pr-3 py-1.5 text-[11px] text-blue-500 hover:text-blue-700 hover:bg-blue-50 rounded-lg transition-colors"
                      >
                        + Add group via Build Policy
                      </button>
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          <NavItem to="/build"   label="Build Policy" icon={<BuildIcon />} />
          <NavItem to="/history" label="Run History"  icon={<HistoryIcon />} />
          <NavItem to="/settings" label="Settings"    icon={<SettingsIcon />} />
        </nav>

        <div className="px-4 py-3 border-t border-gray-200">
          <p className="text-[10px] text-gray-400 font-mono">Cloud Custodian 0.9.35</p>
        </div>
      </aside>

      <main className="flex-1 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  )
}

function NavItem({ to, label, icon }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        `flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
          isActive
            ? 'bg-blue-50 text-blue-700'
            : 'text-gray-600 hover:bg-gray-100 hover:text-gray-900'
        }`
      }
    >
      {icon}
      {label}
    </NavLink>
  )
}

function DashboardIcon() {
  return <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6"/></svg>
}
function ScanIcon() {
  return <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4"/></svg>
}
function LibraryIcon() {
  return <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"/></svg>
}
function BuildIcon() {
  return <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"/></svg>
}
function HistoryIcon() {
  return <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/></svg>
}
function SettingsIcon() {
  return <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"/><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
}
