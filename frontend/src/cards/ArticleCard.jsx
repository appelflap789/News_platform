// The standard card: picture, title, source, age. Used for articles and news, and for any type without
// a card of its own.

import { CardFrame, CardText, Thumb } from './parts.jsx'

function ArticleCard({ article, onOpen, onRemove, onFavorite, showSource = true, snippet = false }) {
  return (
    <CardFrame onOpen={onOpen} onRemove={onRemove} onFavorite={onFavorite} favorite={Boolean(article.favorite_at)}>
      <Thumb article={article} icon="news" />
      <CardText article={article} showSource={showSource} snippet={snippet} />
    </CardFrame>
  )
}

export default { types: ['article', 'news', 'other'], fallback: true, component: ArticleCard }
