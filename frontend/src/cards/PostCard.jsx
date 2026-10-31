// Forum posts (Reddit): the author matters more than the outlet, and many posts have no picture.

import { CardFrame, CardText, Thumb } from './parts.jsx'

function PostCard({ article, onOpen, onRemove, onFavorite, showSource = true, snippet = false }) {
  return (
    <CardFrame onOpen={onOpen} onRemove={onRemove} onFavorite={onFavorite} favorite={Boolean(article.favorite_at)} className="card--post">
      <Thumb article={article} icon="post" />
      <CardText
        article={article}
        showSource={showSource}
        snippet={snippet}
        extra={article.author ? `u/${article.author}` : ''}
      />
    </CardFrame>
  )
}

export default { types: ['post'], component: PostCard }
