// Renders Markdown written by Claude (structure reports, briefings). Raw HTML in the text is not rendered.

import ReactMarkdown from 'react-markdown'
import { useApp } from '../lib/app.jsx'

/**
 * `citations` maps a number to an article id. A "[3]" in the text then becomes a link that opens
 * that article in the reader.
 */
export default function Markdown({ text, citations }) {
  const { openReader } = useApp()
  let source = text || ''
  if (citations) {
    source = source.replace(/\[(\d+)\]/g, (whole, number) =>
      citations[number] ? `[\\[${number}\\]](#article-${citations[number]})` : whole,
    )
  }
  const ids = citations ? [...new Set(Object.values(citations))] : []

  return (
    <div className="markdown">
      <ReactMarkdown
        components={{
          a({ href, children }) {
            if (href && href.startsWith('#article-')) {
              const id = Number(href.slice('#article-'.length))
              return (
                <a
                  href={href}
                  className="citation"
                  onClick={(event) => {
                    event.preventDefault()
                    openReader(id, ids)
                  }}
                >
                  {children}
                </a>
              )
            }
            return (
              <a href={href} target="_blank" rel="noreferrer">
                {children}
              </a>
            )
          },
        }}
      >
        {source}
      </ReactMarkdown>
    </div>
  )
}
