// Reports, papers and standalone documents: the card says how long the piece is, since that is what
// separates a 40-page report from a news item.

import { CardFrame, CardText, Thumb } from './parts.jsx'

function DocumentCard({ article, onOpen, onRemove, onFavorite, showSource = true, snippet = false }) {
  const length = article.word_count > 1500 ? `${Math.round(article.word_count / 100) / 10}k words` : ''
  return (
    <CardFrame onOpen={onOpen} onRemove={onRemove} onFavorite={onFavorite} favorite={Boolean(article.favorite_at)} className="card--document">
      <Thumb article={article} icon="file" />
      <CardText article={article} showSource={showSource} snippet={snippet} extra={length} />
    </CardFrame>
  )
}

export default { types: ['report', 'paper', 'document'], component: DocumentCard }
