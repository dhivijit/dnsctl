import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { gsap } from 'gsap'
import { ArrowRight, Download } from 'lucide-react'
import { useLatestExe } from '../hooks/useLatestExe'

const TERMINAL_LINES = [
  { text: '$ dnsctl accounts switch personal', delay: 0, type: 'cmd' },
  { text: "  Switched to account 'personal'.", delay: 600, type: 'out' },
  { text: '$ dnsctl sync', delay: 1400, type: 'cmd' },
  { text: '  Synced dhivijit.dev  (17 records, hash=4a72c94acc8a)', delay: 2000, type: 'out' },
  { text: '$ dnsctl add --type A --name staging.dhivijit.dev --content 1.2.3.4', delay: 3000, type: 'cmd' },
  { text: '  Added A staging.dhivijit.dev → 1.2.3.4', delay: 3700, type: 'out' },
  { text: '$ dnsctl plan', delay: 4500, type: 'cmd' },
  { text: '  dhivijit.dev: +1 create', delay: 5100, type: 'out' },
  { text: '    + CREATE A      staging.dhivijit.dev → 1.2.3.4', delay: 5200, type: 'create' },
  { text: '$ dnsctl apply', delay: 6200, type: 'cmd' },
  { text: '  Apply changes to Cloudflare? [y/N]: y', delay: 6800, type: 'out' },
  { text: '  ✓ Applied 1 change(s).', delay: 7600, type: 'success' },
]

function TerminalLine({ line, show }) {
  const color = {
    cmd: '#e2e8f0',
    out: '#94a3b8',
    create: '#00D4FF',
    success: '#00ff88',
  }[line.type]

  return (
    <motion.div
      initial={{ opacity: 0, x: -8 }}
      animate={show ? { opacity: 1, x: 0 } : { opacity: 0, x: -8 }}
      transition={{ duration: 0.3 }}
      style={{
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: '0.8rem',
        lineHeight: '1.7',
        color,
        whiteSpace: 'pre',
      }}
    >
      {line.text}
    </motion.div>
  )
}

export default function Hero() {
  const [visibleLines, setVisibleLines] = useState([])
  const [loopKey, setLoopKey] = useState(0)
  const glowRef = useRef()
  const exeUrl = useLatestExe()

  useEffect(() => {
    const timers = []
    setVisibleLines([])

    TERMINAL_LINES.forEach((line, i) => {
      const t = setTimeout(() => {
        setVisibleLines(prev => [...prev, i])
      }, line.delay)
      timers.push(t)
    })

    const resetTimer = setTimeout(() => {
      setVisibleLines([])
      setLoopKey(k => k + 1)
    }, 10000)
    timers.push(resetTimer)

    return () => timers.forEach(clearTimeout)
  }, [loopKey])

  useEffect(() => {
    if (!glowRef.current) return
    gsap.to(glowRef.current, {
      opacity: 0.6,
      duration: 2,
      repeat: -1,
      yoyo: true,
      ease: 'sine.inOut',
    })
  }, [])

  return (
    <section style={{
      minHeight: '100vh',
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      justifyContent: 'center',
      padding: '80px 2rem 4rem',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* background glow */}
      <div ref={glowRef} style={{
        position: 'absolute',
        top: '20%',
        left: '50%',
        transform: 'translateX(-50%)',
        width: '600px',
        height: '400px',
        background: 'radial-gradient(ellipse, rgba(0,212,255,0.08) 0%, transparent 70%)',
        pointerEvents: 'none',
        opacity: 0.4,
      }} />

      {/* badge */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.1 }}
        style={{
          display: 'inline-flex',
          alignItems: 'center',
          gap: '8px',
          padding: '6px 14px',
          borderRadius: '999px',
          border: '1px solid rgba(0,212,255,0.25)',
          background: 'rgba(0,212,255,0.06)',
          color: 'var(--cyan)',
          fontSize: '0.78rem',
          fontWeight: 500,
          marginBottom: '2rem',
          fontFamily: "'JetBrains Mono', monospace",
        }}
      >
        <span style={{ width: 6, height: 6, borderRadius: '50%', background: '#00ff88', display: 'inline-block' }} />
        Open source · Cloudflare DNS Manager
      </motion.div>

      {/* headline */}
      <motion.h1
        initial={{ opacity: 0, y: 30 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.7, delay: 0.2, ease: [0.22, 1, 0.36, 1] }}
        style={{
          fontSize: 'clamp(2.4rem, 6vw, 5rem)',
          fontWeight: 700,
          color: 'var(--white)',
          textAlign: 'center',
          lineHeight: 1.1,
          letterSpacing: '-0.03em',
          marginBottom: '1.25rem',
          maxWidth: '800px',
        }}
      >
        Git-backed DNS management,<br />
        <span style={{ color: 'var(--cyan)' }}>without the dashboard.</span>
      </motion.h1>

      {/* subheading */}
      <motion.p
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.35 }}
        style={{
          fontSize: 'clamp(1rem, 2vw, 1.2rem)',
          color: 'var(--text)',
          textAlign: 'center',
          maxWidth: '560px',
          lineHeight: 1.7,
          marginBottom: '2.5rem',
        }}
      >
        Sync, diff, plan, and apply Cloudflare DNS changes safely from your terminal or GUI — with full git audit history.
      </motion.p>

      {/* CTAs */}
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, delay: 0.5 }}
        style={{ display: 'flex', gap: '1rem', flexWrap: 'wrap', justifyContent: 'center', marginBottom: '4rem' }}
      >
        <a
          href="https://l.dhivijit.dev/dnsctl"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '12px 24px',
            borderRadius: '10px',
            background: 'var(--cyan)',
            color: '#080B10',
            fontWeight: 600,
            fontSize: '0.95rem',
            textDecoration: 'none',
            transition: 'all 0.2s ease',
          }}
          onMouseEnter={e => e.currentTarget.style.opacity = '0.85'}
          onMouseLeave={e => e.currentTarget.style.opacity = '1'}
        >
          Get Started <ArrowRight size={16} />
        </a>
        <a
          href={exeUrl ?? 'https://github.com/dhivijit/dnsctl/releases'}
          target={exeUrl ? '_self' : '_blank'}
          rel="noopener noreferrer"
          download={!!exeUrl}
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '8px',
            padding: '12px 24px',
            borderRadius: '10px',
            border: '1px solid rgba(0,212,255,0.25)',
            color: 'var(--text-bright)',
            fontWeight: 500,
            fontSize: '0.95rem',
            textDecoration: 'none',
            transition: 'all 0.2s ease',
            background: 'rgba(255,255,255,0.03)',
          }}
          onMouseEnter={e => e.currentTarget.style.borderColor = 'rgba(0,212,255,0.5)'}
          onMouseLeave={e => e.currentTarget.style.borderColor = 'rgba(0,212,255,0.25)'}
        >
          <Download size={16} /> Download
        </a>
      </motion.div>

      {/* terminal */}
      <motion.div
        initial={{ opacity: 0, y: 40, scale: 0.97 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        transition={{ duration: 0.8, delay: 0.6, ease: [0.22, 1, 0.36, 1] }}
        style={{
          width: '100%',
          maxWidth: '680px',
          borderRadius: '14px',
          border: '1px solid rgba(0,212,255,0.15)',
          background: 'rgba(13,17,23,0.9)',
          backdropFilter: 'blur(12px)',
          overflow: 'hidden',
          boxShadow: '0 0 60px rgba(0,212,255,0.08), 0 24px 48px rgba(0,0,0,0.5)',
        }}
      >
        {/* title bar */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '8px',
          padding: '12px 16px',
          borderBottom: '1px solid rgba(255,255,255,0.06)',
          background: 'rgba(255,255,255,0.02)',
        }}>
          {['#ff5f57','#ffbd2e','#28c840'].map(c => (
            <div key={c} style={{ width: 12, height: 12, borderRadius: '50%', background: c }} />
          ))}
          <span style={{
            marginLeft: 8,
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '0.75rem',
            color: '#4a5568',
          }}>
            Terminal
          </span>
        </div>

        {/* terminal content */}
        <div style={{ padding: '20px 24px', minHeight: '260px' }}>
          {TERMINAL_LINES.map((line, i) => (
            <TerminalLine key={`${loopKey}-${i}`} line={line} show={visibleLines.includes(i)} />
          ))}
          <motion.span
            animate={{ opacity: [1, 0] }}
            transition={{ duration: 0.8, repeat: Infinity }}
            style={{
              display: 'inline-block',
              width: 8,
              height: 16,
              background: 'var(--cyan)',
              verticalAlign: 'text-bottom',
              marginLeft: 2,
            }}
          />
        </div>
      </motion.div>
    </section>
  )
}
