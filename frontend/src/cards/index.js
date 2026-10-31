// Card registry. Every file in this folder named *Card.jsx is picked up automatically. A card file
// default-exports { types: [...content types it draws], component, fallback?: true }.
//
// To give a content type its own look, add a file here; nothing else needs to change.

const modules = import.meta.glob('./*Card.jsx', { eager: true })

const byType = {}
let fallback = null

for (const module of Object.values(modules)) {
  const card = module.default
  if (!card?.component) continue
  for (const type of card.types || []) byType[type] = card.component
  if (card.fallback) fallback = card.component
}

export function cardFor(contentType) {
  return byType[contentType] || fallback
}
