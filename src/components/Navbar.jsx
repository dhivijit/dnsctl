import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Github } from 'lucide-react'

export default function Navbar() {
  const [scrolled, setScrolled] = useState(false)

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40)
    window.addEventListener('scroll', onScroll)
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  return (
    <motion.nav
      initial={{ y: -80, opacity: 0 }}
      animate={{ y: 0, opacity: 1 }}
      transition={{ duration: 0.6, ease: [0.22, 1, 0.36, 1] }}
      style={{
        position: 'fixed',
        top: 0,
        left: 0,
        right: 0,
        zIndex: 100,
        padding: '0 2rem',
        height: '64px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        backdropFilter: scrolled ? 'blur(20px)' : 'none',
        background: scrolled ? 'rgba(8, 11, 16, 0.85)' : 'transparent',
        borderBottom: scrolled ? '1px solid rgba(0,212,255,0.08)' : '1px solid transparent',
        transition: 'all 0.3s ease',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <img src="/icon.png" alt="dnsctl logo" style={{ width: 28, height: 28 }} />
        <span style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontWeight: 600,
          fontSize: '1.1rem',
          color: 'var(--white)',
          letterSpacing: '-0.02em',
        }}>
          dnsctl
        </span>
      </div>

      <a
        href="https://l.dhivijit.dev/dnsctl"
        target="_blank"
        rel="noopener noreferrer"
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '8px 16px',
          borderRadius: '8px',
          border: '1px solid rgba(0,212,255,0.25)',
          color: 'var(--cyan)',
          textDecoration: 'none',
          fontSize: '0.875rem',
          fontWeight: 500,
          transition: 'all 0.2s ease',
          background: 'rgba(0,212,255,0.05)',
        }}
        onMouseEnter={e => {
          e.currentTarget.style.background = 'rgba(0,212,255,0.12)'
          e.currentTarget.style.borderColor = 'rgba(0,212,255,0.5)'
        }}
        onMouseLeave={e => {
          e.currentTarget.style.background = 'rgba(0,212,255,0.05)'
          e.currentTarget.style.borderColor = 'rgba(0,212,255,0.25)'
        }}
      >
        <Github size={16} />
        GitHub
      </a>
    </motion.nav>
  )
}
