import { useState, useEffect } from 'react'

export function useLatestExe() {
  const [exeUrl, setExeUrl] = useState(null)

  useEffect(() => {
    fetch('https://api.github.com/repos/dhivijit/dnsctl/releases/latest')
      .then(r => r.json())
      .then(data => {
        const asset = data.assets?.find(a => a.name.endsWith('.exe'))
        const url = asset?.browser_download_url
        if (url && url.startsWith('https://github.com/')) setExeUrl(url)
      })
      .catch(() => {})
  }, [])

  return exeUrl
}
