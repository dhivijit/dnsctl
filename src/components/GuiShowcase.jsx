import { useRef } from 'react'
import { motion, useInView, useScroll, useTransform } from 'framer-motion'

export default function GuiShowcase() {
  const sectionRef = useRef()
  const headRef = useRef()
  const headInView = useInView(headRef, { once: true, margin: '-80px' })
  const { scrollYProgress } = useScroll({ target: sectionRef, offset: ['start end', 'end start'] })
  const y1 = useTransform(scrollYProgress, [0, 1], [40, -40])

  return (
    <section
      ref={sectionRef}
      style={{
        padding: '6rem 2rem',
        maxWidth: '1200px',
        margin: '0 auto',
      }}
    >
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
          GUI
        </p>
        <h2 style={{
          fontSize: 'clamp(1.8rem, 4vw, 2.8rem)',
          fontWeight: 700,
          color: 'var(--white)',
          letterSpacing: '-0.03em',
          lineHeight: 1.2,
        }}>
          A desktop app, when you want it
        </h2>
        <p style={{
          marginTop: '1rem',
          color: 'var(--text)',
          fontSize: '1.05rem',
          maxWidth: '480px',
          margin: '1rem auto 0',
        }}>
          All the power of the CLI, wrapped in a native PyQt6 interface.
        </p>
      </motion.div>

      <div style={{
        display: 'flex',
        gap: '2rem',
        justifyContent: 'center',
        alignItems: 'flex-start',
        flexWrap: 'wrap',
      }}>
        <motion.div
          style={{ y: y1, width: '100%', maxWidth: '700px' }}
        >
          <motion.div
            initial={{ opacity: 0, x: -30 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true, margin: '-80px' }}
            transition={{ duration: 0.7, ease: [0.22, 1, 0.36, 1] }}
            style={{
              borderRadius: '14px',
              overflow: 'hidden',
              border: '1px solid rgba(0,212,255,0.15)',
              boxShadow: '0 0 40px rgba(0,212,255,0.06), 0 20px 60px rgba(0,0,0,0.6)',
            }}
          >
            <div style={{
              background: 'rgba(13,17,23,0.8)',
              padding: '10px 14px',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              borderBottom: '1px solid rgba(255,255,255,0.05)',
            }}>
              {['#ff5f57','#ffbd2e','#28c840'].map(c => (
                <div key={c} style={{ width: 10, height: 10, borderRadius: '50%', background: c }} />
              ))}
              <span style={{
                fontFamily: "'JetBrains Mono', monospace",
                fontSize: '0.7rem',
                color: '#4a5568',
                marginLeft: 6,
              }}>DNSCTL — Cloudflare DNS Manager</span>
            </div>
            <img
              src="/dnsctl-gui.png"
              alt="dnsctl main window showing DNS records"
              style={{ width: '100%', display: 'block' }}
            />
          </motion.div>
          <p style={{
            marginTop: '1rem',
            textAlign: 'center',
            fontSize: '0.8rem',
            color: 'var(--text)',
            fontFamily: "'JetBrains Mono', monospace",
          }}>
            Main window — browse all DNS records across zones
          </p>
        </motion.div>

      </div>
    </section>
  )
}
