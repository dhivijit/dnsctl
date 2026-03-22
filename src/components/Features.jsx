import { useRef } from 'react'
import { motion, useInView } from 'framer-motion'
import { Shield, GitCommit, Terminal, Monitor, Layers, AlertTriangle } from 'lucide-react'

const FEATURES = [
  {
    icon: GitCommit,
    title: 'Full Git Audit Trail',
    desc: 'Every sync and apply creates a git commit. You always know what changed, when, and why.',
  },
  {
    icon: Shield,
    title: 'Encrypted Credentials',
    desc: 'API tokens are encrypted with AES-GCM + PBKDF2 and stored in your OS keyring. Never written in plaintext.',
  },
  {
    icon: AlertTriangle,
    title: 'Drift Detection',
    desc: 'Detects when your local state diverges from Cloudflare. Warns you before you overwrite remote changes.',
  },
  {
    icon: Terminal,
    title: 'Powerful CLI',
    desc: 'Full-featured Click-based CLI. Script it, alias it, or drop it into CI pipelines.',
  },
  {
    icon: Monitor,
    title: 'Native GUI',
    desc: 'A PyQt6 desktop app for those who prefer a visual interface — with all the same capabilities.',
  },
  {
    icon: Layers,
    title: 'Multi-Account',
    desc: 'Manage multiple Cloudflare accounts with named aliases. Switch context in one command.',
  },
]

function FeatureCard({ feature, index }) {
  const ref = useRef()
  const inView = useInView(ref, { once: true, margin: '-60px' })
  const Icon = feature.icon

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 32 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.55, delay: (index % 3) * 0.1, ease: [0.22, 1, 0.36, 1] }}
      whileHover={{ y: -4 }}
      style={{
        padding: '1.75rem',
        borderRadius: '14px',
        border: '1px solid rgba(255,255,255,0.06)',
        background: 'rgba(13,17,23,0.5)',
        transition: 'border-color 0.3s',
        cursor: 'default',
      }}
      onMouseEnter={e => e.currentTarget.style.borderColor = 'rgba(0,212,255,0.2)'}
      onMouseLeave={e => e.currentTarget.style.borderColor = 'rgba(255,255,255,0.06)'}
    >
      <div style={{
        width: 40,
        height: 40,
        borderRadius: '10px',
        background: 'rgba(0,212,255,0.08)',
        border: '1px solid rgba(0,212,255,0.15)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        marginBottom: '1.1rem',
      }}>
        <Icon size={18} color="#00D4FF" />
      </div>
      <h3 style={{
        fontSize: '1rem',
        fontWeight: 600,
        color: 'var(--white)',
        marginBottom: '0.5rem',
      }}>
        {feature.title}
      </h3>
      <p style={{
        fontSize: '0.875rem',
        color: 'var(--text)',
        lineHeight: 1.7,
      }}>
        {feature.desc}
      </p>
    </motion.div>
  )
}

export default function Features() {
  const headRef = useRef()
  const headInView = useInView(headRef, { once: true, margin: '-80px' })

  return (
    <section style={{
      padding: '6rem 2rem',
      maxWidth: '1100px',
      margin: '0 auto',
    }}>
      <motion.div
        ref={headRef}
        initial={{ opacity: 0, y: 24 }}
        animate={headInView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6 }}
        style={{ textAlign: 'center', marginBottom: '3.5rem' }}
      >
        <p style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: '0.78rem',
          color: 'var(--cyan)',
          textTransform: 'uppercase',
          letterSpacing: '0.15em',
          marginBottom: '1rem',
        }}>
          Features
        </p>
        <h2 style={{
          fontSize: 'clamp(1.8rem, 4vw, 2.8rem)',
          fontWeight: 700,
          color: 'var(--white)',
          letterSpacing: '-0.03em',
        }}>
          Everything you need, nothing you don't
        </h2>
      </motion.div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))',
        gap: '1.25rem',
      }}>
        {FEATURES.map((f, i) => (
          <FeatureCard key={f.title} feature={f} index={i} />
        ))}
      </div>
    </section>
  )
}
