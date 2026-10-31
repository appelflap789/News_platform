// Videos (YouTube): the thumbnail with a play mark and the length, and the channel and views underneath.

import Icon from '../components/Icon.jsx'
import { compact } from '../lib/format.js'
import { CardFrame, CardText, Thumb } from './parts.jsx'

function VideoCard({ article, onOpen, onRemove, onFavorite, showSource = true, snippet = false }) {
  const channel = article.author && article.author !== article.source_name ? article.author : ''
  const views = article.views ? `${compact(article.views)} views` : ''
  return (
    <CardFrame onOpen={onOpen} onRemove={onRemove} onFavorite={onFavorite} favorite={Boolean(article.favorite_at)} className="card--video">
      <Thumb article={article} icon="play">
        <span className="thumb__play">
          <Icon name="play" size={22} />
        </span>
      </Thumb>
      <CardText
        article={article}
        showSource={showSource}
        snippet={snippet}
        extra={[channel, views].filter(Boolean).join(' · ')}
      />
    </CardFrame>
  )
}

export default { types: ['video'], component: VideoCard }
