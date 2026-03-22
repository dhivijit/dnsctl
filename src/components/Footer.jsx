import { motion, useInView } from 'framer-motion'
import { useRef } from 'react'
import { Github, Star } from 'lucide-react'

export default function Footer() {
  const ref = useRef()
  const inView = useInView(ref, { once: true, margin: '-60px' })

  return (
    <footer style={{
      borderTop: '1px solid rgba(255,255,255,0.05)',
      padding: '5rem 2rem 3rem',
    }}>
      <motion.div
        ref={ref}
        initial={{ opacity: 0, y: 24 }}
        animate={inView ? { opacity: 1, y: 0 } : {}}
        transition={{ duration: 0.6 }}
        style={{
          maxWidth: '700px',
          margin: '0 auto',
          textAlign: 'center',
          marginBottom: '4rem',
        }}
      >
        <div style={{
          width: 60,
          height: 60,
          borderRadius: '16px',
          border: '1px solid rgba(0,212,255,0.2)',
          background: 'rgba(0,212,255,0.06)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          margin: '0 auto 1.5rem',
        }}>
          <img src="/icon.png" alt="dnsctl" style={{ width: 36, height: 36 }} />
        </div>

        <h2 style={{
          fontSize: 'clamp(1.6rem, 4vw, 2.5rem)',
          fontWeight: 700,
          color: 'var(--white)',
          letterSpacing: '-0.03em',
          marginBottom: '1rem',
          lineHeight: 1.2,
        }}>
          Built for developers who care<br />about their infrastructure.
        </h2>
        <p style={{
          color: 'var(--text)',
          fontSize: '1rem',
          lineHeight: 1.7,
          marginBottom: '2.5rem',
          maxWidth: '480px',
          margin: '0 auto 2.5rem',
        }}>
          dnsctl is open source and free to use. If it saves you from accidentally deleting a DNS record at 2am, consider leaving a star.
        </p>

        <a
          href="https://l.dhivijit.dev/dnsctl"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: '10px',
            padding: '14px 28px',
            borderRadius: '12px',
            background: 'var(--cyan)',
            color: '#080B10',
            fontWeight: 700,
            fontSize: '1rem',
            textDecoration: 'none',
            transition: 'opacity 0.2s, transform 0.2s',
          }}
          onMouseEnter={e => { e.currentTarget.style.opacity = '0.88'; e.currentTarget.style.transform = 'scale(1.02)' }}
          onMouseLeave={e => { e.currentTarget.style.opacity = '1'; e.currentTarget.style.transform = 'scale(1)' }}
        >
          <Github size={18} />
          Star on GitHub
          <Star size={16} />
        </a>
      </motion.div>

      <div style={{
        maxWidth: '1100px',
        margin: '0 auto',
        borderTop: '1px solid rgba(255,255,255,0.05)',
        paddingTop: '2rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        flexWrap: 'wrap',
        gap: '1rem',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <img src="/icon.png" alt="dnsctl" style={{ width: 20, height: 20 }} />
          <span style={{
            fontFamily: "'JetBrains Mono', monospace",
            fontSize: '0.875rem',
            color: 'var(--text)',
          }}>
            dnsctl
          </span>
        </div>
        <p style={{ fontSize: '0.8rem', color: '#374151' }}>
          MIT License · Built by{' '}
          <a
            href="https://github.com/dhivijit"
            target="_blank"
            rel="noopener noreferrer"
            style={{ color: 'var(--text)', textDecoration: 'none' }}
            onMouseEnter={e => e.currentTarget.style.color = 'var(--cyan)'}
            onMouseLeave={e => e.currentTarget.style.color = 'var(--text)'}
          >
            Dhivijit Koppuravuri
          </a>
        </p>
        <a
          href="https://l.dhivijit.dev/dnsctl"
          target="_blank"
          rel="noopener noreferrer"
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '6px',
            fontSize: '0.8rem',
            color: 'var(--text)',
            textDecoration: 'none',
            transition: 'color 0.2s',
          }}
          onMouseEnter={e => e.currentTarget.style.color = 'var(--cyan)'}
          onMouseLeave={e => e.currentTarget.style.color = 'var(--text)'}
        >
          <Github size={14} /> github.com/dhivijit/dnsctl
        </a>
      </div>
    </footer>
  )
}
