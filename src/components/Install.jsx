import { useRef, useState } from 'react'
import { motion, useInView } from 'framer-motion'
import { Copy, Check, Download } from 'lucide-react'
import { useLatestExe } from '../hooks/useLatestExe'

const INSTALL_STEPS = [
  { label: 'Install via pip', cmd: 'pip install dnsctl-app' },
  { label: 'Add your Cloudflare token', cmd: 'dnsctl login --alias personal' },
  { label: 'Sync your DNS records', cmd: 'dnsctl sync' },
  { label: 'Preview changes', cmd: 'dnsctl plan' },
  { label: 'Want to use the GUI ?', cmd: 'dnsctl-g' },
]

function CodeBlock({ cmd, label }) {
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText(cmd)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div style={{ marginBottom: '1rem' }}>
      <p style={{
        fontSize: '0.78rem',
        color: 'var(--text)',
        marginBottom: '0.5rem',
        fontFamily: "'JetBrains Mono', monospace",
      }}>
        # {label}
      </p>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        background: 'rgba(13,17,23,0.9)',
        border: '1px solid rgba(0,212,255,0.12)',
        borderRadius: '10px',
        padding: '12px 16px',
        gap: '12px',
      }}>
        <span style={{
          color: 'var(--cyan)',
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: '0.9rem',
          flex: 1,
        }}>
          {cmd}
        </span>
        <button
          onClick={copy}
          style={{
            background: 'none',
            border: 'none',
            cursor: 'pointer',
            color: copied ? '#00ff88' : 'var(--text)',
            display: 'flex',
            alignItems: 'center',
            padding: '4px',
            borderRadius: '6px',
            transition: 'color 0.2s',
          }}
        >
          {copied ? <Check size={15} /> : <Copy size={15} />}
        </button>
      </div>
    </div>
  )
}

export default function Install() {
  const ref = useRef()
  const inView = useInView(ref, { once: true, margin: '-80px' })
  const exeUrl = useLatestExe()

  return (
    <section style={{
      padding: '6rem 2rem',
      maxWidth: '720px',
      margin: '0 auto',
    }}>
      <motion.div
        ref={ref}
        initial={{ opacity: 0, y: 30 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
      >
        <p style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: '0.78rem',
          color: 'var(--cyan)',
          textTransform: 'uppercase',
          letterSpacing: '0.15em',
          marginBottom: '1rem',
          textAlign: 'center',
        }}>
          Get started
        </p>
        <h2 style={{
          fontSize: 'clamp(1.8rem, 4vw, 2.8rem)',
          fontWeight: 700,
          color: 'var(--white)',
          letterSpacing: '-0.03em',
          marginBottom: '0.75rem',
          textAlign: 'center',
        }}>
          Up and running in minutes
        </h2>
        <p style={{
          color: 'var(--text)',
          fontSize: '1rem',
          lineHeight: 1.7,
          marginBottom: '2.5rem',
          textAlign: 'center',
        }}>
          Requires Python 3.11+. Works on Windows, macOS, and Linux.
        </p>

        <div style={{
          background: 'rgba(8,11,16,0.6)',
          border: '1px solid rgba(0,212,255,0.1)',
          borderRadius: '16px',
          padding: '2rem',
          backdropFilter: 'blur(12px)',
          boxShadow: '0 0 60px rgba(0,212,255,0.04)',
        }}>
          {INSTALL_STEPS.map((step) => (
            <CodeBlock key={step.cmd} cmd={step.cmd} label={step.label} />
          ))}
        </div>

        <div style={{ marginTop: '1.5rem', textAlign: 'center' }}>
          <p style={{ fontSize: '0.875rem', color: 'var(--text)', marginBottom: '0.75rem' }}>
            Prefer a GUI?
          </p>
          <a
            href={exeUrl ?? 'https://github.com/dhivijit/dnsctl/releases'}
            target={exeUrl ? '_self' : '_blank'}
            rel="noopener noreferrer"
            download={!!exeUrl}
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: '8px',
              padding: '10px 20px',
              borderRadius: '10px',
              border: '1px solid rgba(0,212,255,0.25)',
              color: 'var(--cyan)',
              textDecoration: 'none',
              fontSize: '0.875rem',
              fontWeight: 500,
              background: 'rgba(0,212,255,0.05)',
              transition: 'all 0.2s ease',
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
            <Download size={15} />
            Download the desktop app (.exe)
          </a>
          {!exeUrl && (
            <p style={{ marginTop: '0.5rem', fontSize: '0.75rem', color: '#374151' }}>
              No release found — link goes to releases page
            </p>
          )}
        </div>
      </motion.div>
    </section>
  )
}
