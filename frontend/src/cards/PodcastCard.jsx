// Podcast episodes: the show's cover with a play mark and the length, and the show underneath.

import Icon from '../components/Icon.jsx'
import { CardFrame, CardText, Thumb } from './parts.jsx'

function PodcastCard({ article, onOpen, onRemove, onFavorite, showSource = true, snippet = false }) {
  const show = article.author && article.author !== article.source_name ? article.author : ''
  return (
    <CardFrame onOpen={onOpen} onRemove={onRemove} onFavorite={onFavorite} favorite={Boolean(article.favorite_at)} className="card--video card--podcast">
      <Thumb article={article} icon="play">
        <span className="thumb__play">
          <Icon name="play" size={22} />
        </span>
      </Thumb>
      <CardText article={article} showSource={showSource} snippet={snippet} extra={show} />
    </CardFrame>
  )
}

export default { types: ['podcast'], component: PodcastCard }
