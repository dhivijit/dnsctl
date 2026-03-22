import { useRef } from 'react'
import { motion, useInView } from 'framer-motion'
import { LogIn, RefreshCw, GitBranch, Rocket } from 'lucide-react'

const STEPS = [
  {
    icon: LogIn,
    num: '01',
    title: 'Login',
    desc: 'Add your Cloudflare API token. It\'s encrypted with AES-GCM and stored securely in your OS keyring — never in plaintext.',
    accent: '#00D4FF',
  },
  {
    icon: RefreshCw,
    num: '02',
    title: 'Sync',
    desc: 'Pull all zones and DNS records from Cloudflare into a local git-tracked state. Every sync is a commit.',
    accent: '#00D4FF',
  },
  {
    icon: GitBranch,
    num: '03',
    title: 'Plan',
    desc: 'Make local edits, then run plan to see an exact diff of what will change — creates, updates, and deletes — before touching anything live.',
    accent: '#00D4FF',
  },
  {
    icon: Rocket,
    num: '04',
    title: 'Apply',
    desc: 'Confirm and push your changes to Cloudflare. dnsctl re-syncs and commits the final state, giving you a full audit trail.',
    accent: '#00ff88',
  },
]

function StepCard({ step, index }) {
  const ref = useRef()
  const inView = useInView(ref, { once: true, margin: '-80px' })
  const Icon = step.icon

  return (
    <motion.div
      ref={ref}
      initial={{ opacity: 0, y: 40 }}
      animate={inView ? { opacity: 1, y: 0 } : {}}
      transition={{ duration: 0.6, delay: index * 0.12, ease: [0.22, 1, 0.36, 1] }}
      style={{
        flex: '1 1 220px',
        maxWidth: '260px',
        padding: '2rem 1.5rem',
        borderRadius: '16px',
        border: '1px solid rgba(0,212,255,0.1)',
        background: 'rgba(13,17,23,0.6)',
        backdropFilter: 'blur(8px)',
        position: 'relative',
        transition: 'border-color 0.3s, transform 0.3s',
        cursor: 'default',
      }}
      whileHover={{ y: -4, borderColor: 'rgba(0,212,255,0.3)' }}
    >
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: '1.25rem',
      }}>
        <div style={{
          width: 44,
          height: 44,
          borderRadius: '12px',
          background: 'rgba(0,212,255,0.1)',
          border: '1px solid rgba(0,212,255,0.2)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}>
          <Icon size={20} color={step.accent} />
        </div>
        <span style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: '2rem',
          fontWeight: 700,
          color: 'rgba(0,212,255,0.12)',
          lineHeight: 1,
        }}>
          {step.num}
        </span>
      </div>
      <h3 style={{
        fontSize: '1.1rem',
        fontWeight: 600,
        color: 'var(--white)',
        marginBottom: '0.6rem',
      }}>
        {step.title}
      </h3>
      <p style={{
        fontSize: '0.875rem',
        color: 'var(--text)',
        lineHeight: 1.7,
      }}>
        {step.desc}
      </p>

      {index < STEPS.length - 1 && (
        <div style={{
          position: 'absolute',
          top: '50%',
          right: '-28px',
          transform: 'translateY(-50%)',
          color: 'rgba(0,212,255,0.2)',
          fontSize: '1.2rem',
          zIndex: 1,
          display: 'flex',
          alignItems: 'center',
        }}>
          →
        </div>
      )}
    </motion.div>
  )
}

export default function HowItWorks() {
  const headRef = useRef()
  const headInView = useInView(headRef, { once: true, margin: '-80px' })

  return (
    <section style={{
      padding: '7rem 2rem',
      maxWidth: '1200px',
      margin: '0 auto',
    }}>
      <motion.div
        ref={headRef}
        initial={{ opacity: 0, y: 24 }}
        animate={headInView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6 }}
        style={{ textAlign: 'center', marginBottom: '4rem' }}
      >
        <p style={{
          fontFamily: "'JetBrains Mono', monospace",
          fontSize: '0.78rem',
          color: 'var(--cyan)',
          textTransform: 'uppercase',
          letterSpacing: '0.15em',
          marginBottom: '1rem',
        }}>
          How it works
        </p>
        <h2 style={{
          fontSize: 'clamp(1.8rem, 4vw, 2.8rem)',
          fontWeight: 700,
          color: 'var(--white)',
          letterSpacing: '-0.03em',
          lineHeight: 1.2,
        }}>
          A workflow you can trust
        </h2>
        <p style={{
          marginTop: '1rem',
          color: 'var(--text)',
          fontSize: '1.05rem',
          maxWidth: '500px',
          margin: '1rem auto 0',
        }}>
          Inspired by Terraform's plan/apply pattern, built for DNS.
        </p>
      </motion.div>

      <div style={{
        display: 'flex',
        gap: '2.5rem',
        justifyContent: 'center',
        flexWrap: 'wrap',
        position: 'relative',
      }}>
        {STEPS.map((step, i) => (
          <StepCard key={step.num} step={step} index={i} />
        ))}
      </div>
    </section>
  )
}
